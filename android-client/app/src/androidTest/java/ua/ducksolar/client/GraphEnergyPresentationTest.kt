package ua.ducksolar.b2.client
import android.app.Activity
import android.content.Intent
import android.view.View
import android.view.ViewGroup
import android.widget.*
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import java.io.File
import android.graphics.Bitmap
import android.graphics.Canvas
@RunWith(AndroidJUnit4::class)
class GraphEnergyPresentationTest {
 @Test fun instantaneousPvAndConsumptionAlsoShowPeriodSummary() {
  val inst=InstrumentationRegistry.getInstrumentation();val context=inst.targetContext
  ClientBridge.initialize(context)
  val fixture=com.chaquo.python.Python.getInstance().getModule("navigation_fixture");fixture.callAttr("install")
  var activity:Activity?=null
  fun views(v:View):List<View> = listOf(v)+(if(v is ViewGroup)(0 until v.childCount).flatMap { views(v.getChildAt(it)) } else emptyList())
  try {
   context.getSharedPreferences("Graphs",Activity.MODE_PRIVATE).edit().putInt("period",0).putInt("mode",0).putInt("group",0).putBoolean("automatic",false).commit()
   activity=inst.startActivitySync(Intent(context,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
   Thread.sleep(500)
   inst.runOnMainSync { views(activity!!.window.decorView).filterIsInstance<Button>().first { it.text=="Графіки" && it.isShown }.performClick() }
   Thread.sleep(300)
   inst.runOnMainSync {
    assertTrue(views(activity!!.window.decorView).filterIsInstance<Spinner>().any { it.isShown && it.selectedItem=="Зміна показників" })
    views(activity!!.window.decorView).filterIsInstance<Button>().first { it.text=="Побудувати" && it.isShown }.performClick()
   }
   val deadline=System.currentTimeMillis()+8000
   var shown=false
   while(!shown && System.currentTimeMillis()<deadline) {
    inst.runOnMainSync { shown=views(activity!!.window.decorView).filterIsInstance<GraphEnergySummary>().any { it.isShown && it.text.toString().contains("Сальдо") } }
    if(!shown)Thread.sleep(80)
   }
   assertTrue("Power PV/consumption summary is missing",shown)
   assertEquals("power",ClientBridge.graphStatus().getJSONObject("result").getString("mode"))
  } finally { inst.runOnMainSync { activity?.finish() };fixture.callAttr("restore") }
 }
 @Test fun unknownValuesAreNotZero() {
  val inst=InstrumentationRegistry.getInstrumentation()
  inst.runOnMainSync {
   val result=org.json.JSONObject("""{"energy_summary":{"generation":{"kwh":0,"partial":true},"consumption":{"kwh":null},"export":{"kwh":null},"import":{"kwh":null},"balance":{"kwh":null}}}""")
   val text=GraphEnergySummary(inst.targetContext,result).text.toString()
   assertTrue(text,text.contains("Генерація: 0,00"));assertTrue(text,text.contains("Споживання: —"));assertTrue(text,text.contains("Сальдо (експорт − імпорт): —"))
  }
 }
 @Test fun monthlyEnergyShowsServerTotalsAndModeChoice() {
  assertEquals(33,android.os.Build.VERSION.SDK_INT)
  val inst=InstrumentationRegistry.getInstrumentation();val context=inst.targetContext
  ClientBridge.initialize(context)
  val fixture=com.chaquo.python.Python.getInstance().getModule("navigation_fixture");fixture.callAttr("install")
  var activity:Activity?=null
  var fullscreen:Activity?=null
  fun views(v:View):List<View> = listOf(v)+(if(v is ViewGroup)(0 until v.childCount).flatMap { views(v.getChildAt(it)) } else emptyList())
  try {
   context.getSharedPreferences("Graphs",Activity.MODE_PRIVATE).edit().putInt("period",1).putInt("mode",1).putInt("energy_group",0).putInt("group",0).putBoolean("automatic",false).commit()
   activity=inst.startActivitySync(Intent(context,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
   Thread.sleep(700)
   inst.runOnMainSync { views(activity!!.window.decorView).filterIsInstance<Button>().first { it.text=="Графіки" && it.isShown }.performClick() }
   Thread.sleep(400)
   inst.runOnMainSync {
    val all=views(activity!!.window.decorView)
    assertTrue(all.filterIsInstance<Spinner>().any { it.isShown && it.selectedItem=="Енергія за період" })
    all.filterIsInstance<Button>().first { it.text=="Побудувати" && it.isShown }.performClick()
   }
   val deadline=System.currentTimeMillis()+8000
   while(ClientBridge.graphStatus().optString("state") !in listOf("complete","error","cancelled") && System.currentTimeMillis()<deadline)Thread.sleep(80)
   assertEquals("complete",ClientBridge.graphStatus().optString("state"))
   var drawn=false;val layoutDeadline=System.currentTimeMillis()+5000
   while(!drawn && System.currentTimeMillis()<layoutDeadline) {
    inst.runOnMainSync { drawn=views(activity!!.window.decorView).filterIsInstance<HistoryChart>().any { it.isShown && it.height>=150*context.resources.displayMetrics.density } }
    if(!drawn)Thread.sleep(80)
   }
   inst.runOnMainSync {
    val all=views(activity!!.window.decorView)
    val summary=all.filterIsInstance<GraphEnergySummary>().first { it.isShown }
    val text=summary.text.toString()
    for(label in listOf("Генерація","Споживання","Експорт","Імпорт","Сальдо","-1,50","Неповне покриття"))assertTrue(text,text.contains(label))
    val chart=all.filterIsInstance<HistoryChart>().first { it.isShown }
    val view=activity!!.window.decorView;val bitmap=Bitmap.createBitmap(view.width,view.height,Bitmap.Config.ARGB_8888);view.draw(Canvas(bitmap))
    File(context.cacheDir,"graph-energy-month-a1.6.14.png").outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG,100,it) };bitmap.recycle()
    assertTrue("chart=${chart.height}, host=${(chart.parent as View).height}, density=${context.resources.displayMetrics.density}",chart.height>=150*context.resources.displayMetrics.density)
   }
   inst.runOnMainSync { GraphFullscreenActivity.result=ClientBridge.graphStatus().getJSONObject("result") }
   fullscreen=inst.startActivitySync(Intent(context,GraphFullscreenActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
   Thread.sleep(700)
   inst.runOnMainSync {
    val all=views(fullscreen!!.window.decorView)
    val summary=all.filterIsInstance<GraphEnergySummary>().first { it.isShown }
    val scroll=all.filterIsInstance<ScrollView>().first { it.isShown }
    scroll.scrollTo(0,summary.bottom)
    assertTrue(summary.text.toString().contains("Сальдо"))
    assertTrue(all.filterIsInstance<HistoryChart>().first { it.isShown }.height>0)
    val view=fullscreen!!.window.decorView;val bitmap=Bitmap.createBitmap(view.width,view.height,Bitmap.Config.ARGB_8888);view.draw(Canvas(bitmap))
    File(context.cacheDir,"graph-energy-fullscreen-a1.6.14.png").outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG,100,it) };bitmap.recycle()
   }
  } finally { inst.runOnMainSync { fullscreen?.finish();activity?.finish() };fixture.callAttr("restore") }
 }
}
