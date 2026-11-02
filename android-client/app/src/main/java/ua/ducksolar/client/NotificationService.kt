package ua.ducksolar.b2.client

import android.app.*
import android.content.Intent
import android.os.*
import org.json.JSONArray
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/** User-visible direct push connection to the paired inverter server. */
class NotificationService:Service() {
    companion object {
        @Volatile var running=false
        @Volatile var reliableLeaseHeld=false
        @Volatile private var instance:NotificationService?=null
        private val signalPending=java.util.concurrent.atomic.AtomicBoolean(false)
        @JvmStatic fun signal() { instance?.let { service -> if(running && signalPending.compareAndSet(false,true))try { service.timer.execute { try { service.guardedPump() } finally { signalPending.set(false) } } } catch(_:java.util.concurrent.RejectedExecutionException) { signalPending.set(false) } } }
    }
    private val timer=Executors.newSingleThreadScheduledExecutor()
    private var wake:PowerManager.WakeLock?=null
    private var lease:AlertWakeLease?=null
    private val powerReceiver=object:android.content.BroadcastReceiver() {
        override fun onReceive(context:android.content.Context,intent:Intent) { updateLease();signal() }
    }
    private fun updateLease() { if(running)lease?.update() else lease?.release();reliableLeaseHeld=lease?.held()==true }
    private var initialized=false
    private var lastResume=0L
    private var lastPump=0L
    private var lastWorkMs=0L
    private var lastBatteryProbe=0L
    private var lastHealth=""
    private var lastText=""
    private val networkChanged=java.util.concurrent.atomic.AtomicBoolean(false)
    private lateinit var networks:NetworkWatch
    private lateinit var manager:NotificationManager
    private fun contentIntent()=PendingIntent.getActivity(this,0,Intent(this,MainActivity::class.java),PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
    private fun ongoing(text:String)=Notification.Builder(this,"alert_connection").setSmallIcon(android.R.drawable.ic_dialog_info)
        .setContentTitle(ua.ducksolar.shared.UiLanguage.text("Duck Solar · сповіщення")).setContentText(ua.ducksolar.shared.UiLanguage.text(text)).setContentIntent(contentIntent())
        .setOngoing(true).setOnlyAlertOnce(true).setCategory(Notification.CATEGORY_SERVICE).build()
    override fun onCreate() {
        super.onCreate();running=true;instance=this
        manager=getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel("alert_connection",ua.ducksolar.shared.UiLanguage.text("З’єднання для сповіщень"),NotificationManager.IMPORTANCE_LOW))
        manager.createNotificationChannel(NotificationChannel("inverter_alerts",ua.ducksolar.shared.UiLanguage.text("Мережа та заряд акумуляторів"),NotificationManager.IMPORTANCE_HIGH))
        startForeground(4100,ongoing("Підключення до сервера…"))
        lease=AlertWakeLease(this);updateLease()
        registerReceiver(powerReceiver,android.content.IntentFilter().apply {
            addAction(Intent.ACTION_SCREEN_ON);addAction(Intent.ACTION_SCREEN_OFF);addAction(PowerManager.ACTION_DEVICE_IDLE_MODE_CHANGED)
        })
        networks=NetworkWatch(this) { updateLease();networkChanged.set(true);signal() };networks.start()
        wake=getSystemService(PowerManager::class.java).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"DuckSolar:ClientAlerts")
        timer.scheduleWithFixedDelay({ guardedPump() },0,30,TimeUnit.SECONDS)
    }
    private fun guardedPump() {
        if(!running)return
        try {
            updateLease()
            // Work lock protects this batch; the separate bounded lease protects screen-off scheduling.
            wake?.acquire(90000)
            pump()
        } catch(e:Exception) {
            lastWorkMs=(SystemClock.elapsedRealtime()-lastPump).coerceAtLeast(0)
            updateText("Очікування зв’язку із сервером")
            android.util.Log.w("DuckSolarClient","Alert delivery: ${e.javaClass.simpleName}")
        } finally { wake?.let { if(it.isHeld)it.release() } }
    }

    private fun updateText(text:String) { if(lastText!=text && running) { lastText=text;manager.notify(4100,ongoing(text)) } }
    private fun pump() {
        if(!AlertMonitoring.enabled(this) || !AlertMonitoring.permitted(this)) { stopSelf();return }
        if(!initialized) {
            val profile=ClientBridge.initialize(this)
            if(!profile.optBoolean("saved")) { stopSelf();return }
            initialized=true
        }
        val now=SystemClock.elapsedRealtime()
        val health=AlertMonitoring.health(this)
        if(now-lastBatteryProbe>=300000 || lastBatteryProbe==0L) {
            lastBatteryProbe=now
            val battery=registerReceiver(null,android.content.IntentFilter(Intent.ACTION_BATTERY_CHANGED))
            ClientBridge.backgroundEvent("energy",org.json.JSONObject().put("level",battery?.getIntExtra(BatteryManager.EXTRA_LEVEL,-1) ?: -1).put("scale",battery?.getIntExtra(BatteryManager.EXTRA_SCALE,100) ?: 100).put("plugged",battery?.getIntExtra(BatteryManager.EXTRA_PLUGGED,0) ?: 0).put("screen_on",getSystemService(PowerManager::class.java).isInteractive).put("wakelock_active",wake?.isHeld==true).put("reliable_lease_held",reliableLeaseHeld))
        }
        if(health.toString()!=lastHealth) { lastHealth=health.toString();ClientBridge.backgroundEvent("health",health) }
        if(lastPump>0 && now-lastPump>60000)ClientBridge.backgroundEvent("resume_gap",health.put("gap_s",(now-lastPump)/1000.0).put("previous_work_s",lastWorkMs/1000.0).put("idle_gap_s",((now-lastPump-lastWorkMs).coerceAtLeast(0))/1000.0))
        lastPump=now
        if(networkChanged.getAndSet(false)) { lastResume=now;ClientBridge.networkChanged() }
        else if(now-lastResume>10000 || lastResume==0L) { lastResume=now;ClientBridge.resume() }
        SolarWidget.capture(this,ClientBridge.snapshot())
        val batch=ClientBridge.notificationBatch()
        updateText(if(!AlertMonitoring.channelEnabled(this))"Канал сповіщень вимкнений в Android" else if(!batch.optBoolean("connected"))"Очікування зв’язку із сервером" else if(!batch.optBoolean("supported"))"Для сповіщень потрібен Server a1.4.22" else if(AlertMonitoring.reliableBackground(this) && !AlertMonitoring.batteryExempt(this))"Підключено · дозвольте роботу без обмежень батареї" else "Підключено · очікування подій")
        val rows=batch.optJSONArray("events") ?: return
        val ack=AlertDelivery(this).deliver(rows)
        if(ack.length()>0)ClientBridge.notificationAck(ack)
        lastWorkMs=(SystemClock.elapsedRealtime()-now).coerceAtLeast(0)
    }
    override fun onStartCommand(intent:Intent?,flags:Int,startId:Int):Int { updateLease();signal();return START_STICKY }
    override fun onBind(intent:Intent?)=null
    override fun onDestroy() {
        running=false;instance=null;timer.shutdownNow();try { unregisterReceiver(powerReceiver) } catch(_:IllegalArgumentException) {}
        lease?.release();reliableLeaseHeld=false;if(::networks.isInitialized)networks.stop();wake?.let { if(it.isHeld)it.release() }
        val cleanup=Executors.newSingleThreadExecutor()
        cleanup.execute { try { if(!ClientLifecycle.hasScreens())ClientBridge.stop() } catch(_:Exception) {} }
        cleanup.shutdown();super.onDestroy()
    }
}
