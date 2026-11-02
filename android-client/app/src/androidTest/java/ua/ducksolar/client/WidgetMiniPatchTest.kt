package ua.ducksolar.b2.client
import android.graphics.Bitmap
import android.graphics.Canvas
import android.view.View
import android.widget.FrameLayout
import android.widget.TextView
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
@RunWith(AndroidJUnit4::class)
class WidgetMiniPatchTest {
 @Test fun captureAndDisplayWidgetOnly() {
  val ins=InstrumentationRegistry.getInstrumentation();val context=ins.targetContext
  fun m(v:Double,u:String,stale:Boolean=false)=JSONObject().put("value",v).put("unit",u).put("quality","good").put("stale",stale)
  val metrics=JSONObject().put("pv.inputs.aggregate.voltage",m(320.0,"V")).put("pv.total_power",m(1600.0,"W"))
   .put("pv.inputs.aggregate.current",m(0.0,"A",true))
   .put("output.phases.L1.voltage",m(230.0,"V")).put("output.active_power",m(460.0,"W")).put("output.apparent_power",m(460.0,"VA"))
   .put("battery.channels.main.voltage",m(53.2,"V")).put("battery.channels.main.charge_current",m(0.0,"A"))
   .put("battery.channels.main.discharge_current",m(9.1,"A")).put("grid.phases.L1.voltage",m(231.0,"V")).put("grid.phases.L1.current",m(0.0,"A"))
  val state=JSONObject().put("stale",false).put("updated","2026-10-25 18:30:00+02:00").put("data",JSONObject().put("pv_w",1600).put("output_w",460))
   .put("normalized",JSONObject().put("metrics",metrics).put("grid",JSONObject().put("voltage_present",true)))
   .put("battery",JSONObject().put("values",JSONObject().put("soc",68)))
  SolarWidget.capture(context,JSONObject().put("connected",true).put("state",state),true)
  val row=JSONObject(context.getSharedPreferences("solar_widget",0).getString("cache","{}")!!)
  assertEquals(5.0,row.getDouble("pv_a"),0.00001);assertEquals(2.0,row.getDouble("load_a"),0.00001)
  assertEquals(0.0,row.getDouble("charge_a"),0.0);assertEquals(231.0,row.getDouble("grid_v"),0.0)
  assertFalse(WidgetRings.detail(row,"grid_a","А").contains("—"))
  ins.runOnMainSync {
   for((name,width,height) in listOf(Triple("widget-mini",250,180),Triple("widget-a51",360,220),Triple("widget-large-font",250,180))) {
    val renderContext=if(name=="widget-large-font")context.createConfigurationContext(android.content.res.Configuration(context.resources.configuration).apply { fontScale=1.3f }) else context
    val view=SolarWidget.views(renderContext,row).apply(renderContext,FrameLayout(renderContext))
    val d=renderContext.resources.displayMetrics.density;val w=(width*d).toInt();val h=(height*d).toInt()
    view.measure(View.MeasureSpec.makeMeasureSpec(w,View.MeasureSpec.EXACTLY),View.MeasureSpec.makeMeasureSpec(h,View.MeasureSpec.EXACTLY));view.layout(0,0,w,h)
    val rings=view.findViewById<View>(R.id.widget_rings);val refresh=view.findViewById<View>(R.id.widget_refresh)
    val grid=view.findViewById<TextView>(R.id.widget_grid);val rr=android.graphics.Rect(0,0,refresh.width,refresh.height);val ir=android.graphics.Rect(0,0,rings.width,rings.height)
    (view as android.view.ViewGroup).offsetDescendantRectToMyCoords(refresh,rr);view.offsetDescendantRectToMyCoords(rings,ir)
    assertTrue("Refresh below image",rr.top>=ir.bottom)
    assertTrue(refresh.hasOnClickListeners());assertTrue(refresh.height>=39*d)
    assertTrue(rr.bottom<=h);assertTrue(grid.text.contains("231"))
    assertTrue(rings.height>=80*d)
    val bitmap=Bitmap.createBitmap(w,h,Bitmap.Config.ARGB_8888);view.draw(Canvas(bitmap))
    context.openFileOutput("$name.png",0).use { bitmap.compress(Bitmap.CompressFormat.PNG,100,it) }
   }
  }
  metrics.getJSONObject("pv.inputs.aggregate.voltage").put("stale",true)
  metrics.getJSONObject("grid.phases.L1.current").put("age_s",15).put("valid_for_s",10)
  SolarWidget.capture(context,JSONObject().put("connected",true).put("state",state),true)
  val missing=JSONObject(context.getSharedPreferences("solar_widget",0).getString("cache","{}")!!)
  assertTrue(missing.isNull("pv_v"));assertTrue(missing.isNull("pv_a"));assertTrue(missing.isNull("grid_a"))
  assertTrue(WidgetRings.detail(missing,"grid_a","А").contains("—"))
 }
}
