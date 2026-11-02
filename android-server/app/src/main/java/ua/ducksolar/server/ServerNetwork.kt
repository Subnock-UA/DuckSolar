package ua.ducksolar.b2.server

import android.net.LinkProperties
import android.net.Network
import org.json.JSONArray
import org.json.JSONObject

/** Callback-owned Wi-Fi state. Default Internet changes do not own logger recovery. */
object ServerNetwork {
    @JvmStatic fun signal(context:android.content.Context):JSONObject {
        val result=JSONObject()
        try {
            val manager=context.applicationContext.getSystemService(android.net.wifi.WifiManager::class.java)
            val info=manager.connectionInfo
            result.put("association",info.supplicantState.toString()).put("rssi_dbm",info.rssi)
                .put("frequency_mhz",info.frequency).put("link_mbps",info.linkSpeed)
            if(info.bssid!=null && info.bssid!="02:00:00:00:00:00")result.put("bssid",info.bssid)
            if(info.ssid!=null && info.ssid!="<unknown ssid>")result.put("ssid",info.ssid)
        } catch(_:SecurityException) { result.put("unavailable",true) }
        return result
    }
    private val networks=mutableMapOf<String,Network>()
    private val links=mutableMapOf<String,LinkProperties>()
    private val blocked=mutableMapOf<String,Boolean>()
    @Synchronized fun update(network:Network, value:LinkProperties) { networks[network.toString()]=network;links[network.toString()]=value }
    @Synchronized fun blocked(network:Network,value:Boolean) { blocked[network.toString()]=value }
    @Synchronized fun remove(network:Network) { networks.remove(network.toString());links.remove(network.toString());blocked.remove(network.toString()) }
    @Synchronized fun clear() { networks.clear();links.clear();blocked.clear() }
    @JvmStatic fun bindSocket(fd:Int,id:String) {
        val network=synchronized(this) { networks[id] } ?: throw java.io.IOException("Wi-Fi network unavailable")
        android.os.ParcelFileDescriptor.fromFd(fd).use { network.bindSocket(it.fileDescriptor) }
    }
    @JvmStatic @Synchronized fun snapshot():String {
        val rows=JSONArray()
        links.forEach { (id,link) ->
            rows.put(JSONObject().put("id",id).put("interface",link.interfaceName ?: "")
                .put("addresses",JSONArray(link.linkAddresses.map { it.toString() }))
                .put("blocked",blocked[id] ?: false))
        }
        return JSONObject().put("wifi",rows).toString()
    }
}
