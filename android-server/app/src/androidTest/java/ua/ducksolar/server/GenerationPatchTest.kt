package ua.ducksolar.b2.server
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.json.JSONObject
@RunWith(AndroidJUnit4::class)
class GenerationPatchTest {
 @Test fun streamingSummaryParityCancellationAndCleanup() {
  assertEquals(30,android.os.Build.VERSION.SDK_INT)
  Bridge.initialize(InstrumentationRegistry.getInstrumentation().targetContext)
  val value=JSONObject(com.chaquo.python.Python.getInstance().getModule("generation_patch_checks").callAttr("run").toString())
  assertTrue(value.getBoolean("passed"));assertEquals(5,value.getInt("tests"))
 }
}
