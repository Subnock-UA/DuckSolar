package ua.ducksolar.b2.server
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.json.JSONObject
@RunWith(AndroidJUnit4::class)
class Connectivity30Test {
 @Test fun pollingAndPassiveTelemetryOnAndroid11() {
  assertEquals(30,android.os.Build.VERSION.SDK_INT)
  Bridge.initialize(InstrumentationRegistry.getInstrumentation().targetContext)
  val result=JSONObject(com.chaquo.python.Python.getInstance().getModule("connectivity30_checks").callAttr("run").toString())
  assertTrue(result.getBoolean("passed"));assertEquals(10,result.getInt("tests"))
 }
}
