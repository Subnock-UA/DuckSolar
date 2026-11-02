package ua.ducksolar.b2.client
import org.json.JSONObject

/** A friendly alias is shown only for the server's verified equipment profile. */
object InverterName {
 fun display(descriptor:JSONObject,identity:JSONObject?):String {
  fun usable(value:String)=value.isNotBlank() && value!="null"
  val model=descriptor.optString("model").takeIf(::usable) ?: identity?.optString("model")?.takeIf(::usable) ?: return "—"
  return if(model=="VMII-NXPW5KW" && descriptor.optBoolean("profile_confirmed") &&
   descriptor.optString("profile_id")=="daxtromn.vmii-nxpw5kw.00074.11")"DAXTROMN AGH 6.2 PRO" else model
 }
}
