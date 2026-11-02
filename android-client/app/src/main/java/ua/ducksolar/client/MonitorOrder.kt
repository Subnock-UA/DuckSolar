package ua.ducksolar.b2.client
import org.json.JSONObject

/** Stable semantic order, independent of changing metric values. */
object MonitorOrder {
 fun rank(item:JSONObject):Int {
  val key=item.optString("canonical_id").lowercase()
  val unit=item.optString("unit")
  if(listOf("nominal","rated","firmware","version","serial","protocol","raw","setting","priority","limit").any { key.contains(it) })return 90
  if(key.contains("voltage"))return 0
  if(unit in listOf("W","VA","kW") || key.contains("power"))return 10
  if(unit=="A" || key.contains("current"))return 20
  if(key=="battery.channels.main.remaining_energy")return 31
  if(key=="battery.channels.main.inverter_soc")return 32
  if(key.startsWith("battery.") && (key.contains("soc") || key.contains("capacity")))return 30
  if(key.contains("mode") || key.contains("state") || key.contains("status") || key.contains("available"))return 40
  if(key.contains("frequency") || key.contains("temperature"))return 50
  return 70
 }
}
