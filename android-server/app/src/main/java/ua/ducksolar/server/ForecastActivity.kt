package ua.ducksolar.b2.server

import android.app.Activity
import android.os.*
import android.widget.*
import org.json.JSONObject
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

class ForecastActivity:ua.ducksolar.shared.LocalizedActivity() {
 private val worker=Executors.newSingleThreadExecutor()
 private val handler=Handler(Looper.getMainLooper())
 private val busy=AtomicBoolean(false)
 private lateinit var state:TextView
 private lateinit var root:LinearLayout
 private val inputs=linkedMapOf<String,EditText>()
 private var device=""
 private var loaded=false
 private lateinit var start:Button
 private lateinit var cancel:Button
 private val tick=object:Runnable { override fun run() { request { Bridge.forecastStatus(device) };handler.postDelayed(this,3000) } }
 override fun onCreate(savedInstanceState:Bundle?) {
  super.onCreate(savedInstanceState)
  root=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL;setPadding(24,24,24,24);setBackgroundColor(AppStyle.canvas) }
  setContentView(ScrollView(this).apply { addView(root) })
  fun label(s:String,size:Float=15f)=TextView(this).apply { text=s;textSize=size;root.addView(this) }
  Button(this).apply { text="‹ До сервера";root.addView(this);setOnClickListener { finish() } }
  label("Навчання прогнозу",25f)
  label("Примусовий запуск обходить тільки очікування зарядки й черги історії. Зберігаються покриття ≥95% сонячного часу, мінімум 6 валідних діб і всі перевірки якості. Інвертор не переналаштовується.")
  state=label("Завантаження стану…")
  for((key,title) in listOf("location" to "Населений пункт","installed_kw" to "Панелі, кВт","tilt_deg" to "Нахил, °","azimuth_deg" to "Азимут, °","latitude" to "Широта (необов’язково)","longitude" to "Довгота (необов’язково)")) {
   label(title,13f)
   inputs[key]=EditText(this).apply { setSingleLine();hint=title;inputType=if(key=="location")android.text.InputType.TYPE_CLASS_TEXT else android.text.InputType.TYPE_CLASS_NUMBER or android.text.InputType.TYPE_NUMBER_FLAG_DECIMAL or android.text.InputType.TYPE_NUMBER_FLAG_SIGNED;root.addView(this) }
  }
  start=Button(this).apply { text="Навчити зараз • без очікування";root.addView(this);setOnClickListener {
   val values=JSONObject()
   try {
    for((key,field) in inputs) {
     val raw=field.text.toString().trim()
     values.put(key,if(key=="location")raw else if(raw.isBlank() && key in listOf("latitude","longitude"))JSONObject.NULL else raw.replace(',','.').toDoubleOrNull() ?: throw IllegalArgumentException("Перевірте поле: $key"))
    }
    request { Bridge.forecastTrain(values,true,device) }
   } catch(error:Exception) { state.text=error.message }
  } }
  cancel=Button(this).apply { text="Скасувати навчання";root.addView(this);setOnClickListener { request { Bridge.forecastCancel(device) } } }
  root.post { CompactSections.apply(root);AppStyle.apply(root) }
 }
 private fun request(action:()->JSONObject) {
  if(!busy.compareAndSet(false,true))return
  worker.execute {
   try { val result=action();runOnUiThread { if(!isDestroyed)render(result) } }
   catch(error:Exception) { runOnUiThread { if(!isDestroyed)state.text=error.message ?: "Помилка навчання" } }
   finally { busy.set(false) }
  }
 }
 private fun render(job:JSONObject) {
  if(job.has("device_id"))device=job.getString("device_id")
  if(!loaded && job.has("settings")) { val settings=job.getJSONObject("settings");for((key,field) in inputs)field.setText(if(settings.isNull(key))"" else settings.optString(key));loaded=true }
  val running=job.optString("state")=="running"
  start.isEnabled=loaded && !running;cancel.isEnabled=running
  val calibration=job.optJSONObject("result")?.optJSONObject("calibration")
  val count=calibration?.optInt("sample_count",0) ?: 0
  val phase=when(job.optString("phase")) { "history"->"Підготовка історії: ${job.optInt("server_done")} / ${job.optInt("server_total")}";"training_weather"->"Отримання архіву погоди";"forecast"->"Розрахунок прогнозу";"location"->"Визначення координат";else->"Виконується…" }
  state.text="${job.optString("device_name",device)}\n${if(running)phase else if(count>0)"Навчено: $count діб" else "Ще не навчено"}\n${job.optString("training_note")}\n${job.optString("error",calibration?.optString("note","") ?: "")}"
 }
 override fun onResume() { super.onResume();handler.post(tick) }
 override fun onPause() { handler.removeCallbacks(tick);super.onPause() }
 override fun onDestroy() { worker.shutdown();super.onDestroy() }
}
