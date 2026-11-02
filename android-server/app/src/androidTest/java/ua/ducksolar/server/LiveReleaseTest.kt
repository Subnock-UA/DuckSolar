package ua.ducksolar.b2.server
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.json.JSONObject
@RunWith(AndroidJUnit4::class)
class LiveReleaseTest {
 @Test fun deltaRecoveryAndBroadcast() {
  assertEquals(30,android.os.Build.VERSION.SDK_INT)
  val context=InstrumentationRegistry.getInstrumentation().targetContext
  Bridge.initialize(context)
  val result=JSONObject(com.chaquo.python.Python.getInstance().getModule("live_release_checks").callAttr("run").toString())
  assertTrue(result.getBoolean("passed"));assertEquals(7,result.getInt("tests"))
  assertTrue(ServerNetwork.signal(context).has("association") || ServerNetwork.signal(context).optBoolean("unavailable"))
 }
}
