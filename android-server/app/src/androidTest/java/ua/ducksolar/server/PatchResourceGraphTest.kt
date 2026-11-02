package ua.ducksolar.b2.server
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import java.io.File
import org.json.JSONObject
@RunWith(AndroidJUnit4::class)
class PatchResourceGraphTest {
 @Test fun compressedHistoryFourGraphPeriodsAndMemoryReturn() {
  assertEquals(30,android.os.Build.VERSION.SDK_INT)
  val context=InstrumentationRegistry.getInstrumentation().targetContext;Bridge.initialize(context)
  val result=com.chaquo.python.Python.getInstance().getModule("patch_checks").callAttr("run",context.cacheDir.absolutePath).toString()
  val data=JSONObject(result);assertTrue(data.getBoolean("metadata_exact"));assertTrue(data.getBoolean("caches_empty"));assertTrue(data.getLong("released_bytes")>16L*1024*1024)
  File(context.filesDir,"PATCH_RESOURCE_RESULT.json").writeText(result)
 }
}
