package ua.ducksolar.b2.server
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.json.JSONObject
@RunWith(AndroidJUnit4::class)
class IdlePatchTest {
 @Test fun idleContracts() {
  Bridge.initialize(InstrumentationRegistry.getInstrumentation().targetContext)
  val result=JSONObject(com.chaquo.python.Python.getInstance().getModule("server_idle_checks").callAttr("run").toString())
  assertTrue(result.optString("output"),result.getBoolean("passed"));assertEquals(3,result.getInt("tests"))
 }
}
