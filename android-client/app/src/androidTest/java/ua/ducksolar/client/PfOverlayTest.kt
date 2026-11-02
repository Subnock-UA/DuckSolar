package ua.ducksolar.b2.client
import android.app.Activity
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.view.View
import android.view.ViewGroup
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

@RunWith(AndroidJUnit4::class)
class PfOverlayTest {
 private fun field(key:String,unit:String)=JSONObject().put("key",key).put("unit",unit).put("label",if(key=="output_pf")"Коефіцієнт потужності PF" else "Потужність")
 @Test fun groupingIncludesPfWithoutBlankUnit() {
  val groups=GraphUnits.groups(listOf(field("output_w","Вт"),field("output_pf","")))
  assertEquals(setOf("Вт","PF"),groups.keys)
  assertTrue(groups.getValue("Вт").any { it.getString("key")=="output_pf" })
  assertEquals("Вт + PF",GraphUnits.label("Вт",groups.getValue("Вт")))
  assertTrue(GraphUnits.dual(groups.getValue("Вт"),false))
  assertFalse(GraphUnits.dual(groups.getValue("PF"),false))
 }
 @Test fun bothCurvesVisibleWithIndependentPfScale() {
  val inst=InstrumentationRegistry.getInstrumentation();val points=JSONArray()
  for(i in 0..23)points.put(JSONObject().put("x",1793491200000L+i*60000L).put("label","01.11 02:${i.toString().padStart(2,'0')}").put("output_w",1000+i*40).put("output_pf",.6+i*.4/23))
  val result=JSONObject().put("kind","line").put("mode","power").put("points",points).put("fields",JSONArray().put(field("output_w","Вт")).put(field("output_pf","")))
  GraphFullscreenActivity.result=result;GraphFullscreenActivity.colors=mapOf("output_w" to Color.GREEN,"output_pf" to Color.MAGENTA)
  val a=inst.startActivitySync(Intent(inst.targetContext,GraphFullscreenActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as Activity
  fun all(v:View):List<View> = listOf(v)+(if(v is ViewGroup)(0 until v.childCount).flatMap { all(v.getChildAt(it)) } else emptyList())
  try {
   inst.waitForIdleSync();Thread.sleep(250)
   inst.runOnMainSync {
    val chart=all(a.window.decorView).filterIsInstance<HistoryChart>().single()
    assertTrue(HistoryChart::class.java.getDeclaredField("dual").apply { isAccessible=true }.getBoolean(chart))
    val bitmap=Bitmap.createBitmap(chart.width,chart.height,Bitmap.Config.ARGB_8888);chart.draw(Canvas(bitmap))
    val d=a.resources.displayMetrics.density;val left=(55*d).toInt();val right=(chart.width-48*d).toInt();val top=16*d;val bottom=chart.height-34*d
    var green=0;var magenta=0;var lowestPf=0
    for(y in top.toInt() until bottom.toInt())for(x in left until right) {
     val color=bitmap.getPixel(x,y)
     if(Color.green(color)>200 && Color.red(color)<50 && Color.blue(color)<50)green++
     if(Color.red(color)>200 && Color.blue(color)>200 && Color.green(color)<50) { magenta++;lowestPf=maxOf(lowestPf,y) }
    }
    assertTrue("Power curve missing",green>100);assertTrue("PF curve missing",magenta>100)
    assertTrue("PF flattened onto the watts axis",lowestPf<top+(bottom-top)*.46)
    File(a.cacheDir,"pf-overlay-chart.png").outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG,100,it) };bitmap.recycle()
    chart.scale(2.0);chart.move(.2);chart.reset()
   }
   inst.uiAutomation.takeScreenshot().also { bitmap->File(a.cacheDir,"pf-overlay-screen.png").outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG,100,it) };bitmap.recycle() }
  } finally { inst.runOnMainSync { a.finish() } }
 }
}
