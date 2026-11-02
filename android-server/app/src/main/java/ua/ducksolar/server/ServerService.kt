package ua.ducksolar.b2.server

import android.app.*
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.util.Log
import java.util.concurrent.Executors

class ServerService : Service() {
    companion object {
        private val lifecycleWorker=Executors.newSingleThreadExecutor()
        @Volatile private var activeService:ServerService?=null
        val cpuHeld:Boolean get()=activeService?.cpuLock?.isHeld==true
        val wifiHeld:Boolean get()=activeService?.wifiLock?.isHeld==true
        @Volatile var foreground=false
    }
    private val worker=lifecycleWorker
    private var stopping=false
    @Volatile private var stopped=false
    private lateinit var resources: ResourceJournal
    private var starting = false
    private var cpuLock:android.os.PowerManager.WakeLock?=null
    private var wifiLock:android.net.wifi.WifiManager.WifiLock?=null
    private lateinit var maintenance:MaintenanceScheduler
    private lateinit var environment:ServerEnvironment
    override fun onBind(intent: Intent?): IBinder? = null
    override fun onCreate() {
        super.onCreate()
        activeService=this
        val power=getSystemService(android.os.PowerManager::class.java)
        cpuLock=power.newWakeLock(android.os.PowerManager.PARTIAL_WAKE_LOCK,"DuckSolar:server").apply { setReferenceCounted(false);acquire() }
        val wifi=applicationContext.getSystemService(android.net.wifi.WifiManager::class.java)
        wifiLock=wifi.createWifiLock(android.net.wifi.WifiManager.WIFI_MODE_FULL_HIGH_PERF,"DuckSolar:server").apply { setReferenceCounted(false);acquire() }
        resources = ResourceJournal(this); resources.start()
        maintenance=MaintenanceScheduler(this);maintenance.start()
        environment=ServerEnvironment(this);environment.start()
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel("server", ua.ducksolar.shared.UiLanguage.text("Робота сервера"), NotificationManager.IMPORTANCE_LOW))
    }
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == "STOP") {
            if(stopping)return START_NOT_STICKY
            stopping=true;Bridge.state="Повернення логера на прямий ESS…"
            worker.execute {
                try { val result=Bridge.stop();stopped=true;Bridge.state=if(result.optBoolean("route_restored",true))"Сервер зупинено • логер працює напряму з ESS" else "Сервер зупинено • ESS не підтверджено: "+result.optString("route_error") }
                catch (error: Exception) { Bridge.state = "Помилка зупинки: ${error.message}" }
                finally { stopForeground(STOP_FOREGROUND_REMOVE); stopSelf() }
            }
            return START_NOT_STICKY
        }
        if(stopping)return START_NOT_STICKY
        val prefs=getSharedPreferences("MainActivity",MODE_PRIVATE)
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val notification = Notification.Builder(this, "server")
            .setContentTitle(ua.ducksolar.shared.UiLanguage.text("Duck Solar Server ${AppVersion.name(this)}"))
            .setContentText(ua.ducksolar.shared.UiLanguage.text("Сервер працює • натисніть для перегляду"))
            .setSmallIcon(android.R.drawable.presence_online).setContentIntent(open).setOngoing(true).build()
        if (Build.VERSION.SDK_INT >= 29) startForeground(1, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE)
        else startForeground(1, notification)
        foreground=true
        if (!starting) {
            starting = true
            val ip = intent?.getStringExtra("ip") ?: prefs.getString("ip","") ?: ""
            val pn = intent?.getStringExtra("pn") ?: prefs.getString("pn","") ?: ""
            val offline = intent?.getBooleanExtra("offline",true) ?: prefs.getBoolean("offline",true)
            Bridge.state = "Запуск сервера…"
            worker.execute {
                try {
                    Bridge.initialize(this)
                    if(intent?.getBooleanExtra("verify_update",false)==true)Bridge.verifyAfterUpdate()
                    Bridge.selfTest()
                    val mode=intent?.getStringExtra("equipment_mode") ?: prefs.getString("equipment_mode","normal") ?: "normal"
                    Bridge.start(ip, pn, offline,mode)
                    getSharedPreferences("ServerUpdate",MODE_PRIVATE).edit().putBoolean("resume",false).apply()
                    Bridge.state = if (offline) "Працює • без підключення до обладнання" else "Сервер запущено • підключення логера через Duck Solar"
                    Log.i("DuckSolar", "Server ready ${AppVersion.name(this)}; offline=$offline")
                } catch (error: Exception) {
                    Log.e("DuckSolar", "Server start failed", error)
                    Bridge.state = "Не вдалося запустити: ${error.message}"
                    stopForeground(STOP_FOREGROUND_REMOVE); stopSelf()
                }
            }
        }
        return if(prefs.getBoolean("server_enabled",false))START_STICKY else START_NOT_STICKY
    }
    override fun onTrimMemory(level:Int) {
        super.onTrimMemory(level)
        if(level==TRIM_MEMORY_UI_HIDDEN)return
        worker.execute {
            if(com.chaquo.python.Python.isStarted()) {
                val info=android.app.ActivityManager.MemoryInfo();getSystemService(android.app.ActivityManager::class.java).getMemoryInfo(info)
                com.chaquo.python.Python.getInstance().getModule("android_bridge").callAttr("resource_state",info.availMem,info.threshold,info.totalMem,true)
            }
        }
    }
    override fun onDestroy() {
        resources.stop()
        cpuLock?.let { if(it.isHeld)it.release() };cpuLock=null
        wifiLock?.let { if(it.isHeld)it.release() };wifiLock=null
        activeService=null;foreground=false
        maintenance.stop()
        environment.stop()
        if(!stopped)worker.execute { try { Bridge.stop() } catch (_: Exception) { } }
        super.onDestroy()
    }
}
