package ua.ducksolar.b2.server
import android.content.*
import android.content.pm.PackageInstaller
import android.os.Build

object UpdateCoordinator {
    @Suppress("DEPRECATION")
    fun recover(context:Context,force:Boolean=false) {
        val pending=context.getSharedPreferences("ServerUpdate",Context.MODE_PRIVATE)
        if(!pending.getBoolean("resume",false))return
        val info=context.packageManager.getPackageInfo(context.packageName,0)
        val version=if(Build.VERSION.SDK_INT>=28)info.longVersionCode else info.versionCode.toLong()
        val changed=version>=pending.getLong("target",Long.MAX_VALUE)
        val installer=context.getSharedPreferences("UpdateInstaller",Context.MODE_PRIVATE)
        var result=installer.getInt("result",PackageInstaller.STATUS_PENDING_USER_ACTION)
        val session=installer.getInt("session",-1)
        if(session>=0 && context.packageManager.packageInstaller.getSessionInfo(session)==null && !changed)
            result=PackageInstaller.STATUS_FAILURE_ABORTED
        if(!force && !changed && result==PackageInstaller.STATUS_PENDING_USER_ACTION)return
        val prefs=context.getSharedPreferences("MainActivity",Context.MODE_PRIVATE)
        val intent=Intent(context,ServerService::class.java)
            .putExtra("ip",prefs.getString("ip",""))
            .putExtra("pn",prefs.getString("pn",""))
            .putExtra("offline",prefs.getBoolean("offline",true))
            .putExtra("verify_update",changed)
        try { context.startForegroundService(intent) }
        catch(_:Exception) { Bridge.state="Після оновлення відкрийте застосунок і запустіть сервер" }
    }
}
class UpdateResumeReceiver:BroadcastReceiver() {
    override fun onReceive(context:Context,intent:Intent) {
        if(intent.action==Intent.ACTION_MY_PACKAGE_REPLACED || intent.action=="${context.packageName}.UPDATE_FINISHED")
            UpdateCoordinator.recover(context)
    }
}
