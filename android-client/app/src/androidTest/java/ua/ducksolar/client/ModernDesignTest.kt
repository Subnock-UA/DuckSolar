package ua.ducksolar.b2.client
import android.app.Activity
import android.content.Intent
import android.graphics.*
import android.graphics.drawable.AdaptiveIconDrawable
import android.graphics.drawable.RippleDrawable
import android.view.View
import android.view.ViewGroup
import android.widget.*
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.json.JSONObject
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import java.io.File

@RunWith(AndroidJUnit4::class)
class ModernDesignTest {
 @Test fun pathsStayOutsideDataCardsAtLargeFontSizes() {
  for(scale in listOf(1f,1.3f,1.6f)) {
   val layout=FlowLayout.create(scale)
   for(path in layout.routes) {
    val measure=PathMeasure(path,false);val point=FloatArray(2)
    for(i in 1 until 1000) {
     measure.getPosTan(measure.length*i/1000,point,null)
     assertFalse("$scale: path inside card at ${point.toList()}",layout.cards.values.any { it.contains(point[0],point[1]) })
    }
   }
  }
 }
 @Test fun launcherHasCorrectNameAndOpaqueFullBleedBackground() {
  val context=InstrumentationRegistry.getInstrumentation().targetContext
  assertEquals("Duck Solar",context.packageManager.getApplicationLabel(context.applicationInfo).toString())
  val icon=context.packageManager.getApplicationIcon(context.packageName)
  assertTrue(icon is AdaptiveIconDrawable)
  val bitmap=Bitmap.createBitmap(108,108,Bitmap.Config.ARGB_8888)
  val background=(icon as AdaptiveIconDrawable).background;background.bounds=Rect(0,0,108,108);background.draw(Canvas(bitmap))
  for(x in listOf(0,54,107))for(y in listOf(0,54,107)) { val color=bitmap.getPixel(x,y);assertEquals(255,Color.alpha(color));assertNotEquals(Color.WHITE,color) }
  bitmap.recycle()
  val preview=Bitmap.createBitmap(192,192,Bitmap.Config.ARGB_8888);icon.bounds=Rect(0,0,192,192);icon.draw(Canvas(preview))
  File(context.cacheDir,"modern-icon.png").outputStream().use { preview.compress(Bitmap.CompressFormat.PNG,100,it) };preview.recycle()
 }
 @Test fun dashboardCardsCurrentsMenusAndControlsAreStyled() {
  val inst=InstrumentationRegistry.getInstrumentation();val context=inst.targetContext
  assertEquals(33,android.os.Build.VERSION.SDK_INT)
  ClientBridge.initialize(context)
  fun views(v:View):List<View> = listOf(v)+(if(v is ViewGroup)(0 until v.childCount).flatMap { views(v.getChildAt(it)) } else emptyList())
  fun shot(a:Activity,name:String) { inst.runOnMainSync { val v=a.window.decorView;val b=Bitmap.createBitmap(v.width,v.height,Bitmap.Config.ARGB_8888);v.draw(Canvas(b));File(context.cacheDir,name).outputStream().use { b.compress(Bitmap.CompressFormat.PNG,100,it) };b.recycle() } }
  val activity=inst.startActivitySync(Intent(context,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)) as MainActivity
  try {
   Thread.sleep(700)
   val recorded=JSONObject(inst.context.assets.open("dashboard-synthetic-example.json").bufferedReader().readText())
   val metrics=recorded.getJSONObject("state").getJSONObject("normalized").getJSONObject("metrics")
   fun metric(key:String,value:Double,unit:String) { metrics.put(key,JSONObject().put("value",value).put("unit",unit).put("quality","good")) }
   metric("battery.channels.main.soc",76.0,"%");metric("grid.import_power",0.0,"W");metric("grid.export_power",400.0,"W");metric("output.active_power",2160.0,"W");metric("output.apparent_power",2300.0,"VA");metric("output.phases.L1.current",10.0,"A");metric("battery.charge_power",639.6,"W");metric("battery.discharge_power",0.0,"W");metric("pv.total_power",3200.0,"W");metric("pv.inputs.aggregate.voltage",350.0,"V");metric("pv.inputs.aggregate.current",9.1,"A")
   metric("grid.phases.L1.current",1.8,"A");metric("output.phases.L1.current",10.0,"A")
   metric("battery.channels.main.charge_current",12.0,"A");metric("battery.channels.main.discharge_current",0.0,"A")
   recorded.getJSONObject("state").getJSONObject("descriptor").put("name","Приклад · Daxtromn")
   inst.runOnMainSync {
    MainActivity::class.java.getDeclaredField("visible").apply { isAccessible=true }.setBoolean(activity,false)
    MainActivity::class.java.getDeclaredMethod("render",JSONObject::class.java).apply { isAccessible=true }.invoke(activity,recorded)
   }
   Thread.sleep(500)
   inst.runOnMainSync {
    val all=views(activity.window.decorView)
    assertEquals(5,all.filterIsInstance<MetricCard>().count { it.isShown })
    val flow=all.filterIsInstance<FlowDiagram>().single()
    assertTrue(flow.contentDescription.toString().contains("PV струм: 9"))
    assertTrue(flow.contentDescription.toString().contains("Струм навантаження: 10"))
    for(title in listOf("Головна","Моніторинг","Графіки","Додатково")) {
     val button=all.filterIsInstance<Button>().first { it.text.toString()==title }
     assertNotNull(button.compoundDrawables[1]);assertTrue(button.background is RippleDrawable)
    }
   }
   shot(activity,"modern-home.png")
   inst.runOnMainSync { val scroll=views(activity.window.decorView).filterIsInstance<ScrollView>().first { it.isShown };scroll.scrollTo(0,(350*context.resources.displayMetrics.density).toInt()) }
   shot(activity,"modern-home-details.png")
   inst.runOnMainSync { views(activity.window.decorView).filterIsInstance<Button>().first { it.text.toString()=="Додатково" }.performClick() }
   Thread.sleep(250);shot(activity,"modern-more.png")
   inst.runOnMainSync {
    val menu=views(activity.window.decorView).filterIsInstance<Button>().first { it.text.toString()=="Місячний баланс" }
    assertNotNull(menu.compoundDrawables[0]);assertNotNull(menu.compoundDrawables[2])
   }
  } finally { inst.runOnMainSync { activity.finish() } }
  val settings=inst.startActivitySync(Intent(context,NotificationSettingsActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
  try {
   Thread.sleep(400)
   inst.runOnMainSync { val switches=views(settings.window.decorView).filterIsInstance<Switch>();assertEquals(12,switches.size);switches.forEachIndexed { i,s->s.isChecked=i%2==0;assertNotNull(s.trackDrawable) } }
   shot(settings,"modern-notifications.png")
  } finally { inst.runOnMainSync { settings.finish() } }
 }
}
