package ua.ducksolar.b2.client
import android.content.*
import java.io.File
import org.json.JSONObject

class NotificationResumeReceiver:BroadcastReceiver() {
 override fun onReceive(context:Context,intent:Intent) {
  if(intent.action !in listOf(Intent.ACTION_BOOT_COMPLETED,Intent.ACTION_MY_PACKAGE_REPLACED))return
  val saved=try { JSONObject(File(context.filesDir,"connection.json").readText()).optString("token").isNotEmpty() } catch(_:Exception) { false }
  if(saved)AlertMonitoring.start(context)
 }
}
