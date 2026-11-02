package ua.ducksolar.b2.server
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.json.JSONObject
@RunWith(AndroidJUnit4::class)
class HourlyPatchTest {
 @Test fun projectionsAppendAndLegacyJob() {
  assertEquals(30,android.os.Build.VERSION.SDK_INT)
  val context=InstrumentationRegistry.getInstrumentation().targetContext
  if(!Python.isStarted())Python.start(AndroidPlatform(context))
  val result=JSONObject(Python.getInstance().getModule("hourly_patch_checks").callAttr("run",context.cacheDir.absolutePath).toString())
  assertTrue(result.getBoolean("passed"));assertEquals(6,result.getInt("checks"))
 }
}
