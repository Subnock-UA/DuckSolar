package ua.ducksolar.b2.client
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
@RunWith(AndroidJUnit4::class)
class WeatherTlsIntegrationTest {
 @Test fun actualTlsHistoryCheckpointPauseResumeAndCalibration() {
  val inst=InstrumentationRegistry.getInstrumentation();val context=inst.targetContext
  val args=InstrumentationRegistry.getArguments();ClientBridge.initialize(context)
  val fixture=com.chaquo.python.Python.getInstance().getModule("weather_tls_fixture")
  fun waitFor(test:()->Boolean) { val end=System.currentTimeMillis()+90000;while(!test() && System.currentTimeMillis()<end)Thread.sleep(150);assertTrue(ClientBridge.weatherStatus().toString(),test()) }
  try {
   fixture.callAttr("install",context.filesDir.absolutePath,context.cacheDir.absolutePath,args.getString("weather_url"),args.getString("weather_pin"),args.getString("weather_token"))
   ClientBridge.weatherStart(true)
   waitFor { ClientBridge.weatherStatus().optInt("done")==40 }
   ClientBridge.weatherCancel(true);waitFor { ClientBridge.weatherStatus().optString("state")=="paused" }
   fixture.callAttr("allow");ClientBridge.weatherResume()
   waitFor { ClientBridge.weatherStatus().optString("state")=="complete" || ClientBridge.weatherStatus().optString("state")=="error" }
   val result=ClientBridge.weatherStatus()
   assertEquals(result.toString(),"complete",result.optString("state"))
   assertEquals(41,result.getJSONObject("result").getJSONObject("calibration").getInt("sample_count"))
   assertEquals(10,result.getJSONObject("result").getJSONArray("days").length())
  } finally {
   ClientBridge.weatherCancel();Thread.sleep(200);fixture.callAttr("restore")
  }
 }
}
