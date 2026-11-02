package ua.ducksolar.b2.server
import android.content.*
class BootReceiver:BroadcastReceiver() {
    override fun onReceive(context:Context,intent:Intent) {
        if(intent.action!=Intent.ACTION_BOOT_COMPLETED)return
        val prefs=context.getSharedPreferences("MainActivity",Context.MODE_PRIVATE)
        if(!prefs.getBoolean("auto_boot",false) || !prefs.getBoolean("server_enabled",false))return
        try { context.startForegroundService(Intent(context,ServerService::class.java)) }
        catch(_:Exception) { Bridge.state="Автостарт обмежено Android; відкрийте застосунок" }
    }
}
