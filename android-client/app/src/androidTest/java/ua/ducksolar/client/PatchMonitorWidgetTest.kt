package ua.ducksolar.b2.client

import android.graphics.Bitmap
import android.graphics.Canvas
import android.view.View
import android.widget.FrameLayout
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class PatchMonitorWidgetTest {
 private fun metric(v:Double,u:String,stale:Boolean=false)=JSONObject().put("value",v).put("unit",u).put("quality","good").put("stale",stale)
 @Test fun allMonitoringValues() {
  val context=InstrumentationRegistry.getInstrumentation().context
  val metrics=JSONObject(context.assets.open("monitoring_fixture.json").bufferedReader().use { it.readText() })
  var count=0
  for(key in metrics.keys()) {
   val m=metrics.getJSONObject(key)
   assertFalse("Fresh $key",MetricText.value(m,false).startsWith("—"))
   assertTrue("Stale $key",MetricText.value(JSONObject(m.toString()).put("stale",true),false).startsWith("—"))
   assertTrue("Missing $key",MetricText.value(JSONObject(m.toString()).put("value",JSONObject.NULL),false).startsWith("—"))
   count++
  }
  assertTrue(count>=26)
  assertFalse(MetricText.value(metric(0.0,"A"),false).startsWith("—"))
 }
 @Test fun freshFallbacks() {
  val m=JSONObject().put("pv.inputs.aggregate.current",metric(1.0,"A",true)).put("pv.inputs.aggregate.voltage",metric(349.0,"V")).put("pv.total_power",metric(2749.92,"W"))
  val pv=HomeMetrics.pvCurrent(m)!!
  assertEquals(7.879426934,pv.getDouble("value"),0.000001)
  assertFalse(MetricText.value(pv,false).startsWith("—"))
  m.getJSONObject("pv.total_power").put("stale",true)
  assertTrue(MetricText.value(HomeMetrics.pvCurrent(m),false).startsWith("—"))
  m.put("output.phases.L1.current",metric(1.0,"A",true)).put("output.phases.L1.voltage",metric(230.0,"V")).put("output.apparent_power",metric(460.0,"VA")).put("output.active_power",metric(400.0,"W"))
  assertEquals(2.0,HomeMetrics.outputCurrent(m)!!.getDouble("value"),0.00001)
  m.put("battery.charge_power",metric(1.0,"W",true)).put("battery.channels.main.voltage",metric(54.0,"V")).put("battery.channels.main.charge_current",metric(2.0,"A"))
  assertEquals(108.0,HomeMetrics.power(m,"charge")!!.getDouble("value"),0.00001)
 }
 @Test fun widgetSizeAndUnknownBattery() {
  val instrumentation=InstrumentationRegistry.getInstrumentation();val context=instrumentation.targetContext
  instrumentation.runOnMainSync {
   val row=JSONObject().put("valid",true).put("time",System.currentTimeMillis()).put("updated","2026-10-25 16:30:00+02:00").put("pv",2696.0).put("load",545.0).put("soc",65.0).put("pv_max",4700.0).put("load_max",6200.0).put("grid",true)
   for((name,width,height) in listOf(Triple("widget-min",250,100),Triple("widget-large",320,140),Triple("widget-no-soc",250,100))) {
    if(name=="widget-no-soc")row.put("soc",JSONObject.NULL)
    val view=SolarWidget.views(context,row).apply(context,FrameLayout(context))
    val d=context.resources.displayMetrics.density;val w=(width*d).toInt();val h=(height*d).toInt()
    view.measure(View.MeasureSpec.makeMeasureSpec(w,View.MeasureSpec.EXACTLY),View.MeasureSpec.makeMeasureSpec(h,View.MeasureSpec.EXACTLY));view.layout(0,0,w,h)
    assertTrue(view.findViewById<View>(R.id.widget_rings).height>0)
    assertTrue(view.findViewById<View>(R.id.widget_stamp).bottom<=view.height)
    val bitmap=Bitmap.createBitmap(w,h,Bitmap.Config.ARGB_8888);view.draw(Canvas(bitmap))
    context.openFileOutput("$name.png",0).use { bitmap.compress(Bitmap.CompressFormat.PNG,100,it) }
   }
  }
 }
}
