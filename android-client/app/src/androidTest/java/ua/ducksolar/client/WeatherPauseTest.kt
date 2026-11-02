package ua.ducksolar.b2.client
import android.app.Activity
import android.content.Intent
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
@RunWith(AndroidJUnit4::class)
class WeatherPauseTest {
 @Test fun leavingScreenPausesAndResumeButtonContinues() {
  val inst=InstrumentationRegistry.getInstrumentation();val context=inst.targetContext
  ClientBridge.initialize(context)
  val fixture=com.chaquo.python.Python.getInstance().getModule("weather_pause_fixture")
  fixture.callAttr("install",context.cacheDir.absolutePath)
  var activity:Activity?=null
  fun views(v:View):List<View> = listOf(v)+(if(v is ViewGroup)(0 until v.childCount).flatMap { views(v.getChildAt(it)) } else emptyList())
  fun waitFor(test:()->Boolean) { val end=System.currentTimeMillis()+10000;while(!test() && System.currentTimeMillis()<end)Thread.sleep(100);assertTrue(test()) }
  fun click(title:String) { inst.runOnMainSync { views(activity!!.window.decorView).filterIsInstance<Button>().first { it.text.toString()==title }.performClick() } }
  try {
   activity=inst.startActivitySync(Intent(context,WeatherActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
   waitFor { var ready=false;inst.runOnMainSync { ready=views(activity!!.window.decorView).filterIsInstance<Button>().any { it.text.toString()=="Оновити" && it.isEnabled } };ready }
   click("Оновити");waitFor { ClientBridge.weatherStatus().optString("state")=="running" }
   inst.runOnMainSync { activity!!.finish() }
   waitFor { ClientBridge.weatherStatus().optString("state")=="paused" }
   fixture.callAttr("allow")
   activity=inst.startActivitySync(Intent(context,WeatherActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
   waitFor { var ready=false;inst.runOnMainSync { ready=views(activity!!.window.decorView).filterIsInstance<Button>().any { it.text.toString()=="Продовжити" } };ready }
   click("Продовжити");waitFor { ClientBridge.weatherStatus().optString("state")=="complete" }
   assertEquals(10,ClientBridge.weatherStatus().getJSONObject("result").getJSONArray("days").length())
  } finally { ClientBridge.weatherCancel();Thread.sleep(100);inst.runOnMainSync { activity?.finish() };fixture.callAttr("restore") }
 }
}
