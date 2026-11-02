package ua.ducksolar.b2.client

import android.content.Context
import android.graphics.Color
import android.widget.TextView
import org.json.JSONObject
import java.util.Locale

/** Server totals use the same full-resolution range as the graph. */
class GraphEnergySummary(context:Context, result:JSONObject):TextView(context) {
 init {
  textSize=13f
  setTextColor(Color.rgb(38,54,65))
  val pad=(8*resources.displayMetrics.density).toInt()
  setPadding(pad,pad,pad,pad)
  setBackgroundColor(Color.rgb(239,246,249))
  setTextIsSelectable(true)
  val totals=result.optJSONObject("energy_summary")
  if(totals==null)text="Підсумки цього графіка доступні з Server a1.4.22."
  else {
   fun value(key:String):String {
    val item=totals.optJSONObject(key)
    if(item==null || item.isNull("kwh"))return "—"
    val number=item.optDouble("kwh",Double.NaN)
    if(!number.isFinite())return "—"
    return String.format(Locale.forLanguageTag("uk-UA"),if(key=="balance")"%+.2f" else "%.2f",number)
   }
   val partial=listOf("generation","consumption","export","import").any { totals.optJSONObject(it)?.optBoolean("partial",true)!=false }
   text="За період графіка · кВт·год\n"+
    "Генерація: ${value("generation")}    Споживання: ${value("consumption")}\n"+
    "Експорт: ${value("export")}    Імпорт: ${value("import")}\n"+
    "Сальдо (експорт − імпорт): ${value("balance")}"+
    if(partial)"\nНеповне покриття · — немає даних; пропуски не є нулями." else ""
  }
 }
}
