package ua.ducksolar.b2.client
import android.content.Context
import android.net.*
class NetworkWatch(context:Context,private val changed:()->Unit) {
 private val manager=context.applicationContext.getSystemService(ConnectivityManager::class.java)
 private var registered=false
 private var lastLinks=""
 private val callback=object:ConnectivityManager.NetworkCallback() {
  override fun onAvailable(network:Network) { android.util.Log.i("DuckSolarClient","Default network available");changed() }
  override fun onLinkPropertiesChanged(network:Network,properties:LinkProperties) {
   val key=network.toString()+properties.linkAddresses.joinToString(",")
   if(key!=lastLinks) { lastLinks=key;changed() }
  }
  override fun onLost(network:Network) { android.util.Log.i("DuckSolarClient","Default network lost");changed() }
 }
 fun start() { if(!registered) { manager.registerDefaultNetworkCallback(callback);registered=true } }
 fun stop() { if(registered) { manager.unregisterNetworkCallback(callback);registered=false } }
}
