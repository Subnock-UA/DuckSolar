package ua.ducksolar.b2.client
import org.json.JSONObject
object MetricText {
 fun value(metric:JSONObject?,stale:Boolean):String {
  if(stale || metric?.optBoolean("stale")==true || (metric!=null && metric.optDouble("age_s",0.0)>metric.optDouble("valid_for_s",Double.POSITIVE_INFINITY)))return "—"
  if(metric==null || !metric.has("value") || metric.isNull("value"))return "—"
  if(metric.optString("quality","good") !in listOf("good","estimated"))return "— (дані недоступні)"
  val raw=metric.opt("value")
  if(raw is Number && !raw.toDouble().isFinite())return "—"
  val duration=if(raw is Number)DurationText.value(raw.toDouble(),metric.optString("unit")) else null
  val text=duration ?: if(raw is Number)String.format(java.util.Locale.getDefault(),if(metric.optInt("precision",1)==2)"%.2f" else "%.1f",raw.toDouble()).removeSuffix(",0").removeSuffix(".0") else if(raw is Boolean) { if(raw)"Так" else "Ні" } else raw.toString()
  val confidence=metric.optString("confidence")
  val note=when(confidence) { "estimated"->" (розрах.)";else->"" }
  return DisplayText.clean(text)+(if(duration==null)" "+metric.optString("unit") else "")+note+(if(metric.optString("warning").isNotBlank())" ⚠ "+metric.optString("warning") else "")+if(stale || metric.optBoolean("stale"))" • застаріле" else ""
 }
}
