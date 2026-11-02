package ua.ducksolar.b2.server

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

@RunWith(AndroidJUnit4::class)
class ForecastArtworkPatchTest {
 @Test fun observedFactsSurviveRealHistoryAndAndroidKernel() {
  val context=InstrumentationRegistry.getInstrumentation().targetContext
  if(!Python.isStarted())Python.start(AndroidPlatform(context))
  val output=Python.getInstance().getModule("forecast_artwork_patch_checks").callAttr("run").toString()
  File(context.cacheDir,"forecast-artwork-checks.json").writeText(output)
  val result=JSONObject(output);assertTrue(output,result.getBoolean("passed"));assertEquals(14,result.getInt("tests"))
  assertTrue(result.getJSONObject("cpu").getString("engine").contains("android.art"))
 }
}
