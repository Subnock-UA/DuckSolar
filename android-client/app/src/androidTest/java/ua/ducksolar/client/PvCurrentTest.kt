package ua.ducksolar.b2.client
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class PvCurrentTest {
 private fun m(n:Double,u:String)=JSONObject().put("value",n).put("unit",u).put("quality","good")
 @Test fun alternatingQpigsAndNativeFramesKeepPvVisibleWithoutHoldingOldValue() {
  val frame=JSONObject().put("pv.total_power",m(709.0,"W")).put("pv.inputs.aggregate.voltage",m(353.1,"V")).put("pv.inputs.aggregate.current",m(2.0,"A"))
  assertEquals(2.0,HomeMetrics.withDisplayCurrents(frame)!!.getJSONObject("pv.inputs.aggregate.current").getDouble("value"),0.0)
  frame.remove("pv.inputs.aggregate.current");val before=frame.toString()
  val fallback=HomeMetrics.withDisplayCurrents(frame)!!.getJSONObject("pv.inputs.aggregate.current")
  assertEquals(709.0/353.1,fallback.getDouble("value"),0.00001);assertEquals("estimated",fallback.getString("confidence"));assertEquals(before,frame.toString())
  frame.getJSONObject("pv.total_power").put("value",353.1)
  assertEquals(1.0,HomeMetrics.withDisplayCurrents(frame)!!.getJSONObject("pv.inputs.aggregate.current").getDouble("value"),0.00001)
  frame.put("pv.inputs.aggregate.current",m(1.2,"A"));assertEquals(1.2,HomeMetrics.withDisplayCurrents(frame)!!.getJSONObject("pv.inputs.aggregate.current").getDouble("value"),0.0)
  val inst=InstrumentationRegistry.getInstrumentation()
  inst.runOnMainSync { val view=FlowDiagram(inst.targetContext);frame.remove("pv.inputs.aggregate.current");view.update(frame,false,"Приклад");assertFalse(view.contentDescription.toString().substringAfter("PV струм:").substringBefore("\n").contains("—")) }
 }
 @Test fun zeroMissingInvalidAndMultipleInputsStayDistinct() {
  val frame=JSONObject().put("pv.total_power",m(0.0,"W")).put("pv.inputs.aggregate.voltage",m(0.0,"V")).put("pv.inputs.aggregate.current",m(0.0,"A"))
  assertEquals(0.0,HomeMetrics.pvCurrent(frame)!!.getDouble("value"),0.0)
  frame.remove("pv.inputs.aggregate.current");assertNull(HomeMetrics.pvCurrent(frame))
  frame.getJSONObject("pv.inputs.aggregate.voltage").put("value",350.0);assertEquals(0.0,HomeMetrics.pvCurrent(frame)!!.getDouble("value"),0.0)
  frame.getJSONObject("pv.total_power").put("quality","missing");assertNull(HomeMetrics.pvCurrent(frame))
  frame.getJSONObject("pv.total_power").put("quality","good");frame.put("pv.inputs.2.voltage",m(300.0,"V"));assertNull(HomeMetrics.pvCurrent(frame))
 }
 @Test fun outputAndPvCalculationsCoexistAndPreserveStaleness() {
  val frame=JSONObject().put("pv.total_power",m(600.0,"W")).put("pv.inputs.aggregate.voltage",m(300.0,"V").put("stale",true)).put("output.apparent_power",m(2300.0,"VA")).put("output.phases.L1.voltage",m(230.0,"V"))
  val computed=HomeMetrics.withDisplayCurrents(frame)!!
  assertEquals(2.0,computed.getJSONObject("pv.inputs.aggregate.current").getDouble("value"),0.0);assertTrue(computed.getJSONObject("pv.inputs.aggregate.current").getBoolean("stale"))
  assertEquals(10.0,computed.getJSONObject("output.phases.L1.current").getDouble("value"),0.0)
  assertFalse(frame.has("pv.inputs.aggregate.current"));assertFalse(frame.has("output.phases.L1.current"))
 }
}
