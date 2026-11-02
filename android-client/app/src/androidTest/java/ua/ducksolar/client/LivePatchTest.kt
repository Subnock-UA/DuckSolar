package ua.ducksolar.b2.client
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.json.JSONObject
@RunWith(AndroidJUnit4::class)
class LivePatchTest {
 @Test fun completeLargeEventsPartialTransportAndInvalidJsonAreDistinct() {
  assertEquals(33,android.os.Build.VERSION.SDK_INT)
  ClientBridge.initialize(InstrumentationRegistry.getInstrumentation().targetContext)
  val result=JSONObject(com.chaquo.python.Python.getInstance().getModule("live_patch_checks").callAttr("run").toString())
  assertTrue(result.getBoolean("passed"));assertEquals(4,result.getInt("tests"))
 }
}
