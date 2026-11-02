package ua.ducksolar.b2.client
import android.app.Activity
import android.widget.LinearLayout
import android.widget.TextView
import org.json.JSONObject
import java.util.Locale

object HouseMeterView {
 fun add(activity:Activity,parent:LinearLayout,row:JSONObject,title:String="Лічильник будинку") {
  fun text(value:String,size:Float=14f) { parent.addView(TextView(activity).apply { text=value;textSize=size;setPadding(8,12,8,12);setTextIsSelectable(true) }) }
  fun number(key:String)=if(row.isNull(key))"—" else row.optDouble(key,Double.NaN).takeIf { it.isFinite() }?.let { String.format(Locale.getDefault(),"%.3f",it) } ?: "—"
  text(title+" • достовірні інтервали",18f)
  if(row.isNull("import_kwh") || !row.has("import_kwh"))text("У межах вибраного періоду немає повного інтервалу між показниками.")
  else text("${row.optString("period_start")} → ${row.optString("period_end")}\nІмпорт: ${number("import_kwh")} кВт·год • Експорт: ${number("export_kwh")} кВт·год\nСальдо: ${number("saldo_kwh")} кВт·год")
  val refs=row.optJSONArray("reference_intervals")
  if(row.isNull("import_kwh") && refs!=null && refs.length()>0) {
   text("Наявні показники охоплюють більший фактичний інтервал:")
   for(i in 0 until refs.length().coerceAtMost(3)) { val ref=refs.getJSONObject(i);text("${ref.optString("start")} → ${ref.optString("end")}\nІмпорт ${String.format(Locale.getDefault(),"%.3f",ref.optDouble("import"))}, експорт ${String.format(Locale.getDefault(),"%.3f",ref.optDouble("export"))} кВт·год (за весь інтервал)") }
  }
  text("Фактичні межі показників можуть відрізнятися від календарних меж графіка. Розподіл по днях/годинах є оцінкою. Це облік будинку, а не лише інвертора.",12f)
 }
}
