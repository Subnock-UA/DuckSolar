package ua.ducksolar.b2.server

import android.content.*
import android.net.*
import android.os.*
import ua.ducksolar.shared.UpdateDiagnostics
import java.util.concurrent.Executors

/** Native events remain visible even while Python is performing a calculation. */
class ServerEnvironment(private val context:Context) {
    private val worker=Executors.newSingleThreadExecutor()
    private val network=context.getSystemService(ConnectivityManager::class.java)
    private val power=context.getSystemService(PowerManager::class.java)
    private val networkPending=java.util.concurrent.atomic.AtomicBoolean(false)
    private val pending=java.util.concurrent.atomic.AtomicBoolean(false)
    @Volatile private var charging=false
    private val revision=java.util.concurrent.atomic.AtomicLong(0)
    private val wifiCallback=object:ConnectivityManager.NetworkCallback() {
        override fun onAvailable(value:Network) { event("wifi.available",value.toString()) }
        override fun onLost(value:Network) {
            ServerNetwork.remove(value);event("wifi.lost",value.toString());refreshNetwork()
        }
        override fun onLinkPropertiesChanged(value:Network,link:LinkProperties) {
            ServerNetwork.update(value,link)
            event("wifi.links","network=$value interface=${link.interfaceName} addresses=${link.linkAddresses}")
            refreshNetwork()
        }
        override fun onBlockedStatusChanged(value:Network,blocked:Boolean) {
            ServerNetwork.blocked(value,blocked)
            event("wifi.uid_blocked","network=$value blocked=$blocked")
        }
    }
    private val callback=object:ConnectivityManager.NetworkCallback() {
        override fun onAvailable(value:Network) { event("network.available",value.toString()) }
        override fun onLost(value:Network) { event("network.lost",value.toString()) }
        override fun onLinkPropertiesChanged(value:Network,link:LinkProperties) {
            event("network.links","network=$value interface=${link.interfaceName} addresses=${link.linkAddresses} routes=${link.routes} dns=${link.dnsServers}")
        }
        override fun onCapabilitiesChanged(value:Network,caps:NetworkCapabilities) {
            event("network.capabilities","network=$value wifi=${caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)} mobile=${caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR)} validated=${caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)}")
        }
    }
    private fun refreshNetwork() {
        revision.incrementAndGet()
        if(com.chaquo.python.Python.isStarted() && networkPending.compareAndSet(false,true))worker.execute {
            var seen=revision.get()
            try {
                do {
                    seen=revision.get()
                    com.chaquo.python.Python.getInstance().getModule("android_bridge").callAttr("network_changed")
                } while(seen!=revision.get())
            }
            catch(e:Exception) { event("network.refresh.failed",e.javaClass.simpleName) }
            finally { networkPending.set(false);if(seen!=revision.get())refreshNetwork() }
        }
    }
    private fun event(code:String,detail:String) { UpdateDiagnostics.record(context,code,detail) }
    private val receiver=object:BroadcastReceiver() {
        override fun onReceive(ctx:Context,intent:Intent) {
            val battery=context.registerReceiver(null,IntentFilter(Intent.ACTION_BATTERY_CHANGED))
            charging=(battery?.getIntExtra(BatteryManager.EXTRA_PLUGGED,0) ?: 0)!=0
            if(intent.action==android.net.wifi.WifiManager.WIFI_STATE_CHANGED_ACTION || intent.action==android.net.wifi.WifiManager.NETWORK_STATE_CHANGED_ACTION) {
                val wifi=appWifi()
                val association=try { wifi.connectionInfo.supplicantState.toString() } catch(_:SecurityException) { "unavailable" }
                event("wifi.state","action=${intent.action} state=${wifi.wifiState} enabled=${wifi.isWifiEnabled} association=$association signal=${ServerNetwork.signal(context)}")
                return
            }
            event("power.changed","action=${intent.action} charging=$charging screen=${power.isInteractive} saver=${power.isPowerSaveMode} idle=${power.isDeviceIdleMode} exempt=${power.isIgnoringBatteryOptimizations(context.packageName)}")
            if(com.chaquo.python.Python.isStarted() && pending.compareAndSet(false,true))worker.execute {
                try { com.chaquo.python.Python.getInstance().getModule("android_bridge").callAttr("power_state",charging) }
                finally { pending.set(false) }
            }
        }
    }
    private fun appWifi()=context.applicationContext.getSystemService(android.net.wifi.WifiManager::class.java)
    fun start() {
        context.registerReceiver(receiver,IntentFilter().apply {
            addAction(android.net.wifi.WifiManager.WIFI_STATE_CHANGED_ACTION);addAction(android.net.wifi.WifiManager.NETWORK_STATE_CHANGED_ACTION)
            addAction(Intent.ACTION_BATTERY_CHANGED);addAction(Intent.ACTION_POWER_CONNECTED);addAction(Intent.ACTION_POWER_DISCONNECTED)
            addAction(Intent.ACTION_SCREEN_ON);addAction(Intent.ACTION_SCREEN_OFF)
            addAction(PowerManager.ACTION_POWER_SAVE_MODE_CHANGED);addAction(PowerManager.ACTION_DEVICE_IDLE_MODE_CHANGED)
        })
        network.registerDefaultNetworkCallback(callback)
        network.registerNetworkCallback(NetworkRequest.Builder().addTransportType(NetworkCapabilities.TRANSPORT_WIFI).build(),wifiCallback)
        network.allNetworks.forEach { value ->
            if(network.getNetworkCapabilities(value)?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)==true) {
                network.getLinkProperties(value)?.let { ServerNetwork.update(value,it) }
            }
        }
    }
    fun stop() {
        try { context.unregisterReceiver(receiver) } catch(_:Exception) { }
        try { network.unregisterNetworkCallback(callback) } catch(_:Exception) { }
        try { network.unregisterNetworkCallback(wifiCallback) } catch(_:Exception) { }
        ServerNetwork.clear()
        worker.shutdownNow()
    }
}
