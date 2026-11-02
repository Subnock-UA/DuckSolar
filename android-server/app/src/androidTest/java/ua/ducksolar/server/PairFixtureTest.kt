package ua.ducksolar.b2.server
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import android.content.Intent
import org.json.JSONObject
import java.io.File
@RunWith(AndroidJUnit4::class)
class PairFixtureTest {
 @Test fun isolatedOfflinePairingFixture() {
  val context=InstrumentationRegistry.getInstrumentation().targetContext
  Bridge.initialize(context)
  context.startForegroundService(Intent(context,ServerService::class.java).putExtra("offline",true).putExtra("pn","Q0000000000000").putExtra("ip","127.0.0.1"))
  val end=System.currentTimeMillis()+30000
  while(!Bridge.status().optBoolean("running") && System.currentTimeMillis()<end)Thread.sleep(100)
  assertTrue(Bridge.status().optBoolean("running"))
  File(context.filesDir,"PAIR_FIXTURE_RESULT.private.json").writeText(JSONObject().put("code",Bridge.pairingCode()).put("serial","Q0000000000000").toString())
 }
}
