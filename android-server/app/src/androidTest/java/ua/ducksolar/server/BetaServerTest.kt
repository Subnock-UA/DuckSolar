package ua.ducksolar.b2.server
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.json.JSONObject
@RunWith(AndroidJUnit4::class)
class BetaServerTest {
 @Test fun betaContracts() {
  val context=InstrumentationRegistry.getInstrumentation().targetContext
  if(!com.chaquo.python.Python.isStarted())com.chaquo.python.Python.start(com.chaquo.python.android.AndroidPlatform(context))
  val result=JSONObject(com.chaquo.python.Python.getInstance().getModule("beta_checks").callAttr("run").toString())
  assertTrue(result.optString("output"),result.getBoolean("passed"));assertEquals(12,result.getInt("tests"))
 }
}
