package ua.ducksolar.b2.client

import android.content.Intent
import android.graphics.*
import android.view.View
import android.view.ViewGroup
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.chaquo.python.Python
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

@RunWith(AndroidJUnit4::class)
class ForecastAdapterPatchTest {
 @Test fun serverV4PassesThroughRealBridgeIntoVisibleActualSeries() {
  val inst=InstrumentationRegistry.getInstrumentation();val context=inst.targetContext
  ClientBridge.initialize(context)
  val source=inst.context.assets.open("forecast-fact-regression.json").bufferedReader().readText()
  val module=Python.getInstance().getModule("forecast_adapter_checks")
  val expected=JSONObject(module.callAttr("prepare",source).toString())
  var activity:InsightsActivity?=null
  fun views(v:View):List<View> = listOf(v)+(if(v is ViewGroup)(0 until v.childCount).flatMap { views(v.getChildAt(it)) } else emptyList())
  try {
   val state=ClientBridge.featureStart("forecast","2026-11-01","","day","pv_w")
   assertEquals(state.toString(),"complete",state.optString("state"))
   val result=state.getJSONObject("result")
   assertEquals("bars",result.getJSONObject("graph").getString("kind"))
   assertEquals(expected.getJSONObject("graph").toString(),result.getJSONObject("graph").toString())
   val points=result.getJSONObject("graph").getJSONArray("points")
   assertEquals(1.7,points.getJSONObject(0).getDouble("actual"),.00001)
   assertEquals(1.9,points.getJSONObject(1).getDouble("actual"),.00001)
   module.callAttr("restore")
   val a=inst.startActivitySync(Intent(context,InsightsActivity::class.java).putExtra("page","forecast_actual").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as InsightsActivity
   activity=a
   inst.runOnMainSync { InsightsActivity::class.java.getDeclaredMethod("renderResult",JSONObject::class.java).apply { isAccessible=true }.invoke(a,result) }
   inst.waitForIdleSync()
   inst.runOnMainSync {
    val chart=views(a.window.decorView).filterIsInstance<HistoryChart>().single()
    val bitmap=Bitmap.createBitmap(900,600,Bitmap.Config.ARGB_8888);chart.layout(0,0,900,600);chart.draw(Canvas(bitmap))
    var teal=0
    for(y in 20 until 560 step 2)for(x in 150 until 850 step 2) { val p=bitmap.getPixel(x,y);if(Color.red(p)<60 && Color.green(p)>70 && Color.blue(p)>60)teal++ }
    assertTrue("Facts must survive Python adapter, bridge and renderer",teal>500)
    File(context.cacheDir,"forecast-adapter-chart.png").outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG,100,it) };bitmap.recycle()
    File(context.cacheDir,"forecast-adapter-result.json").writeText(result.toString())
   }
  } finally { module.callAttr("restore");activity?.let { a->inst.runOnMainSync { a.finish() } } }
 }
}
