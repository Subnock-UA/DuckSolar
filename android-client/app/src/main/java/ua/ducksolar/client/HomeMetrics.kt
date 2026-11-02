package ua.ducksolar.b2.client

import org.json.JSONObject

/** Dashboard formatting; the original metric and its provenance stay intact. */
object HomeMetrics {
 fun text(metric:JSONObject?,stale:Boolean):String = MetricText.value(
  metric?.let { JSONObject(it.toString()).put("confidence","confirmed") },stale)
 fun positive(metric:JSONObject?):Boolean = metric!=null && !metric.optBoolean("stale") && metric.optDouble("age_s",0.0)<=metric.optDouble("valid_for_s",Double.POSITIVE_INFINITY) && !metric.isNull("value") &&
  metric.optString("quality","good") in listOf("good","estimated") &&
  metric.optDouble("value",Double.NaN).let { it.isFinite() && it>0 }
 fun power(metrics:JSONObject?,direction:String):JSONObject? {
  val direct=metrics?.optJSONObject("battery.${direction}_power")
  if(direct!=null && !direct.optBoolean("stale") && direct.optDouble("age_s",0.0)<=direct.optDouble("valid_for_s",Double.POSITIVE_INFINITY) && !direct.isNull("value") && direct.optString("quality","good") in listOf("good","estimated"))return direct
  val voltage=metrics?.optJSONObject("battery.channels.main.voltage") ?: return null
  val current=metrics.optJSONObject("battery.channels.main.${direction}_current") ?: return null
  fun number(m:JSONObject):Double? {
   if(m.optBoolean("stale") || m.optDouble("age_s",0.0)>m.optDouble("valid_for_s",Double.POSITIVE_INFINITY) || m.isNull("value") || m.optString("quality","good") !in listOf("good","estimated"))return null
   return m.optDouble("value",Double.NaN).takeIf { it.isFinite() && it>=0 }
  }
  val value=(number(voltage) ?: return null)*(number(current) ?: return null)
  if(!value.isFinite())return null
  return JSONObject().put("value",value).put("unit","W").put("quality","estimated")
   .put("confidence","estimated").put("source","client.voltage_current")
   .put("stale",voltage.optBoolean("stale") || current.optBoolean("stale"))
 }
 /** Single-phase RMS current: prefer measured I, then S/U; P/U assumes unity power factor. */
 fun outputCurrent(metrics:JSONObject?):JSONObject? {
  if(metrics==null)return null
  fun number(m:JSONObject?):Double? {
   if(m==null || m.optBoolean("stale") || m.optDouble("age_s",0.0)>m.optDouble("valid_for_s",Double.POSITIVE_INFINITY) || m.isNull("value") || m.optString("quality","good") !in listOf("good","estimated"))return null
   return m.optDouble("value",Double.NaN).takeIf { it.isFinite() && it>=0 }
  }
  val direct=metrics.optJSONObject("output.phases.L1.current")
  if(number(direct)!=null)return direct
  // Aggregate S/P cannot be assigned to one phase of a multi-phase inverter.
  if(metrics.keys().asSequence().any { it.startsWith("output.phases.L2.") || it.startsWith("output.phases.L3.") })return direct
  val u=metrics.optJSONObject("output.phases.L1.voltage");val voltage=number(u)?.takeIf { it>0 } ?: return direct
  val apparent=metrics.optJSONObject("output.apparent_power")
  val active=metrics.optJSONObject("output.active_power")
  val va=number(apparent);val watts=number(active)
  val consistent=va!=null && (watts==null || va>=watts)
  val power=if(consistent)apparent else active
  val amps=(number(power) ?: return direct)/voltage
  if(!amps.isFinite())return direct
  return JSONObject().put("value",amps).put("unit","A").put("quality","estimated").put("confidence","estimated")
   .put("source",if(power===apparent)"client.apparent_power_voltage" else "client.active_power_voltage_pf1")
   .put("calculation",if(power===apparent)"S / U" else "P / U; cosφ = 1")
   .put("stale",u!!.optBoolean("stale") || power!!.optBoolean("stale"))
 }
 fun withOutputCurrent(metrics:JSONObject?):JSONObject? {
  if(metrics==null)return null
  val current=outputCurrent(metrics) ?: return metrics
  if(current===metrics.optJSONObject("output.phases.L1.current"))return metrics
  return JSONObject(metrics.toString()).put("output.phases.L1.current",current)
 }
 /** Fresh aggregate DC P/U only when this frame has no usable measured PV current. */
 fun pvCurrent(metrics:JSONObject?):JSONObject? {
  if(metrics==null)return null
  fun number(m:JSONObject?,unit:String):Double? {
   if(m==null || m.optBoolean("stale") || m.optDouble("age_s",0.0)>m.optDouble("valid_for_s",Double.POSITIVE_INFINITY) || m.isNull("value") || m.optString("unit")!=unit || m.optString("quality","good") !in listOf("good","estimated"))return null
   return m.optDouble("value",Double.NaN).takeIf { it.isFinite() && it>=0 }
  }
  val direct=metrics.optJSONObject("pv.inputs.aggregate.current")
  if(number(direct,"A")!=null)return direct
  // Total PV power must not be divided by the voltage of one of several strings.
  if(metrics.keys().asSequence().any { it.startsWith("pv.inputs.") && !it.startsWith("pv.inputs.aggregate.") || it.startsWith("pv.mppts.") })return direct
  val u=metrics.optJSONObject("pv.inputs.aggregate.voltage");val p=metrics.optJSONObject("pv.total_power")
  val voltage=number(u,"V")?.takeIf { it>0 } ?: return direct
  val watts=number(p,"W") ?: return direct
  val amps=watts/voltage
  if(!amps.isFinite())return direct
  return JSONObject().put("value",amps).put("unit","A").put("quality","estimated").put("confidence","estimated")
   .put("source","client.pv_power_voltage").put("calculation","PV P / U")
   .put("stale",u!!.optBoolean("stale") || p!!.optBoolean("stale"))
 }
 fun withDisplayCurrents(metrics:JSONObject?):JSONObject? {
  val output=withOutputCurrent(metrics) ?: return null
  val pv=pvCurrent(output) ?: return output
  if(pv===output.optJSONObject("pv.inputs.aggregate.current"))return output
  return JSONObject(output.toString()).put("pv.inputs.aggregate.current",pv)
 }
 fun batteryRows(metrics:JSONObject?):List<Pair<String,JSONObject?>> = listOf(
  "Струм заряду" to metrics?.optJSONObject("battery.channels.main.charge_current"),
  "Струм розряду" to metrics?.optJSONObject("battery.channels.main.discharge_current"),
  "Потужність від АКБ" to power(metrics,"discharge"),
  "Потужність заряду" to power(metrics,"charge"))
}
