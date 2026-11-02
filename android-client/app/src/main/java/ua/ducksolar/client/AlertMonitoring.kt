package ua.ducksolar.b2.client

import android.Manifest
import android.app.Activity
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build

object AlertMonitoring {
    val legacy=listOf("grid_lost","grid_restored","server_battery","inverter_battery")
    val groups=linkedMapOf("inverter_connection" to "Зв’язок з інвертором", "server_connection" to "Доступність сервера", "grid_voltage" to "Неприйнятна напруга мережі", "overload" to "Високе навантаження", "over_temperature" to "Перегрів інвертора", "critical_battery" to "Критичний заряд АКБ", "server_power" to "Від’єднання сервера від зарядки", "storage" to "Місце та запис історії")
    val kindGroups=mapOf("inverter_lost" to "inverter_connection","inverter_restored" to "inverter_connection","server_lost" to "server_connection","server_restored" to "server_connection","grid_voltage_bad" to "grid_voltage","grid_voltage_ok" to "grid_voltage","overload_high" to "overload","overload_ok" to "overload","temperature_high" to "over_temperature","temperature_ok" to "over_temperature","battery_critical" to "critical_battery","battery_critical_ok" to "critical_battery","server_unplugged" to "server_power","server_plugged" to "server_power","storage_low" to "storage","storage_ok" to "storage","storage_error" to "storage")
    val kinds=legacy+kindGroups.keys
    fun eventEnabled(context:Context,kind:String):Boolean {
        val group=kindGroups[kind] ?: kind
        return context.getSharedPreferences("alerts",0).getBoolean(group,group in legacy)
    }
    fun enabled(context:Context)=(legacy+groups.keys).any { context.getSharedPreferences("alerts",0).getBoolean(it,it in legacy) }
    fun permitted(context:Context)=context.getSystemService(NotificationManager::class.java).areNotificationsEnabled() &&
        (Build.VERSION.SDK_INT<33 || context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)==PackageManager.PERMISSION_GRANTED)
    fun channelEnabled(context:Context):Boolean {
        val channel=context.getSystemService(NotificationManager::class.java).getNotificationChannel("inverter_alerts")
        return channel==null || channel.importance!=NotificationManager.IMPORTANCE_NONE
    }
    fun reliableBackground(context:Context)=context.getSharedPreferences("alerts",0).getBoolean("reliable_background",true)
    fun batteryExempt(context:Context)=context.getSystemService(android.os.PowerManager::class.java).isIgnoringBatteryOptimizations(context.packageName)
    fun serviceChannelEnabled(context:Context):Boolean {
        val channel=context.getSystemService(NotificationManager::class.java).getNotificationChannel("alert_connection")
        return channel==null || channel.importance!=NotificationManager.IMPORTANCE_NONE
    }
    fun health(context:Context)=org.json.JSONObject().put("battery_exempt",batteryExempt(context)).put("permitted",permitted(context)).put("reliable_background",reliableBackground(context)).put("reliable_lease_held",NotificationService.reliableLeaseHeld).put("device_idle",context.getSystemService(android.os.PowerManager::class.java).isDeviceIdleMode)
        .put("channel_enabled",channelEnabled(context)).put("service_channel_enabled",serviceChannelEnabled(context)).put("channel_importance",context.getSystemService(NotificationManager::class.java).getNotificationChannel("inverter_alerts")?.importance ?: -1).put("channel_sound",context.getSystemService(NotificationManager::class.java).getNotificationChannel("inverter_alerts")?.sound!=null).put("interruption_filter",context.getSystemService(NotificationManager::class.java).currentInterruptionFilter)
    fun openBatteryAccess(activity:Activity) {
        val intent=Intent(if(batteryExempt(activity))android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS else android.provider.Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
            .setData(android.net.Uri.parse("package:"+activity.packageName))
        try { activity.startActivity(intent) } catch(_:android.content.ActivityNotFoundException) { activity.startActivity(Intent(android.provider.Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)) }
    }
    fun start(context:Context) {
        if(enabled(context) && permitted(context)) {
            try { context.startForegroundService(Intent(context,NotificationService::class.java)) }
            catch(e:Exception) { android.util.Log.w("DuckSolarClient","Notification service start: ${e.javaClass.simpleName}") }
        } else context.stopService(Intent(context,NotificationService::class.java))
    }
    fun request(activity:Activity,explicit:Boolean=false) {
        val prefs=activity.getSharedPreferences("alerts",0)
        if(Build.VERSION.SDK_INT>=33 && activity.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)!=PackageManager.PERMISSION_GRANTED && (explicit || !prefs.getBoolean("permission_asked",false))) {
            prefs.edit().putBoolean("permission_asked",true).apply()
            activity.requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS),3874)
        } else start(activity)
    }
}
