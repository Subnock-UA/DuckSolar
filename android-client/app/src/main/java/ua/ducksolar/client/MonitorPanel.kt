package ua.ducksolar.b2.client
import android.content.Context
import android.widget.LinearLayout
import org.json.JSONArray
import org.json.JSONObject

/** Groups all descriptor metrics; unknown/future fields remain visible in Other. */
class MonitorPanel(private val context:Context,private val parent:LinearLayout) {
 private val cards=linkedMapOf<String,MetricCard>()
 private var signature=""
 companion object {
  fun group(key:String):String=when {
   key.startsWith("pv.")->"pv"
   key.startsWith("battery.")->"battery"
   key.startsWith("grid.")->"grid"
   key.startsWith("output.")->"output"
   key.startsWith("temperature.") || key.startsWith("dc.") || key.startsWith("inverter.")->"inverter"
   else->"other"
  }
  val groups=listOf(Triple("pv","Сонячні панелі","sun"),Triple("grid","Мережа","grid"),Triple("output","Навантаження","home"),Triple("battery","Акумулятор","battery"),Triple("inverter","Інвертор","monitor"),Triple("other","Інші показники","settings"))
 }
 fun update(definitions:JSONArray?,metrics:JSONObject?,stale:Boolean) {
  val items=if(definitions==null)mutableListOf() else (0 until definitions.length()).mapNotNull { definitions.optJSONObject(it) }.filter { it.optString("canonical_id").isNotBlank() }.distinctBy { it.optString("canonical_id") }.toMutableList()
  if(metrics?.optJSONObject("output.phases.L1.current")!=null && items.none { it.optString("canonical_id")=="output.phases.L1.current" })items.add(JSONObject().put("canonical_id","output.phases.L1.current").put("ui_name","Струм навантаження").put("unit","A"))
  if(metrics?.optJSONObject("pv.inputs.aggregate.current")!=null && items.none { it.optString("canonical_id")=="pv.inputs.aggregate.current" })items.add(JSONObject().put("canonical_id","pv.inputs.aggregate.current").put("ui_name","Струм PV").put("unit","A"))
  val order=groups.flatMap { (key,_,_)->items.filter { group(it.optString("canonical_id"))==key }.sortedWith(compareBy<JSONObject> { MonitorOrder.rank(it) }.thenBy { it.optString("canonical_id") }) }
  val next=order.joinToString("|") { it.optString("canonical_id")+":"+it.optString("ui_name") }
  if(next!=signature) { cards.values.forEach { parent.removeView(it) };cards.clear();signature=next }
  for((key,title,icon) in groups) {
   val fields=order.filter { group(it.optString("canonical_id"))==key }
   val names=fields.groupingBy { it.optString("ui_name",it.optString("canonical_id")) }.eachCount()
   val rows=fields.map { item->
    val id=item.optString("canonical_id");val label=item.optString("ui_name",id)
    (if((names[label] ?: 0)>1)"$label ($id)" else label) to metrics?.optJSONObject(id)
   }
   if(rows.isEmpty())continue
   val card=cards.getOrPut(key) { MetricCard(context,title,icon,showProvenance=true).also { parent.addView(it,LinearLayout.LayoutParams(-1,-2).apply { bottomMargin=(12*context.resources.displayMetrics.density).toInt() }) } }
   card.update(rows,stale)
  }
 }
}
