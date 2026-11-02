package ua.ducksolar.b2.client

import android.app.Activity
import android.app.AlertDialog
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.InputType
import android.widget.*
import org.json.JSONObject
import java.util.Locale
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

class WeatherActivity:ua.ducksolar.shared.LocalizedActivity() {
 companion object { private val worker=Executors.newSingleThreadExecutor() }
 private val handler=Handler(Looper.getMainLooper())
 private val pending=AtomicBoolean(false)
 private var visible=false
 private var data=JSONObject()
 private var signature=""
 private lateinit var body:LinearLayout
 private lateinit var status:TextView
 private lateinit var cards:LinearLayout
 private lateinit var refresh:Button
 private lateinit var train:Button
 private lateinit var cancel:Button
 private lateinit var settings:Button
 private fun Int.dp()=(this*resources.displayMetrics.density).toInt()
 private fun label(parent:LinearLayout,value:String,size:Float=15f)=TextView(this).apply {
  text=value;textSize=size;setTextIsSelectable(true);setPadding(0,8.dp(),0,8.dp());parent.addView(this)
 }
 private fun button(parent:LinearLayout,title:String,action:()->Unit)=Button(this).apply {
  text=title;parent.addView(this);setOnClickListener { action() }
 }
 override fun onCreate(state:Bundle?) {
  super.onCreate(state)
  window.statusBarColor=AppStyle.canvas;window.navigationBarColor=AppStyle.canvas
  window.decorView.systemUiVisibility=ViewFlags.lightBars
  body=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL;setPadding(16.dp(),8.dp(),16.dp(),16.dp());setBackgroundColor(AppStyle.canvas) }
  val scroll=ScrollView(this).apply { addView(body) };setContentView(scroll)
  scroll.setOnApplyWindowInsetsListener { _,i->scroll.setPadding(i.systemWindowInsetLeft,i.systemWindowInsetTop,i.systemWindowInsetRight,i.systemWindowInsetBottom);i }
  button(body,"‹ Додатково") { finish() }
  label(body,"Погода та прогноз",26f)
  status=label(body,"Завантаження збереженого прогнозу…",14f)
  val actions=LinearLayout(this);body.addView(actions)
  refresh=button(actions,"Оновити") { request { if(data.optString("state")=="paused")ClientBridge.weatherResume() else ClientBridge.weatherStart(false) } }
  settings=button(actions,"Налаштувати") { editSettings() }
  train=button(actions,"Навчити") {
   ua.ducksolar.shared.LocalizedDialog.Builder(this).setTitle("Навчання прогнозу")
    .setMessage("Сервер навчить прогноз за добами з покриттям щонайменше95% сонячного часу. Завдання працюватиме без відкритого клієнта; автоматичне перенавчання виконується під час заряджання сервера. Дані інвертора не змінюються.")
    .setPositiveButton("Почати") { _,_->request { ClientBridge.weatherStart(true) } }.setNegativeButton("Скасувати",null).show()
  }
  cancel=button(body,"Скасувати завдання") { request { ClientBridge.weatherCancel() } }
  cancel.visibility=android.view.View.GONE
  cards=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL;body.addView(this) }
  label(body,"Джерело: Open-Meteo · open-meteo.com · CC BY 4.0. Прогноз є оцінкою, а не виміряною генерацією.",12f)
  actions.removeView(settings)
  body.addView(settings)
  CompactSections.apply(body,false)
  AppStyle.apply(body)
 }
 private fun request(action:()->JSONObject) {
  if(!pending.compareAndSet(false,true))return
  worker.execute {
   try { val value=action();runOnUiThread { if(!isDestroyed && !isFinishing)render(value) } }
   catch(e:Exception) { runOnUiThread { if(!isDestroyed && !isFinishing)status.text=e.message ?: "Прогноз недоступний" } }
   finally { pending.set(false) }
  }
 }
 private fun value(row:JSONObject,key:String,unit:String):String {
  val v=if(row.isNull(key))Double.NaN else row.optDouble(key,Double.NaN)
  return DurationText.value(v,unit) ?: if(v.isFinite())String.format(Locale.getDefault(),"%.1f %s",v,unit) else "—"
 }
 private fun render(job:JSONObject) {
  data=job
  val running=job.optString("state")=="running"
  refresh.isEnabled=!running;train.isEnabled=!running;settings.isEnabled=!running
  refresh.text=if(job.optString("state")=="paused")"Продовжити" else "Оновити"
  cancel.visibility=if(running || job.optString("state")=="paused")android.view.View.VISIBLE else android.view.View.GONE
  val result=job.optJSONObject("result")
  status.text=when {
   running->when(job.optString("phase")) {
    "pausing"->"Збереження стану перед паузою…"
    "cancelling"->"Скасування…"
    "history"->"Історія: збережено ${job.optInt("done")} із ${job.optInt("total")} днів\nПоточний пакет: ${job.optInt("server_done")} / ${job.optInt("server_total")}. Пакетів: ${job.optInt("batch")}."
    "training_weather"->"Завантаження архіву прогнозів для навчання…"
    "forecast"->"Розрахунок прогнозу генерації…"
    "location"->"Пошук населеного пункту…"
    else->"Оновлення погоди…"
   }
   job.optString("state")=="paused"->"Завдання призупинено. Збережені пакети історії залишилися. Натисніть «Продовжити»."
   job.optString("state")=="cancelled"->"Завдання скасовано. Попередній прогноз і отримана історія збережені."
   job.optString("state")=="error"->"Оновлення не виконано: ${job.optString("error")}\nЗбережений прогноз нижче, якщо він є."
   result!=null->"Збережений прогноз · ${result.optString("updated").replace('T',' ')}\nДля актуальних даних натисніть «Оновити»."
   else->"Налаштуйте населений пункт і параметри панелей, потім натисніть «Оновити»."
  }
  job.optString("training_note").takeIf { it.isNotBlank() }?.let { status.append("\n"+it) }
  val next=result?.toString() ?: ""
  if(signature==next)return
  signature=next;cards.removeAllViews()
  if(result==null)return
  val location=result.optJSONObject("location") ?: JSONObject()
  label(cards,listOf(location.optString("name"),location.optString("admin1")).filter { it.isNotBlank() }.joinToString(" · "),20f)
  val profile=result.optJSONObject("pv_profile") ?: JSONObject()
  val calibration=result.optJSONObject("calibration") ?: JSONObject()
  val days=result.optJSONArray("days") ?: return
  val forecasts=result.optJSONObject("generation_by_day") ?: JSONObject()
  for(i in 0 until days.length()) {
   val day=days.getJSONObject(i)
   val card=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL;setPadding(12.dp(),8.dp(),12.dp(),8.dp());background=AppStyle.shape(this@WeatherActivity,android.graphics.Color.WHITE);cards.addView(this,LinearLayout.LayoutParams(-1,-2).apply { bottomMargin=10.dp() }) }
   label(card,"${day.optString("date")} · ${day.optString("condition")}",19f)
   val prediction=forecasts.optJSONObject(day.optString("date"))
   if(prediction==null)label(card,"Прогноз PV: немає повних даних сонячної радіації",14f)
   else {
    label(card,"Генерація PV ≈ ${value(prediction,"expected_kwh","кВт·год")}",22f)
    label(card,"Діапазон ${value(prediction,"low_kwh","")}–${value(prediction,"high_kwh","кВт·год")} · достовірність: ${prediction.optString("confidence")}\nПрогноз сформовано: ${prediction.optString("issued_at")}",13f)
   }
   label(card,"Температура: ${value(day,"temp_min_c","°C")} … ${value(day,"temp_max_c","°C")}\nОпади: ${value(day,"precip_probability_pct","%")} · ${value(day,"precip_mm","мм")}\nВітер до ${value(day,"wind_max_kmh","км/год")} · хмарність ${value(day,"cloud_mean_pct","%")}\nСонячних годин: ${value(day,"sunshine_h","год")}")
   label(card,"Схід: ${day.optString("sunrise","—")}\nЗахід: ${day.optString("sunset","—")}",12f)
  }
  label(cards,"Параметри прогнозу",19f)
  label(cards,"${calibration.optString("model")}\nДнів навчання: ${calibration.optInt("sample_count")} · ${calibration.optString("note","")}",13f)
  label(cards,"Панелі: ${value(profile,"installed_kw","кВт")} · нахил ${value(profile,"tilt_deg","°")} · азимут ${value(profile,"azimuth_deg","°")}\nКоординати: ${location.optString("latitude")}, ${location.optString("longitude")}\nЧасовий пояс: ${result.optString("timezone")}",13f)
  AppStyle.apply(cards)
 }
 private fun editSettings() {
  val s=data.optJSONObject("settings") ?: JSONObject()
  val form=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL;setPadding(16.dp(),8.dp(),16.dp(),8.dp()) }
  val inputs=linkedMapOf<String,EditText>()
  for((key,title) in listOf("location" to "Населений пункт", "latitude" to "Широта (необов’язково)","longitude" to "Довгота (необов’язково)","installed_kw" to "Потужність панелей, кВт", "tilt_deg" to "Нахил, 0–90°", "azimuth_deg" to "Азимут: південь 180°, схід 90°")) {
   label(form,title,13f)
   inputs[key]=EditText(this).apply { setSingleLine();if(key!="location")inputType=InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_FLAG_DECIMAL or InputType.TYPE_NUMBER_FLAG_SIGNED;setText(if(s.has(key) && !s.isNull(key))s.optString(key) else "");form.addView(this) }
  }
  val message=label(form,"Параметри зберігаються лише в клієнті. Обидві координати можна залишити порожніми для пошуку міста.",12f)
  val import=button(form,"Прочитати параметри панелей із сервера") {}
  import.setOnClickListener {
   import.isEnabled=false
   worker.execute {
    try { val profile=ClientBridge.weatherProfile();runOnUiThread { if(!isDestroyed)for(key in listOf("installed_kw","tilt_deg","azimuth_deg"))inputs[key]?.setText(profile.optString(key)) } }
    catch(e:Exception) { runOnUiThread { message.text=e.message } }
    finally { runOnUiThread { import.isEnabled=true } }
   }
  }
  val dialog=ua.ducksolar.shared.LocalizedDialog.Builder(this).setTitle("Погода та панелі").setView(ScrollView(this).apply { addView(form) }).setPositiveButton("Зберегти",null).setNegativeButton("Скасувати",null).create()
  dialog.setOnShowListener {
   dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
    try {
     val value=JSONObject().put("location",inputs.getValue("location").text.toString().trim())
     for((key,field) in inputs)if(key!="location") {
      val text=field.text.toString().trim().replace(',','.')
      value.put(key,if(text.isEmpty() && key in listOf("latitude","longitude"))JSONObject.NULL else text.toDouble())
     }
     request { ClientBridge.weatherSettings(value) };dialog.dismiss()
    } catch(_:Exception) { message.text="Перевірте числа. Потужність, нахил та азимут обов’язкові." }
   }
  }
  AppStyle.apply(form);dialog.show()
 }
 private val tick=object:Runnable { override fun run() { if(!visible)return;request { ClientBridge.weatherStatus() };handler.postDelayed(this,2000) } }
 override fun onResume() { super.onResume();ClientLifecycle.enter();visible=true;handler.post(tick) }
 override fun onPause() {
  visible=false;handler.removeCallbacks(tick)
  worker.execute { try { ClientBridge.weatherCancel(true) } catch(_:Exception) {} }
  ClientLifecycle.leave();super.onPause()
 }
}
