package ua.ducksolar.b2.client
import android.widget.LinearLayout
import android.widget.TextView
import android.view.View
import android.view.ViewGroup
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.json.JSONObject
import org.json.JSONArray
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class SmallPatchTest {
 private fun metric(n:Double,u:String)=JSONObject().put("value",n).put("unit",u).put("quality","good")
 @Test fun loadCurrentPrefersMeasuredThenApparentAndRejectsInvalidInputs() {
  val m=JSONObject().put("output.phases.L1.voltage",metric(230.0,"V")).put("output.apparent_power",metric(2300.0,"VA")).put("output.active_power",metric(1150.0,"W"))
  val original=m.toString();val computed=HomeMetrics.outputCurrent(m)!!
  assertEquals(10.0,computed.getDouble("value"),0.00001);assertEquals("estimated",computed.getString("confidence"));assertEquals(original,m.toString())
  m.put("output.phases.L1.current",metric(0.0,"A"));assertEquals(0.0,HomeMetrics.outputCurrent(m)!!.getDouble("value"),0.0)
  m.remove("output.phases.L1.current");m.remove("output.apparent_power")
  assertEquals(5.0,HomeMetrics.outputCurrent(m)!!.getDouble("value"),0.00001);assertTrue(HomeMetrics.outputCurrent(m)!!.getString("calculation").contains("cosφ"))
  m.put("output.phases.L1.voltage",metric(0.0,"V"));assertNull(HomeMetrics.outputCurrent(m))
  m.put("output.phases.L1.voltage",metric(230.0,"V").put("quality","missing"));assertNull(HomeMetrics.outputCurrent(m))
  m.put("output.phases.L1.voltage",metric(230.0,"V").put("stale",true));assertTrue(HomeMetrics.outputCurrent(m)!!.getBoolean("stale"))
  m.put("output.phases.L2.voltage",metric(230.0,"V"));assertNull(HomeMetrics.outputCurrent(m))
 }
 private fun finance(export:Double,day:Double,night:Double)=JSONObject().put("finance",JSONObject().put("export_kwh",export).put("import_day_kwh",day).put("import_night_kwh",night).put("sale_kwh",maxOf(0.0,export-day-night)).put("import_cost_uah",25.0).put("green_net_uah",50.0)).put("delta",JSONObject()).put("tariff",JSONObject())
 @Test fun saldoKeepsDeficitZeroAndSurplusAndMissingDistinct() {
  val deficit=finance(50.0,60.0,40.0);assertEquals(-50.0,EnergySaldo.financeEnergy(deficit)!!,0.0);assertTrue(EnergySaldo.financeLabel(deficit).contains("-50"))
  assertEquals(0.0,EnergySaldo.financeEnergy(finance(100.0,60.0,40.0))!!,0.0)
  assertTrue(EnergySaldo.financeLabel(finance(150.0,60.0,40.0)).contains("+50"))
  deficit.getJSONObject("delta").put("boundary_adjusted",true);assertTrue(EnergySaldo.financeLabel(deficit).contains("розрах."))
  deficit.getJSONObject("finance").put("green_net_uah",0.0);deficit.remove("tariff");assertTrue(EnergySaldo.money(deficit).contains("-25"))
  val surplus=finance(150.0,60.0,40.0);surplus.remove("tariff");assertTrue(EnergySaldo.money(surplus).contains("тариф"))
  deficit.getJSONObject("finance").remove("import_night_kwh");assertNull(EnergySaldo.financeEnergy(deficit))
 }
 @Test fun inverterSaldoRespectsCoverageAndHouseIsSeparate() {
  fun energy(n:Double,coverage:Double)=JSONObject().put("kwh",n).put("coverage_pct",coverage).put("missing_pct",100-coverage)
  val r=JSONObject().put("inverter_import",energy(100.0,100.0)).put("inverter_export",energy(40.0,100.0)).put("house_meter",JSONObject().put("import_kwh",110.0).put("export_kwh",80.0))
  assertTrue(EnergySaldo.inverter(r).contains("-60"));assertTrue(EnergySaldo.house(r).contains("-30"))
  r.getJSONObject("inverter_import").put("missing_pct",30);assertTrue(EnergySaldo.inverter(r).contains("неповне"))
  r.getJSONObject("inverter_import").put("coverage_pct",0);assertTrue(EnergySaldo.inverter(r).contains("немає даних"))
  r.getJSONObject("house_meter").put("export_kwh",JSONObject.NULL);assertTrue(EnergySaldo.house(r).contains("немає даних"))
 }
 @Test fun monitorGroupsAllFieldsAndRemovesOldDeviceRows() {
  val inst=InstrumentationRegistry.getInstrumentation()
  inst.runOnMainSync {
   val parent=LinearLayout(inst.targetContext);val panel=MonitorPanel(inst.targetContext,parent)
   val ids=listOf("pv.total_power","grid.phases.L1.voltage","output.active_power","battery.channels.main.soc","temperature.inverter","new.future.field")
   val defs=JSONArray();val metrics=JSONObject()
   for(id in ids) { defs.put(JSONObject().put("canonical_id",id).put("ui_name",id));metrics.put(id,metric(2.0,"W")) }
   panel.update(defs,metrics,false);assertEquals(6,parent.childCount)
   fun texts(v:View):List<String> = (if(v is TextView)listOf(v.text.toString()) else emptyList())+(if(v is ViewGroup)(0 until v.childCount).flatMap { texts(v.getChildAt(it)) } else emptyList())
   for(id in ids)assertTrue(texts(parent).contains(id))
   panel.update(JSONArray().put(JSONObject().put("canonical_id","pv.new").put("ui_name","Новий PV")),JSONObject(),false)
   assertEquals(1,parent.childCount);assertFalse(texts(parent).contains("new.future.field"))
  }
 }
}
