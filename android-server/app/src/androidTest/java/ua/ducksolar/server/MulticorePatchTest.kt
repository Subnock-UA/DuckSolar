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
class MulticorePatchTest {
 @Test fun kernelsAndIntegrationOutsideGil() {
  assertEquals(30,android.os.Build.VERSION.SDK_INT)
  val context=InstrumentationRegistry.getInstrumentation().targetContext
  if(!Python.isStarted())Python.start(AndroidPlatform(context))
  val result=JSONObject(Python.getInstance().getModule("multicore_checks").callAttr("run",context.cacheDir.absolutePath).toString())
  assertTrue(result.getBoolean("passed"));assertEquals(7,result.getInt("checks"))
  assertTrue(result.getJSONObject("cpu").getInt("peak_active_workers")>=2)
 }
}
