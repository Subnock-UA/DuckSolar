package ua.ducksolar.b2.client
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.json.JSONObject
@RunWith(AndroidJUnit4::class)
class WeatherRecoveryTest {
 @Test fun durableBatchesPauseResumeCancellationAndRestart() {
  assertEquals(33,android.os.Build.VERSION.SDK_INT)
  ClientBridge.initialize(InstrumentationRegistry.getInstrumentation().targetContext)
  val value=JSONObject(com.chaquo.python.Python.getInstance().getModule("weather_recovery_checks").callAttr("run").toString())
  assertTrue(value.getBoolean("passed"));assertEquals(6,value.getInt("tests"))
 }
}

