package ua.ducksolar.b2.client
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.json.JSONObject
@RunWith(AndroidJUnit4::class)
class WeatherNetworkTest {
 @Test fun actualAndroidHttpsForecastAndTimezone() {
  val context=InstrumentationRegistry.getInstrumentation().targetContext
  ClientBridge.initialize(context)
  val value=JSONObject(com.chaquo.python.Python.getInstance().getModule("weather_network_check").callAttr("run",context.cacheDir.absolutePath).toString())
  assertTrue(value.getBoolean("passed"));assertEquals(10,value.getInt("days"));assertEquals("Europe/Kyiv",value.getString("timezone"))
 }
}
