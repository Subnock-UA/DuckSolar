package ua.ducksolar.b2.client

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.widget.*
import org.json.JSONObject
import java.util.concurrent.Executors

class NotificationSettingsActivity:ua.ducksolar.shared.LocalizedActivity() {
    private val worker=Executors.newSingleThreadExecutor()
    private lateinit var status:TextView
    private lateinit var health:TextView
    private val healthHandler=android.os.Handler(android.os.Looper.getMainLooper())
    private val healthPending=java.util.concurrent.atomic.AtomicBoolean(false)
    private val healthTick=object:Runnable {
        override fun run() {
            if(healthPending.compareAndSet(false,true))worker.execute {
                try {
                    val state=ClientBridge.snapshot()
                    val settings=ClientBridge.notificationSettings()
                    val text="Дозвіл Android: "+(if(AlertMonitoring.permitted(this@NotificationSettingsActivity))"є" else "немає")+
                        "\nКанал: "+(if(AlertMonitoring.channelEnabled(this@NotificationSettingsActivity))"увімкнений" else "вимкнений")+
                        "\nЗвук і банер залежать від налаштувань каналу Android та режиму «Не турбувати»."+
                        "\nСлужбовий канал: "+(if(AlertMonitoring.serviceChannelEnabled(this@NotificationSettingsActivity))"увімкнений" else "вимкнений")+
                        "\nОптимізація батареї: "+(if(AlertMonitoring.batteryExempt(this@NotificationSettingsActivity))"без обмежень Android" else "може призупиняти доставку")+
                        "\nНадійний фон: "+(if(AlertMonitoring.reliableBackground(this@NotificationSettingsActivity))"увімкнений" else "вимкнений")+
                        "\nФонова служба: "+(if(NotificationService.running)"працює" else "зупинена")+
                        "\n"+state.optString("connection_message","Очікування підключення")+
                        "\nНалаштування: "+(if(settings.optBoolean("pending"))"очікують синхронізації" else "збережені на сервері")
                    runOnUiThread { if(!isDestroyed)health.text=text }
                } catch(_:Exception) { } finally { healthPending.set(false) }
            }
            healthHandler.postDelayed(this,5000)
        }
    }
    override fun onCreate(state:Bundle?) {
        super.onCreate(state)
        val body=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL;setPadding(20,24,20,24) }
        setContentView(ScrollView(this).apply { addView(body) })
        body.setOnApplyWindowInsetsListener { _,insets -> body.setPadding(20+insets.systemWindowInsetLeft,24+insets.systemWindowInsetTop,20+insets.systemWindowInsetRight,24+insets.systemWindowInsetBottom);insets }
        fun label(value:String)=TextView(this).apply { text=value;textSize=16f;setPadding(0,12,0,12);body.addView(this) }
        Button(this).apply { text="‹ Налаштування";body.addView(this);setOnClickListener { finish() } }
        label("Сповіщення").textSize=26f
        label("Прямі сповіщення потребують роботи клієнта у фоні. Якщо Android заморожує додаток, доставка затримується до відновлення. Сервер зберігає події протягом 24 годин.")
        val titles=linkedMapOf("grid_lost" to "Відсутня напруга в мережі","grid_restored" to "Напруга в мережі відновлена","server_battery" to "Низький заряд батареї сервера","inverter_battery" to "Заряд АКБ інвертора не більше 30%").apply { putAll(AlertMonitoring.groups) }
        val prefs=getSharedPreferences("alerts",0)
        val reliable=Switch(this).apply {
            text="Надійна доставка з вимкненим екраном";isChecked=AlertMonitoring.reliableBackground(this@NotificationSettingsActivity);body.addView(this)
            setOnCheckedChangeListener { _,value -> prefs.edit().putBoolean("reliable_background",value).apply();AlertMonitoring.start(this@NotificationSettingsActivity) }
        }
        label("Увімкнено: клієнт підтримує роботу процесора з вимкненим екраном, поки дозволені сповіщення й доступна мережа. Це збільшує витрату батареї. Вимкнено: економніший режим, але Android може затримувати доставку. Для роботи в Doze потрібен дозвіл без обмежень батареї.")
        val switches=titles.mapValues { (key,title) -> Switch(this).apply { text=title;isChecked=prefs.getBoolean(key,key in AlertMonitoring.legacy);body.addView(this) } }
        label("Поріг батареї телефону сервера, %")
        val threshold=EditText(this).apply { inputType=android.text.InputType.TYPE_CLASS_NUMBER;setSingleLine();setText(prefs.getInt("server_battery_threshold",50).toString());body.addView(this) }
        label("Нові типи сповіщень вимкнені за замовчуванням. Перемикач також керує повідомленням про відновлення. Потребують Server b1.0.0; недоступність сервера визначає клієнт.")
        val limits=linkedMapOf(
            "connection_delay_s" to Triple("Втрата зв’язку: затримка, с",90,30..600),
            "grid_voltage_min" to Triple("Мінімальна напруга мережі, В",180,80..240),
            "grid_voltage_max" to Triple("Максимальна напруга мережі, В",260,200..300),
            "condition_delay_s" to Triple("Напруга / навантаження / температура: затримка, с",30,5..300),
            "overload_pct" to Triple("Попередження навантаження, %",90,50..100),
            "temperature_c" to Triple("Попередження температури, °C",65,40..100),
            "critical_battery_pct" to Triple("Критичний заряд АКБ, %",15,1..29),
            "power_delay_s" to Triple("Від’єднання зарядки: затримка, с",60,10..600),
            "storage_min_mb" to Triple("Мінімум вільного місця, МіБ",256,64..4096))
        val numeric=limits.mapValues { (key,rule)-> label(rule.first);EditText(this).apply { inputType=android.text.InputType.TYPE_CLASS_NUMBER;setSingleLine();setText(prefs.getInt(key,rule.second).toString());body.addView(this) } }
        status=label("Завантаження налаштувань…")
        health=label("Перевірка стану сповіщень…")
        val save=Button(this).apply { text="Зберегти";isEnabled=false;body.addView(this) }
        save.setOnClickListener {
            val number=threshold.text.toString().toIntOrNull()
            if(number==null || number !in 1..99) { threshold.error="Введіть від 1 до 99";return@setOnClickListener }
            val value=JSONObject().put("server_battery_threshold",number)
            for((key,field) in numeric) {
                val n=field.text.toString().toIntOrNull();val range=limits.getValue(key).third
                if(n==null || n !in range) { field.error="Введіть ${range.first}–${range.last}";return@setOnClickListener };value.put(key,n)
            }
            if(value.getInt("grid_voltage_min")>=value.getInt("grid_voltage_max")) { status.text="Мінімальна напруга має бути нижча за максимальну";return@setOnClickListener }
            val edit=prefs.edit().putInt("server_battery_threshold",number)
            numeric.keys.forEach { key->edit.putInt(key,value.getInt(key)) }
            switches.forEach { (key,toggle)->value.put(key,toggle.isChecked);edit.putBoolean(key,toggle.isChecked) };edit.apply()
            if(AlertMonitoring.enabled(this))AlertMonitoring.request(this,true) else AlertMonitoring.start(this)
            save.isEnabled=false
            worker.execute {
                try { val result=ClientBridge.notificationSettings(value.toString());runOnUiThread { status.text=if(result.optBoolean("pending"))"Збережено на клієнті. Сервер отримає налаштування після підключення." else "Збережено" } }
                catch(e:Exception) { runOnUiThread { status.text="Не вдалося зберегти: ${e.message}" } }
                finally { runOnUiThread { save.isEnabled=true } }
            }
        }
        Button(this).apply { text="Дозволити сповіщення Android";body.addView(this);setOnClickListener { AlertMonitoring.request(this@NotificationSettingsActivity,true) } }
        Button(this).apply { text="Системні налаштування сповіщень";body.addView(this);setOnClickListener { startActivity(Intent(android.provider.Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(android.provider.Settings.EXTRA_APP_PACKAGE,packageName)) } }
        for((id,title) in listOf("inverter_alerts" to "Канал подій інвертора", "alert_connection" to "Канал фонової служби"))Button(this).apply {
            text=title;body.addView(this);setOnClickListener {
                startActivity(Intent(android.provider.Settings.ACTION_CHANNEL_NOTIFICATION_SETTINGS)
                    .putExtra(android.provider.Settings.EXTRA_APP_PACKAGE,packageName).putExtra(android.provider.Settings.EXTRA_CHANNEL_ID,id))
            }
        }
        label("Android може затримувати пряме з’єднання в режимі енергозбереження. Пороги батарей спрацьовують при досягненні встановленого рівня; повторне попередження можливе після відновлення заряду щонайменше до 33%.")
        Button(this).apply { text="Дозволити роботу без обмежень батареї";body.addView(this);setOnClickListener { AlertMonitoring.openBatteryAccess(this@NotificationSettingsActivity) } }
        label("Samsung: перевірте «Батарея → Обмеження фонового використання». Duck Solar має бути поза сплячими списками; додайте до «Ніколи не сплячі», якщо доступно. Дозвіл Android не гарантує виключення з окремих обмежень Samsung.")
        CompactSections.apply(body)
        AppStyle.apply(body)
        worker.execute {
            try { ClientBridge.initialize(this);val result=ClientBridge.notificationSettings().getJSONObject("settings");runOnUiThread {
                switches.forEach { (key,toggle)->toggle.isChecked=result.optBoolean(key,key in AlertMonitoring.legacy) };threshold.setText(result.optInt("server_battery_threshold",50).toString());numeric.forEach { (key,field)->field.setText(result.optInt(key,limits.getValue(key).second).toString()) }
                status.text=if(AlertMonitoring.permitted(this))"Сповіщення Android дозволені" else "Дозвольте сповіщення Android для доставки";save.isEnabled=true
            } } catch(e:Exception) { runOnUiThread { status.text=e.message } }
        }
    }
    override fun onResume() { super.onResume();ClientLifecycle.enter();AlertMonitoring.start(this);healthHandler.post(healthTick) }
    override fun onPause() { healthHandler.removeCallbacks(healthTick);ClientLifecycle.leave();super.onPause() }
    override fun onRequestPermissionsResult(requestCode:Int,permissions:Array<out String>,grantResults:IntArray) { super.onRequestPermissionsResult(requestCode,permissions,grantResults);if(requestCode==3874)AlertMonitoring.start(this) }
    override fun onDestroy() { worker.shutdown();super.onDestroy() }
}
