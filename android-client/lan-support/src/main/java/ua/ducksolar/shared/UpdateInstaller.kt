package ua.ducksolar.shared

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.os.Build
import java.io.File

object UpdateInstaller {
    @Volatile var status=""
    @Volatile var foreground=false
    @Volatile var pendingConfirmation:Intent?=null
    @Suppress("DEPRECATION")
    fun requireNewer(context:Context,update:UpdateInfo) {
        val info=context.packageManager.getPackageInfo(context.packageName,0)
        val current=if(Build.VERSION.SDK_INT>=28)info.longVersionCode else info.versionCode.toLong()
        require(update.packageName==context.packageName && update.versionCode>current) { "Встановлена ця або новіша версія" }
    }
    fun permissionReady(context:Context):Boolean {
        if(!context.packageManager.canRequestPackageInstalls()) {
            status="Дозвольте встановлення оновлень із Duck Solar у налаштуваннях Android"
            context.startActivity(Intent(android.provider.Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                android.net.Uri.parse("package:${context.packageName}")).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            return false
        }
        return true
    }
    fun install(context:Context,file:File,update:UpdateInfo):Int {
        UpdateDiagnostics.record(context,"install.begin",update.version)
        requireNewer(context,update)
        require(LanSupportClient.sha256(file)==update.sha256 && file.length()==update.bytes) { "APK змінився" }
        if(Build.VERSION.SDK_INT>=26 && !context.packageManager.canRequestPackageInstalls()) {
            status="Дозвольте встановлення оновлень із Duck Solar у налаштуваннях Android"
            context.startActivity(Intent(android.provider.Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                android.net.Uri.parse("package:${context.packageName}")).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            return -1
        }
        val installer=context.packageManager.packageInstaller
        val params=PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL).apply {
            setAppPackageName(context.packageName);setSize(file.length())
            if(Build.VERSION.SDK_INT>=31)setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_REQUIRED)
        }
        val id=installer.createSession(params)
        context.getSharedPreferences("UpdateInstaller",Context.MODE_PRIVATE).edit()
            .putInt("session",id).putInt("result",PackageInstaller.STATUS_PENDING_USER_ACTION).commit()
        try {
            installer.openSession(id).use { session ->
                session.openWrite("base.apk",0,file.length()).use { out ->file.inputStream().use { it.copyTo(out,65536) };session.fsync(out) }
                val callback=Intent(context,InstallResultReceiver::class.java).setAction("${context.packageName}.INSTALL_RESULT")
                val flags=PendingIntent.FLAG_UPDATE_CURRENT or if(Build.VERSION.SDK_INT>=31)PendingIntent.FLAG_MUTABLE else 0
                val result=PendingIntent.getBroadcast(context,id,callback,flags)
                status="Очікування підтвердження Android"
                session.commit(result.intentSender)
            }
            return id
        } catch(error:Exception) { UpdateDiagnostics.record(context,"install.error",error.message ?: error.javaClass.simpleName);installer.abandonSession(id);throw error }
    }
}

class InstallResultReceiver:BroadcastReceiver() {
    @Suppress("DEPRECATION")
    override fun onReceive(context:Context,intent:Intent) {
        val result=intent.getIntExtra(PackageInstaller.EXTRA_STATUS,PackageInstaller.STATUS_FAILURE)
        UpdateDiagnostics.record(context,"install.result","status=$result "+intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE).orEmpty())
        context.getSharedPreferences("UpdateInstaller",Context.MODE_PRIVATE).edit().putInt("result",result).commit()
        when(result) {
            PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                val confirmation=intent.getParcelableExtra<Intent>(Intent.EXTRA_INTENT)
                UpdateInstaller.pendingConfirmation=confirmation
                UpdateInstaller.status="Підтвердьте встановлення оновлення в Android"
                if(UpdateInstaller.foreground && confirmation!=null)context.startActivity(confirmation.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            }
            PackageInstaller.STATUS_SUCCESS -> { UpdateInstaller.status="Оновлення встановлено";UpdateInstaller.pendingConfirmation=null }
            else -> { UpdateInstaller.status="Оновлення не встановлено; поточна версія збережена";UpdateInstaller.pendingConfirmation=null }
        }
        if(result!=PackageInstaller.STATUS_PENDING_USER_ACTION)context.sendBroadcast(Intent("${context.packageName}.UPDATE_FINISHED").setPackage(context.packageName))
    }
}
