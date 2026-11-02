package ua.ducksolar.b2.client
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.json.JSONObject
@RunWith(AndroidJUnit4::class)
class IdlePatchTest {
 @Test fun idleContracts() {
  ClientBridge.initialize(InstrumentationRegistry.getInstrumentation().targetContext)
  val result=JSONObject(com.chaquo.python.Python.getInstance().getModule("client_idle_checks").callAttr("run").toString())
  assertTrue(result.optString("output"),result.getBoolean("passed"));assertEquals(6,result.getInt("tests"))
 }
}
