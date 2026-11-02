package ua.ducksolar.b2.client
import android.content.Intent
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class FlowAnimationTest {
 @Test fun animationStopsWhenStaleHiddenOrBackground() {
  val instrumentation=InstrumentationRegistry.getInstrumentation()
  val a=instrumentation.startActivitySync(Intent(instrumentation.targetContext,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)) as MainActivity
  fun buttons(v:View):List<Button> = if(v is Button)listOf(v) else if(v is ViewGroup)(0 until v.childCount).flatMap { buttons(v.getChildAt(it)) } else emptyList()
  Thread.sleep(1500)
  instrumentation.runOnMainSync {
   MainActivity::class.java.getDeclaredField("visible").apply { isAccessible=true }.setBoolean(a,false)
   buttons(a.window.decorView).first { it.text.toString()=="Головна" }.performClick()
   val flow=MainActivity::class.java.getDeclaredField("flow").apply { isAccessible=true }.get(a) as FlowDiagram
   val running=FlowDiagram::class.java.getDeclaredField("animationRunning").apply { isAccessible=true }
   val metric=JSONObject().put("value",500).put("unit","W").put("quality","good")
   val metrics=JSONObject().put("pv.total_power",metric)
   flow.update(metrics,false,"Fixture");flow.setActive(true);assertTrue(running.getBoolean(flow))
   flow.update(metrics,true,"Fixture");assertFalse(running.getBoolean(flow))
   flow.update(metrics,false,"Fixture");assertTrue(running.getBoolean(flow))
   flow.setActive(false);assertFalse(running.getBoolean(flow))
   flow.setActive(true);buttons(a.window.decorView).first { it.text.toString()=="Моніторинг" }.performClick();assertFalse(running.getBoolean(flow))
   a.finish()
  }
 }
 @Test fun stableLiveMetricsBeforeNominals() {
  fun metric(id:String,unit:String="")=JSONObject().put("canonical_id",id).put("unit",unit)
  assertTrue(MonitorOrder.rank(metric("grid.phases.L1.voltage","V"))<MonitorOrder.rank(metric("device.rated_voltage","V")))
  assertTrue(MonitorOrder.rank(metric("output.active_power","W"))<MonitorOrder.rank(metric("device.firmware_version")))
  assertTrue(MonitorOrder.rank(metric("battery.channels.main.soc","%"))<MonitorOrder.rank(metric("device.serial")))
 }
}
