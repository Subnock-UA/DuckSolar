package ua.ducksolar.b2.client
import android.app.Activity
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.widget.*
import org.json.JSONObject
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
class ConnectionHealthActivity:ua.ducksolar.shared.LocalizedActivity() {
 private val handler=Handler(Looper.getMainLooper());private val pending=AtomicBoolean(false)
 private var visible=false;private var generation=0;private lateinit var content:TextView
 companion object { private val worker=Executors.newSingleThreadExecutor() }
 private val tick=object:Runnable { override fun run() { if(!visible)return;refresh();handler.postDelayed(this,2000) } }
 override fun onCreate(state:Bundle?) {
  super.onCreate(state);title="Стан сервера"
  val body=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL;setPadding(20,16,20,16) }
  Button(this).apply { text="‹ Додатково";isAllCaps=false;body.addView(this);setOnClickListener { finish() } }
  content=TextView(this).apply { textSize=16f;setTextIsSelectable(true);body.addView(this) }
  setContentView(ScrollView(this).apply { addView(body) });AppStyle.apply(body)
 }
 private fun refresh() {
  if(!pending.compareAndSet(false,true))return
  val version=generation
  worker.execute {
   val text=try { render(ClientBridge.connectionHealth()) } catch(_:Exception) { "Стан сервера поки недоступний" }
   handler.post { pending.set(false);if(visible && version==generation && !isDestroyed)content.text=text }
  }
 }
 private fun render(value:JSONObject):String {
  fun stamp(obj:JSONObject?)=if(obj==null)"—" else try { Instant.ofEpochMilli((obj.getDouble("time")*1000).toLong()).atZone(ZoneId.systemDefault()).format(DateTimeFormatter.ofPattern("dd.MM HH:mm:ss")) } catch(_:Exception) { "—" }
  fun reason(code:String)=when(code) { "live.closed"->"Живий канал закрито";"connection.timeout"->"Час очікування відповіді вичерпано";"connection.unreachable"->"Маршрут недоступний";"auth.required"->"Потрібен вхід";else->code.ifBlank { "—" } }
  val history=value.optJSONObject("history") ?: JSONObject();val failure=history.optJSONObject("last_failure");val success=history.optJSONObject("last_connection")
  val age=if(value.isNull("last_received_age_s"))"—" else DurationText.seconds(value.optDouble("last_received_age_s",Double.NaN))
  val phone=value.optJSONObject("server_phone") ?: JSONObject()
  val fresh=value.optBoolean("connected") && value.optDouble("last_received_age_s",999.0)<=15 && phone.optBoolean("available") && phone.optDouble("age_s",999.0)<=45
  fun number(key:String)=if(fresh && !phone.isNull(key))phone.optDouble(key).let { if(it.isFinite())String.format(java.util.Locale.getDefault(),"%.0f",it) else "—" } else "—"
  val power=if(!fresh || phone.isNull("external_power"))"—" else if(phone.optBoolean("external_power"))"від зарядного пристрою" else "від батареї"
  val wifi=if(!fresh || phone.isNull("wifi_connected"))"—" else if(!phone.optBoolean("wifi_connected"))"не підключено" else if(phone.isNull("wifi_rssi_dbm"))"підключено; рівень недоступний" else "${number("wifi_rssi_dbm")} dBm"
  return listOf(
   "Сервер: "+if(value.optBoolean("connected"))"підключено" else "немає зв’язку",
   "Батарея телефона сервера: "+number("battery_percent").let { if(it=="—")it else "$it%" },
   "Живлення сервера: $power", "Wi-Fi сервера: $wifi", "",
   "Маршрут: "+if(value.optString("route")=="local")"LAN" else "віддалений",
   "Останній обмін: $age тому",
   "Інвертор: "+if(value.optBoolean("inverter_stale",true))"дані недоступні або застарілі" else "дані актуальні",
   "Час даних інвертора: ${value.optString("inverter_updated").ifBlank { "—" }}",
   "", "Мережа телефона клієнта: "+if(value.optBoolean("network_available"))"доступна" else "недоступна",
   "Wi-Fi клієнта: "+if(value.optBoolean("wifi_available"))"доступний" else "недоступний",
   "Автоматичне відновлення увімкнене",
   "Ручний пріоритет: ${DurationText.seconds(value.optDouble("manual_priority_remaining_s",Double.NaN))}",
   "", "Останнє підключення: ${stamp(success)}", "Остання помилка: ${stamp(failure)}",
   reason(failure?.optString("code") ?: ""), "", "За цей запуск клієнта:",
   "Події помилок обміну: ${history.optInt("disconnects")}",
   "Невдалі спроби маршруту: ${history.optInt("route_failures")}", "Повторні спроби також враховані."
  ).joinToString("\n")
 }
 override fun onResume() { super.onResume();ClientLifecycle.enter();visible=true;generation++;handler.post(tick) }
 override fun onPause() { ClientLifecycle.leave();visible=false;generation++;handler.removeCallbacks(tick);super.onPause() }
}
