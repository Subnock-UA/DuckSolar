package ua.ducksolar.b2.client

import android.content.Context
import android.net.ConnectivityManager
import android.os.PowerManager

/** Bounded, renewed only while user-enabled direct alerts need screen-off delivery. */
class AlertWakeLease(private val context:Context) {
    private val power=context.getSystemService(PowerManager::class.java)
    private val lock=power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"DuckSolar:DirectAlerts").apply { setReferenceCounted(false) }
    companion object {
        fun needed(enabled:Boolean,permitted:Boolean,channel:Boolean,reliable:Boolean,screenOn:Boolean,network:Boolean)=
            enabled && permitted && channel && reliable && !screenOn && network
    }
    @Synchronized fun update() {
        val required=needed(AlertMonitoring.enabled(context),AlertMonitoring.permitted(context),AlertMonitoring.channelEnabled(context),
            AlertMonitoring.reliableBackground(context),power.isInteractive,context.getSystemService(ConnectivityManager::class.java).activeNetwork!=null)
        if(required)lock.acquire(120000L) else release()
    }
    @Synchronized fun held()=lock.isHeld
    @Synchronized fun release() { if(lock.isHeld)lock.release() }
}
