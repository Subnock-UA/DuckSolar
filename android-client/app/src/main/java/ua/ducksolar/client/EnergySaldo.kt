package ua.ducksolar.b2.client
import org.json.JSONObject
import java.util.Locale

/** Energy exchange is signed, unlike the non-negative amount eligible for sale. */
object EnergySaldo {
 fun number(row:JSONObject?,key:String):Double? = if(row==null || row.isNull(key))null else row.optDouble(key,Double.NaN).takeIf { it.isFinite() }
 fun signed(value:Double?,unit:String="кВт·год"):String = if(value==null)"— (немає даних)" else String.format(Locale.getDefault(),"%+.3f %s",if(kotlin.math.abs(value)<0.0005)0.0 else value,unit)
 fun financeEnergy(record:JSONObject):Double? {
  val f=record.optJSONObject("finance") ?: return null
  val imported=(number(f,"import_day_kwh") ?: return null)+(number(f,"import_night_kwh") ?: return null)
  val exported=number(f,"export_kwh") ?: ((number(f,"export_day_kwh") ?: return null)+(number(f,"export_night_kwh") ?: return null))
  return exported-imported
 }
 fun financeLabel(record:JSONObject):String {
  val d=record.optJSONObject("delta")
  return "Сальдо (експорт − імпорт): "+signed(financeEnergy(record))+" (лічильник, за фактичними межами)"
 }
 fun money(record:JSONObject):String {
  val f=record.optJSONObject("finance");val cost=number(f,"import_cost_uah") ?: return "— (немає даних)"
  val sale=number(f,"sale_kwh") ?: return "— (немає даних)"
  val net=if(record.optJSONObject("tariff")==null) { if(sale>0)return "— (зелений тариф не заданий)" else 0.0 } else number(f,"green_net_uah") ?: return "— (немає даних)"
  return String.format(Locale.getDefault(),"%+.2f грн",if(kotlin.math.abs(net-cost)<0.005)0.0 else net-cost)
 }
 fun inverter(report:JSONObject):String {
  val imported=report.optJSONObject("inverter_import");val exported=report.optJSONObject("inverter_export")
  val i=number(imported,"kwh");val e=number(exported,"kwh")
  val valid=i!=null && e!=null && (number(imported,"coverage_pct") ?: 0.0)>0 && (number(exported,"coverage_pct") ?: 0.0)>0
  val partial=(number(imported,"missing_pct") ?: 100.0)>0 || (number(exported,"missing_pct") ?: 100.0)>0
  return "Сальдо інвертора (експорт − імпорт): "+signed(if(valid)e!!-i!! else null)+(if(valid)" (розрах. за історією)" else "")+(if(valid && partial)" • неповне покриття" else "")
 }
 fun house(report:JSONObject):String {
  val h=report.optJSONObject("house_meter");val i=number(h,"import_kwh");val e=number(h,"export_kwh")
  val segments=h?.optJSONArray("segments")
  val estimated=segments!=null && (0 until segments.length()).any { segments.optJSONObject(it)?.optString("source")=="meter_estimated_boundary" }
  return "Сальдо будинку (експорт − імпорт): "+signed(if(i!=null && e!=null)e-i else null)+(if(i!=null && e!=null)if(estimated)" (розрах.)" else " (лічильник)" else "")
 }
}
