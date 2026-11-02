package ua.ducksolar.b2.client
import android.widget.*
import android.graphics.Bitmap
import android.graphics.Canvas
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.json.*
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
@RunWith(AndroidJUnit4::class)
class Patch21Test {
 @Test fun adaptiveAxesAreRoundedAndCoverSmallNegativeConstantRanges() {
  val a=ChartAxis.scale(3.0,15.0,7);assertEquals(2.0,a.low,0.0);assertEquals(16.0,a.high,0.0);assertEquals(2.0,a.step,0.0)
  for((low,high) in listOf(-3.1 to 15.2,0.0 to 0.0,3.0 to 3.0,0.003 to 0.015,12345.0 to 98765.0)) {
   val scale=ChartAxis.scale(low,high,6);assertTrue(scale.low<=low);assertTrue(scale.high>=high);assertTrue(scale.high>scale.low);assertTrue(scale.step>0);assertTrue(scale.ticks.size<=12)
  }
  assertTrue(ChartAxis.timeTicks(1792303200000.0,1792306800000.0,4).all { it.label.matches(Regex("\\d{2}:\\d{2}")) })
 }
 @Test fun noUnconfirmedAcronymForAnyMetricParameterEventOrLateTextUpdate() {
  val inst=InstrumentationRegistry.getInstrumentation();inst.runOnMainSync {
   val metric=JSONObject().put("value",42).put("unit","V")
   for(confidence in listOf("unknown","unverified","protocol_family","confirmed","high_probability","unavailable")) {
    metric.put("confidence",confidence);assertFalse(MetricText.value(metric,false).contains("НП"))
    val row=JSONObject().put("present",true).put("raw_value",42).put("display_value","42 (НП)").put("confidence",confidence)
    assertFalse(CommandText.value(row,false).contains("НП"));assertTrue(CommandText.value(row,false).contains("42"))
   }
   val root=LinearLayout(inst.targetContext);val label=TextView(inst.targetContext);root.addView(label);AppStyle.watch(root)
   label.text="Старий сервер (НП): дані НП";assertFalse(label.text.toString().contains("НП"));assertTrue(label.text.toString().contains("дані"))
   assertEquals("НПА",DisplayText.clean("НПА"));assertEquals("Тест",DisplayText.clean("Тест (НП)"))
  }
 }
 @Test fun inconsistentVaFallsBackToActiveEstimateWithoutChangingRaw() {
  val m=JSONObject().put("output.phases.L1.voltage",JSONObject().put("value",220)).put("output.apparent_power",JSONObject().put("value",242)).put("output.active_power",JSONObject().put("value",836))
  val raw=m.toString();val current=HomeMetrics.outputCurrent(m)!!;assertEquals(3.8,current.getDouble("value"),.0001);assertTrue(current.getString("calculation").contains("cosφ"));assertEquals(raw,m.toString())
  m.getJSONObject("output.apparent_power").put("quality","inconsistent");assertEquals(3.8,HomeMetrics.outputCurrent(m)!!.getDouble("value"),.0001)
 }
 @Test fun negativeBarsAndRoundedAxesRenderAfterZoom() {
  val inst=InstrumentationRegistry.getInstrumentation();inst.runOnMainSync {
   val rows=(0..5).map { JSONObject().put("x",it).put("label","2026-10-${18+it}").put("pv_w",it-3) }
   val fields=listOf(JSONObject().put("key","pv_w").put("unit","кВт·год").put("label","Генерація"))
   val chart=HistoryChart(inst.targetContext,rows,fields,true,mapOf("pv_w" to android.graphics.Color.BLUE),1.5f){}
   chart.layout(0,0,800,500);val bitmap=Bitmap.createBitmap(800,500,Bitmap.Config.ARGB_8888);chart.draw(Canvas(bitmap));chart.scale(2.0);chart.draw(Canvas(bitmap));bitmap.recycle()
  }
 }
}
