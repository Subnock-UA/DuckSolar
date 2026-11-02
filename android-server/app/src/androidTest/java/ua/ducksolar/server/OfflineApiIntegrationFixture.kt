package ua.ducksolar.b2.server
import android.content.Intent
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

@RunWith(AndroidJUnit4::class)
class OfflineApiIntegrationFixture {
 @Test fun temporaryOfflineApi() {
  val instrumentation=InstrumentationRegistry.getInstrumentation()
  val context=instrumentation.targetContext
  Bridge.initialize(context)
  val serial="ANDROID-OFFLINE-TEST"
  instrumentation.startActivitySync(Intent(context,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
  context.startForegroundService(Intent(context,ServerService::class.java).putExtra("offline",true).putExtra("pn",serial))
  val deadline=System.currentTimeMillis()+20000
  while(!Bridge.status().getBoolean("running") && System.currentTimeMillis()<deadline)Thread.sleep(100)
  assertTrue(Bridge.state,Bridge.status().getBoolean("running"))
  val ready=File(context.cacheDir,"OFFLINE_API_READY.json")
  ready.writeText(JSONObject().put("pair_code",Bridge.pairingCode()).put("serial",serial).put("fingerprint",Bridge.status().getString("fingerprint")).toString())
  try {
   val stop=File(context.cacheDir,"OFFLINE_API_DONE")
   stop.delete()
   val end=System.currentTimeMillis()+90000
   while(!stop.exists() && System.currentTimeMillis()<end)Thread.sleep(200)
  } finally {
   ready.delete();context.startService(Intent(context,ServerService::class.java).setAction("STOP"))
  }
 }
}
