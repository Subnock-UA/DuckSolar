package ua.ducksolar.b2.client

import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.PathMeasure
import android.graphics.Rect
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.ScrollView
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

@RunWith(AndroidJUnit4::class)
class A51HomeTest {
 @Test fun routesStayLongAndOutsideCards() {
  for(scale in listOf(1f,1.3f,1.6f)) {
   val layout=FlowLayout.create(scale)
   for(path in layout.routes) {
    val measure=PathMeasure(path,false);assertTrue(measure.length>=90f)
    val point=FloatArray(2)
    for(i in 1 until 1000) {
     measure.getPosTan(measure.length*i/1000,point,null)
     assertFalse("Route hidden by data card",layout.cards.values.any { it.contains(point[0],point[1]) })
    }
   }
  }
 }
 @Test fun completeDashboardFitsA51AndShowsBothDirections() {
  val inst=InstrumentationRegistry.getInstrumentation();val context=inst.targetContext
  assertEquals(33,android.os.Build.VERSION.SDK_INT)
  ClientBridge.initialize(context)
  val a=inst.startActivitySync(Intent(context,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)) as MainActivity
  fun views(v:View):List<View> = listOf(v)+(if(v is ViewGroup)(0 until v.childCount).flatMap { views(v.getChildAt(it)) } else emptyList())
  val envelope=JSONObject(inst.context.assets.open("dashboard-synthetic-example.json").bufferedReader().readText())
  val metrics=JSONObject()
  fun metric(key:String,value:Double,unit:String) { metrics.put(key,JSONObject().put("value",value).put("unit",unit).put("quality","good").put("source","fixture")) }
  metric("pv.total_power",2480.0,"W");metric("pv.inputs.aggregate.voltage",325.0,"V");metric("pv.inputs.aggregate.current",7.63,"A")
  metric("grid.import_power",0.0,"W");metric("grid.export_power",0.0,"W");metric("grid.phases.L1.voltage",230.0,"V");metric("grid.phases.L1.current",0.0,"A");metric("grid.phases.L1.frequency",50.0,"Hz")
  metric("output.active_power",820.0,"W");metric("output.power_factor",820.0/910,"");metric("output.apparent_power",910.0,"VA");metric("output.phases.L1.voltage",230.0,"V");metric("output.phases.L1.current",3.96,"A");metric("output.phases.L1.frequency",50.0,"Hz");metric("output.load_percent",13.0,"%")
  metric("battery.channels.main.soc",88.0,"%");metric("battery.channels.main.voltage",53.2,"V");metric("battery.channels.main.charge_current",31.2,"A");metric("battery.channels.main.discharge_current",0.0,"A")
  metric("battery.charge_power",1660.0,"W");metric("battery.discharge_power",0.0,"W");metric("battery.channels.main.remaining_energy",12.6,"кВт·год")
  metric("temperature.inverter",38.0,"°C");metric("dc.bus_voltage",390.0,"V");metric("battery.scc_voltage",53.2,"V")
  envelope.put("connected",true).put("connection_message","Інвертор онлайн")
  envelope.getJSONObject("state").put("stale",false).put("mode_stale",false).put("mode_code","B").put("normalized",JSONObject().put("metrics",metrics)).getJSONObject("descriptor").put("name","Custom installation").put("model","VMII-NXPW5KW").put("profile_confirmed",true).put("profile_id","daxtromn.vmii-nxpw5kw.00074.11")
  try {
   Thread.sleep(1000)
   inst.runOnMainSync {
    MainActivity::class.java.getDeclaredField("visible").apply { isAccessible=true }.setBoolean(a,false)
    views(a.window.decorView).filterIsInstance<Button>().first { it.text.toString()=="Головна" }.performClick()
    MainActivity::class.java.getDeclaredMethod("render",JSONObject::class.java).apply { isAccessible=true }.invoke(a,envelope)
   }
   inst.waitForIdleSync();Thread.sleep(200)
   inst.runOnMainSync {
    val flow=views(a.window.decorView).filterIsInstance<FlowDiagram>().single()
    val scroll=views(a.window.decorView).filterIsInstance<ScrollView>().single { it.isShown }
    assertFalse("Home requires scrolling at default A51 scale",scroll.canScrollVertically(1))
    val visible=Rect();assertTrue(flow.getGlobalVisibleRect(visible));assertEquals(flow.height,visible.height())
    assertEquals(0,views(a.window.decorView).filterIsInstance<MetricCard>().count { it.isShown })
    assertTrue(flow.contentDescription.toString().contains("88"))
    val bitmap=Bitmap.createBitmap(flow.width,flow.height,Bitmap.Config.ARGB_8888);flow.draw(Canvas(bitmap))
    File(context.cacheDir,"a51-flow.png").outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG,100,it) };bitmap.recycle()
    // Exercise exporting/discharging and stale rendering without network access.
    metric("grid.export_power",400.0,"W");metric("battery.channels.main.charge_current",0.0,"A");metric("battery.channels.main.discharge_current",10.0,"A")
    flow.update(metrics,false,"DAXTROMN AGH 6.2 PRO");flow.update(metrics,true,"DAXTROMN AGH 6.2 PRO")
    metric("grid.export_power",0.0,"W");metric("battery.channels.main.charge_current",31.2,"A");metric("battery.channels.main.discharge_current",0.0,"A")
    metric("grid.import_power",410.0,"W")
    flow.update(metrics,false,"DAXTROMN AGH 6.2 PRO",JSONObject().put("mode_code","B").put("mode_stale",false))
   }
   inst.uiAutomation.takeScreenshot().also { bitmap->File(context.cacheDir,"a51-home.png").outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG,100,it) };bitmap.recycle() }
  } finally { inst.runOnMainSync { a.finish() } }
 }
}
