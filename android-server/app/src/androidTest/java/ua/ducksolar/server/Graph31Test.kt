package ua.ducksolar.b2.server
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.json.JSONObject
@RunWith(AndroidJUnit4::class)
class Graph31Test {
 @Test fun indexedDayAndSelectedWindow() {
  assertEquals(30,android.os.Build.VERSION.SDK_INT)
  Bridge.initialize(InstrumentationRegistry.getInstrumentation().targetContext)
  val result=JSONObject(com.chaquo.python.Python.getInstance().getModule("graph31_checks").callAttr("run").toString())
  assertTrue(result.getBoolean("passed"));assertEquals(13,result.getInt("tests"))
  val dst=JSONObject(com.chaquo.python.Python.getInstance().getModule("dst_checks").callAttr("run").toString())
  assertTrue(dst.optString("output"),dst.getBoolean("passed"));assertEquals(6,dst.getInt("tests"))
 }
}
