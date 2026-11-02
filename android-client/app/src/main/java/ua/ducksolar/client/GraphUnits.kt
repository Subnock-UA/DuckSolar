package ua.ducksolar.b2.client
import org.json.JSONObject

/** PF accompanies each dimensional group, with an independent fixed 0..1 axis. */
object GraphUnits {
 const val PF="output_pf"
 fun groups(fields:List<JSONObject>):Map<String,List<JSONObject>> {
  val pf=fields.filter { it.optString("key")==PF }
  val other=fields.filter { it.optString("key")!=PF }
  val result=linkedMapOf<String,List<JSONObject>>()
  for((unit,rows) in other.groupBy { it.optString("unit") })result[unit.ifBlank { "Безрозмірні" }]=rows+pf
  if(pf.isNotEmpty())result["PF"]=pf
  return result
 }
 fun label(unit:String,fields:List<JSONObject>):String = unit+if(unit!="PF" && fields.any { it.optString("key")==PF })" + PF" else ""
 fun dual(fields:List<JSONObject>,bars:Boolean)=!bars && fields.any { it.optString("key")==PF } && fields.any { it.optString("key")!=PF }
}
