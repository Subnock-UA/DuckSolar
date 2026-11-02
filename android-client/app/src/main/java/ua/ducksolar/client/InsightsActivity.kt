package ua.ducksolar.b2.client

import android.app.*
import android.os.*
import android.content.Intent
import android.graphics.Color
import android.widget.*
import org.json.*
import java.time.LocalDate
import java.util.Locale
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/** Period analytics use the existing asynchronous history queue, never UI calculations. */
class InsightsActivity:ua.ducksolar.shared.LocalizedActivity() {
 companion object { private val worker=Executors.newSingleThreadExecutor() }
 private lateinit var body:LinearLayout
 private lateinit var status:TextView
 private val handler=Handler(Looper.getMainLooper())
 private val pending=AtomicBoolean(false)
 private var visible=false
 private var historyRunning=false
 private var profileJob=""
 private var exportText=""
 private fun Int.dp()=(this*resources.displayMetrics.density).toInt()
 private fun text(parent:LinearLayout,value:String,size:Float=15f)=TextView(this).apply { text=DisplayText.clean(value);textSize=size;setPadding(0,8.dp(),0,8.dp());setTextIsSelectable(true);parent.addView(this) }
 private fun button(parent:LinearLayout,title:String,action:()->Unit)=Button(this).apply { text=title;parent.addView(this);setOnClickListener { action() } }
 private fun input(parent:LinearLayout,hint:String,value:String="")=EditText(this).apply { this.hint=hint;setSingleLine();setText(value);parent.addView(this) }
 private fun spinner(parent:LinearLayout,values:List<String>)=Spinner(this).apply { adapter=ArrayAdapter(this@InsightsActivity,android.R.layout.simple_spinner_dropdown_item,values);parent.addView(this) }
 private fun value(row:JSONObject,key:String,unit:String=""):String { val n=row.optDouble(key,Double.NaN);return DurationText.value(n,unit) ?: if(n.isFinite())String.format(Locale.getDefault(),"%.2f %s",n,unit) else "—" }
 private fun task(action:()->Unit) {
  if(!pending.compareAndSet(false,true)) { status.text="Попередній запит ще виконується";return }
  worker.execute { try { action() } catch(e:Exception) { runOnUiThread { if(!isDestroyed)status.text=e.message ?: "Запит не виконано" } } finally { pending.set(false) } }
 }
 private fun call(method:String,vararg args:Any)=ClientBridge.featureCall(method,JSONArray(args.toList()))
 override fun onCreate(saved:Bundle?) {
  super.onCreate(saved);window.statusBarColor=AppStyle.canvas;window.navigationBarColor=AppStyle.canvas;window.decorView.systemUiVisibility=ViewFlags.lightBars
  val root=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL;setPadding(20.dp(),8.dp(),20.dp(),8.dp());background=AppStyle.backdrop() };setContentView(root)
  root.setOnApplyWindowInsetsListener { _,i -> root.setPadding(20.dp()+i.systemWindowInsetLeft,8.dp()+i.systemWindowInsetTop,20.dp()+i.systemWindowInsetRight,8.dp()+i.systemWindowInsetBottom);i }
  button(root,"‹ Додатково") { finish() };status=text(root,"",13f)
  body=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL };root.addView(ScrollView(this).apply { addView(body) },LinearLayout.LayoutParams(-1,0,1f));AppStyle.watch(root)
  when(intent.getStringExtra("page") ?: "menu") {
   "battery"->battery(false);"battery_settings"->battery(true);"night"->nightCharge();"pv_correction"->pvCorrection();"profiles"->profiles();"commands"->commands();"forecast"->forecast()
   "forecast_stats"->dashboard("forecast_stats","Точність прогнозу");"forecast_live"->dashboard("forecast_live","Генерація сьогодні");"charge_plan"->dashboard("charge_plan","План нічного заряду");"battery_history"->period("battery")
   "calendar"->period("calendar");"compare"->period("compare");"report"->period("report");"forecast_actual"->period("forecast");"outages"->period("outages")
   else->{ text(body,"Аналітика станції",25f);for((title,page) in listOf("Відключення мережі" to "outages","Порівняння періодів" to "compare","Календар енергії" to "calendar","Добовий звіт" to "report","Прогноз і факт" to "forecast_actual"))button(body,title) { startActivity(Intent(this,InsightsActivity::class.java).putExtra("page",page)) } }
  }
  CompactSections.apply(body)
 }
 private val poll=object:Runnable {
  override fun run() {
   if(!visible)return
   if(historyRunning)task {
    val row=ClientBridge.featureStatus();runOnUiThread { if(!isDestroyed)when(row.optString("state")) {
     "complete"->{ historyRunning=false;status.text="Готово";renderResult(row.getJSONObject("result")) }
     "error"->{ historyRunning=false;status.text=row.optString("error") }
     else->status.text="Обробка на сервері…"
    } }
   }
   if(profileJob.isNotEmpty())task {
    val row=call("profile_status",profileJob) as JSONObject
    runOnUiThread { if(!isDestroyed) { status.text="Профіль: ${row.optString("status")} • ${row.optJSONArray("steps")?.length() ?: 0}/${row.optInt("total")} ${row.optString("error")}";if(row.optString("status")!="running")profileJob="" } }
   }
   handler.postDelayed(this,1000)
  }
 }
 private lateinit var resultBody:LinearLayout
 private fun period(kind:String) {
  text(body,when(kind) { "calendar"->"Календар енергії";"compare"->"Порівняння періодів";"outages"->"Відключення мережі";"battery"->"Історія АКБ";"forecast"->"Прогноз і факт";else->"Звіт за період" },25f)
  val mode=spinner(body,if(kind=="calendar")listOf("Місяць") else if(kind=="forecast")listOf("День") else listOf("День","Місяць"))
  val first=input(body,"Дата",intent.getStringExtra("date") ?: LocalDate.now(java.time.ZoneId.of("Europe/Kiev")).toString());PeriodPicker.bind(this,first,{if(kind=="calendar" || mode.selectedItemPosition==1)"month" else "day"})
  val second=if(kind=="compare")input(body,"Друга дата",LocalDate.now().minusDays(1).toString()).also { PeriodPicker.bind(this,it,{if(mode.selectedItemPosition==1)"month" else "day"}) } else null
  val metric=if(kind=="calendar" || kind=="compare")spinner(body,listOf("Генерація","Споживання","Імпорт","Експорт","Сальдо")) else null
  button(body,"Отримати дані") { if(!historyRunning)task { val fields=listOf("pv_w","output_w","grid_import_w","grid_export_w","saldo");ClientBridge.featureStart(kind,first.text.toString(),second?.text?.toString() ?: "",if(kind=="calendar" || mode.selectedItemPosition==1)"month" else "day",fields[metric?.selectedItemPosition ?: 0]);runOnUiThread { historyRunning=true;status.text="Запит прийнято…" } } }
  button(body,"Поділитися звітом") { if(exportText.isBlank())ua.ducksolar.shared.LocalizedToast.makeText(this,"Спочатку отримайте дані",Toast.LENGTH_SHORT).show() else startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT,exportText),"Звіт Duck Solar")) }
  resultBody=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL };body.addView(resultBody)
  resultBody.tag=metric
 }
 private fun summary(parent:LinearLayout,row:JSONObject,title:String,showNote:Boolean=true) {
  text(parent,title,19f)
  val metrics=listOf("generation" to "Генерація","consumption" to "Споживання","export" to "Експорт","import" to "Імпорт","balance" to "Сальдо")
  val coverage=metrics.map { row.optJSONObject(it.first)?.optDouble("coverage_seconds",Double.NaN) ?: Double.NaN }
  val common=coverage.all { it.isFinite() && kotlin.math.abs(it-coverage.first())<0.01 }
  for((key,label) in metrics) {
   val v=row.optJSONObject(key) ?: JSONObject()
   text(parent,"$label: ${value(v,"kwh","кВт·год")}"+if(common)"" else " • покриття ${value(JSONObject().put("hours",v.optDouble("coverage_seconds",0.0)/3600),"hours","год")}")
  }
  if(common)text(parent,"Покриття всіх показників: ${value(JSONObject().put("hours",coverage.first()/3600),"hours","год")}",13f)
  if(showNote)text(parent,"Графік і основні підсумки — межа інвертора. Неповні доби/місяці не порівнюються з повними без урахування покриття. За наявними даними інвертора. Пропуски не прирівнюються до нуля; імпорт/експорт успадковують джерело обліку.",12f)
 }
 private fun dashboard(kind:String,title:String) {
  text(body,title,25f)
  text(body,when(kind) { "forecast_stats"->"Збережені прогнози й фактична генерація за7/30діб. Плюс у відхиленні означає завищений прогноз.";"forecast_live"->"Оперативна оцінка враховує останню погоду та вже виміряну генерацію. Початковий прогноз залишається незмінним.";else->"Рекомендація за оцінкою АКБ, споживанням і нижнім прогнозом PV. Автовиконання окремо вмикається в нічному розкладі." },13f)
  button(body,"Оновити дані") { if(!historyRunning)task { ClientBridge.featureStart(kind,LocalDate.now(java.time.ZoneId.of("Europe/Kyiv")).toString());runOnUiThread { historyRunning=true;status.text="Запит прийнято…" } } }
  if(kind=="charge_plan")button(body,"Налаштувати автоматичний нічний заряд") { startActivity(Intent(this,InsightsActivity::class.java).putExtra("page","night")) }
  resultBody=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL };body.addView(resultBody)
 }
 private fun renderResult(row:JSONObject) {
  resultBody.removeAllViews()
  if(row.optString("note").isNotBlank())text(resultBody,row.optString("note"),13f)
  when(row.optString("kind")) {
   "forecast"->{
    val comparison=row.optJSONObject("comparison")
    if(comparison==null)text(resultBody,"Для погодинного порівняння оновіть сервер.\n"+row.optString("forecast_note"),15f)
    else {
     text(resultBody,"Дата: ${comparison.optString("day")}\nПрогноз на добу: ${value(comparison,"forecast_day_kwh","кВт·год")}\nПрогноз за порівнюваний час: ${value(comparison,"forecast_period_kwh","кВт·год")}\nВиміряно за наявними даними: ${value(comparison,"observed_kwh","кВт·год")}\nГодин з неповними даними: ${comparison.optInt("partial_hours")}\nФакт за порівнювані години: ${value(comparison,"actual_period_kwh","кВт·год")}\nВідхилення: ${value(comparison,"error_kwh","кВт·год")} / ${value(comparison,"error_pct","%")}\nГодин із достатніми даними: ${comparison.optInt("covered_hours")} із ${comparison.optInt("expected_hours")}\nПорівняння до: ${comparison.optString("period_end").replace('T',' ')}\nПрогноз видано: ${comparison.optString("issued_at").takeUnless { it=="null" || it.isBlank() } ?: "—"}",17f)
     text(resultBody,comparison.optString("note"),13f)
    }
   }
   "forecast_live"->{
    text(resultBody,"Виміряно: ${value(row,"actual_kwh","кВт·год")}\nОчікується до кінця дня: ${value(row,"remaining_kwh","кВт·год")}\nОперативний підсумок: ${value(row,"expected_total_kwh","кВт·год")}\nПочатковий прогноз: ${value(row,"original_kwh","кВт·год")}\nПокриття сонячного часу до зараз: ${value(row,"solar_coverage_pct","%")}\nПогода: ${row.optString("weather_updated")}",18f)
    val values=row.optJSONArray("hourly") ?: JSONArray();val points=JSONArray()
    for(i in 0 until values.length()) { val v=values.getJSONObject(i);points.put(JSONObject().put("x",java.time.OffsetDateTime.parse(v.getString("time")).toInstant().toEpochMilli()).put("label",v.getString("time")).put("forecast",v.optDouble("power_w"))) }
    if(!row.has("graph") && points.length()>0)resultBody.addView(GraphPlot(this,JSONObject().put("kind","line").put("mode","power").put("points",points).put("fields",JSONArray().put(JSONObject().put("key","forecast").put("label","Поточний прогноз PV").put("unit","Вт"))),mapOf("forecast" to AppStyle.accent),1.5f,220.dp()).body)
   }
   "forecast_stats"->{
    val windows=row.optJSONObject("windows") ?: JSONObject()
    for(count in listOf("7","30")) {
     text(resultBody,"За $count днів",20f);val groups=windows.optJSONArray(count) ?: JSONArray()
     if(groups.length()==0)text(resultBody,"Ще немає придатних пар прогноз/факт. Статистика накопичується з виданих прогнозів.",13f)
     for(i in 0 until groups.length()) { val v=groups.getJSONObject(i);text(resultBody,"Горизонт ${v.optInt("horizon")} дн. • ${v.optInt("samples")} діб\nСередня абсолютна похибка: ${value(v,"mae_kwh","кВт·год")} / ${value(v,"mae_pct","%")}\nСистематичне відхилення: ${value(v,"bias_kwh","кВт·год")}") }
    }
    text(resultBody,"Прогноз напередодні — по днях",18f);val values=row.optJSONArray("rows") ?: JSONArray()
    for(i in 0 until values.length()) { val v=values.getJSONObject(i);if(v.optInt("horizon")==1)text(resultBody,"${v.optString("day")} • прогноз ${value(v,"forecast_kwh")} / факт ${value(v,"actual_kwh")} кВт·год\nВідхилення ${value(v,"error_kwh","кВт·год")} / ${value(v,"error_pct","%")}",13f) }
    text(resultBody,"Виключено через недостатнє покриття: ${row.optJSONArray("excluded")?.length() ?: 0}",13f)
   }
   "charge_plan"->{
    if(!row.optBoolean("available"))text(resultBody,row.optString("fallback"),16f)
    else text(resultBody,"Ніч: ${row.optString("start")} → ${row.optString("end")}\nРекомендований ліміт: ${value(row,"recommended_a","А")} (межа ${value(row,"current_cap_a","А")})\nЦіль на ранок: ${value(row,"target_kwh","кВт·год")} / ${value(row,"target_pct","%")}\nОцінка на початок ночі: ${value(row,"estimated_start_kwh","кВт·год")}\nПотрібно додати: ${value(row,"needed_kwh","кВт·год")}\nСпоживання вдень: ${value(row,"day_load_kwh","кВт·год")}\nСпоживання вночі: ${value(row,"night_load_kwh","кВт·год")} • від АКБ ${value(row,"night_battery_share_pct","%")}\nНижня оцінка PV: ${value(row,"pv_low_kwh","кВт·год")}\nІсторія: ${row.optInt("history_days")} діб\n${if(row.optBoolean("can_reach_target"))"Часу й ліміту розрахунково достатньо" else "У межах ліміту можна не досягти цілі"}",17f)
   }
   "battery"->{
    val summary=row.optJSONObject("battery_summary") ?: JSONObject()
    text(resultBody,"Записів: ${summary.optInt("records")} • відомо ${value(summary,"known_hours","год")}\nМіж наявними точками: заряд ${value(summary,"charged_kwh","кВт·год")} / розряд ${value(summary,"discharged_kwh","кВт·год")}",15f)
    val graphs=row.optJSONArray("graphs") ?: JSONArray()
    for(i in 0 until graphs.length())resultBody.addView(GraphPlot(this,graphs.getJSONObject(i),mapOf("soc" to AppStyle.accent,"energy" to Color.rgb(224,158,37)),1.5f,190.dp()).body)
    val anchors=row.optJSONArray("anchors") ?: JSONArray()
    for(i in 0 until anchors.length()) { val v=anchors.getJSONObject(i);val at=java.time.Instant.ofEpochSecond(v.getDouble("at").toLong()).atZone(java.time.ZoneId.of("Europe/Kyiv"));text(resultBody,"$at • ${if(v.optString("source")=="automatic_full_charge")"Автоматична опора100%" else "Ручна опора100%"}",13f) }
   }
  }
  if(row.optString("kind")!="forecast") {
  row.optJSONObject("house_meter")?.let { HouseMeterView.add(this,resultBody,it,"Лічильник будинку") }
  row.optJSONObject("other_house_meter")?.let { HouseMeterView.add(this,resultBody,it,"Лічильник другого періоду") }
  if(row.optString("forecast_note").isNotBlank())text(resultBody,row.optString("forecast_note"),13f)
  row.optJSONObject("summary")?.let { summary(resultBody,it,row.optString("anchor")) }
  row.optJSONObject("other_summary")?.let { summary(resultBody,it,row.optString("other"),false) }
  }
  row.optJSONObject("graph")?.let { resultBody.addView(GraphPlot(this,it,mapOf("a" to AppStyle.accent,"b" to Color.rgb(224,158,37),"actual" to AppStyle.accent,"forecast" to Color.rgb(224,158,37)),1.5f,260.dp()).body);text(resultBody,it.optString("note"),12f) }
  row.optJSONArray("days")?.let { days ->
   val field=row.optString("metric","pv_w")
   val maximum=(0 until days.length()).map { days.getJSONObject(it).optDouble(field,Double.NaN) }.filter { it.isFinite() }.map { kotlin.math.abs(it) }.maxOrNull() ?: 1.0
   text(resultBody,"Пн       Вт       Ср       Чт       Пт       Сб       Нд",12f)
   val offset=LocalDate.parse(days.getJSONObject(0).getString("day")).dayOfWeek.value-1
   var index=-offset
   while(index<days.length()) {
    val line=LinearLayout(this);resultBody.addView(line)
    for(column in 0..6) {
     val item=index++;val cell=if(item in 0 until days.length())days.getJSONObject(item) else null
     val tile=TextView(this).apply { gravity=android.view.Gravity.CENTER;textSize=11f;setPadding(0,0,0,0);minWidth=0;minimumWidth=0;text=cell?.let { "${it.getString("day").takeLast(2)}\n${value(it,field)}${if((it.optJSONObject("coverage_seconds")?.optDouble(if(field=="saldo")"grid_import_w" else field,0.0) ?: 0.0)<82800)"*" else ""}" } ?: "";isEnabled=cell!=null }
     line.addView(tile,LinearLayout.LayoutParams(0,64.dp(),1f))
     val n=cell?.optDouble(field,Double.NaN) ?: Double.NaN
     tile.background=AppStyle.shape(this,if(!n.isFinite())Color.rgb(224,230,235) else if(n<0)Color.rgb(250,214,207) else Color.rgb(210-(100*n/maximum.coerceAtLeast(.001)).toInt().coerceIn(0,100),236,225),8)
     tile.setOnClickListener { cell?.let { startActivity(Intent(this,InsightsActivity::class.java).putExtra("page","report").putExtra("date",it.getString("day"))) } }
    }
   }
  }
  val outages=row.optJSONArray("outages") ?: JSONArray()
  if(row.optString("kind") in listOf("report","outages")) {
   text(resultBody,"Відключення мережі: ${outages.length()}",20f)
   for(i in 0 until outages.length()) {
    val outage=outages.getJSONObject(i);text(resultBody,"${outage.optString("start_iso")} → ${if(outage.isNull("end_iso"))"триває" else outage.optString("end_iso")}\n${value(JSONObject().put("m",outage.optDouble("duration_s")/60),"m","хв")} • SOC ${value(outage,"soc_start","%")} → ${value(outage,"soc_end","%")}\n${if(outage.optInt("uncertain")==1)"Є проміжки без даних; тривалість не повністю підтверджена" else "За підтвердженими станами мережі"}")
   }
   if(outages.length()==0)text(resultBody,"Зареєстрованих відключень немає. Облік розпочинається після цього оновлення.")
  }
  if(row.optString("kind")!="forecast") {
   row.optJSONArray("statistics")?.let { stats -> for(i in 0 until stats.length()) { val s=stats.getJSONObject(i);text(resultBody,"${s.optString("day")}: мін. SOC ${value(s,"min_soc","%")} • макс. навантаження ${value(s,"max_load","Вт")}") } }
   row.optJSONArray("events")?.let { events -> for(i in 0 until events.length()) { val e=events.getJSONObject(i);text(resultBody,e.optString("time")+" • "+e.optString("message"),13f) } }
   row.optJSONObject("forecast")?.let { text(resultBody,"Прогноз на дату: ${value(it,"expected_kwh","кВт·год")} • ${it.optString("basis")}\nПрогноз − факт: ${value(row,"forecast_error_kwh","кВт·год")} / ${value(row,"forecast_error_pct","%")} • сонячне покриття ${value(row,"solar_coverage_pct","%")}") }
  }
  exportText=buildString {
   append("Duck Solar • ${row.optString("anchor")} • ${row.optString("source","поточний облік")}\n")
   fun collect(view:android.view.View) { if(view is TextView && view !is Button)append(view.text).append('\n');if(view is android.view.ViewGroup)for(i in 0 until view.childCount)collect(view.getChildAt(i)) }
   collect(resultBody)
  }
 }
 private fun battery(settings:Boolean) {
  text(body,if(settings)"Параметри АКБ" else "Акумулятор і автономність",25f)
  val capacity=EditText(this);val reserve=EditText(this)
  if(settings)for((field,hint) in listOf(capacity to "Корисна ємність, кВт·год",reserve to "Резерв, %")) {
   field.hint=hint;field.setSingleLine();field.inputType=android.text.InputType.TYPE_CLASS_NUMBER or android.text.InputType.TYPE_NUMBER_FLAG_DECIMAL
  }
  if(!settings) {
   button(body,"Оновити") { task { val result=call("battery") as JSONObject;runOnUiThread { showBattery?.invoke(result) } } }
   button(body,"Історія АКБ") { startActivity(Intent(this,InsightsActivity::class.java).putExtra("page","battery_history")) }
  }
  if(settings)button(body,"Зберегти параметри") { task {
   fun n(field:EditText)=field.text.toString().replace(',','.').toDoubleOrNull() ?: throw IllegalArgumentException("Заповніть числові поля")
   call("battery_config",JSONObject().put("usable_kwh",n(capacity)).put("reserve_pct",n(reserve)))
   runOnUiThread { status.text="Параметри збережено" }
  } }
  val values=text(body,"")
  fun show(current:JSONObject) {
   val estimate=current.getJSONObject("estimate");val measured=current.getJSONObject("values")
   values.text="SOC БМС: ${value(measured,"soc","%")}\nЗалишок: ${value(estimate,"remaining_kwh","кВт·год")}\nПонад резерв: ${value(estimate,"available_kwh","кВт·год")}\nЗа поточним споживанням: ${value(estimate,"current_hours","год")}\nЗа середнім за 5 хв: ${value(estimate,"average_hours","год")}\n${estimate.optString("note")}"
  }
  showBattery=::show
  text(body,"SOC надходить від БМС через інвертор. Ємність і резерв використовуються для оцінки залишку енергії та автономності. За відсутності SOC розрахунковий заряд не підставляється.",13f)
  if(settings) { text(body,"Корисна ємність, кВт·год",14f);body.addView(capacity);text(body,"Резерв, %",14f);body.addView(reserve);values.visibility=android.view.View.GONE }
  task { val cfg=call("battery_config") as JSONObject;val result=if(settings)null else call("battery") as JSONObject;runOnUiThread {
   capacity.setText(cfg.optString("usable_kwh"));reserve.setText(cfg.optString("reserve_pct"));if(result!=null)show(result)
  } }
 }
 private var showBattery:((JSONObject)->Unit)?=null
 private fun nightCharge() {
  text(body,"Заряд по нічному тарифу",25f);text(body,"07:00–23:00 — лише сонце; 23:00–07:00 — сонце та мережа, час Києва. Вимкнення відновлює джерело та струм заряду, збережені перед увімкненням. Пов’язані ручні зміни заблоковані до завершення відновлення. Зміни розкладу застосовуються одразу.",13f)
  val enabled=Switch(this).apply { text="Автоматичний розклад";body.addView(this) }
  val adaptive=Switch(this).apply { text="Адаптивний нічний план (типово вимкнено)";body.addView(this) }
  val share=input(body,"Частка нічного споживання від АКБ, %","100").apply { inputType=android.text.InputType.TYPE_CLASS_NUMBER or android.text.InputType.TYPE_NUMBER_FLAG_DECIMAL }
  text(body,"0% — нічне навантаження живиться від мережі;100% — консервативно враховувати його повністю від АКБ. План застосовується на початку ночі та після редагування налаштувань режиму.",13f)
  val day=input(body,"Денний мережевий ліміт, А (джерело — лише сонце)","10");val night=input(body,"Нічний ліміт / максимум плану, А","60");val detail=text(body,"")
  for(v in listOf(day,night))v.inputType=android.text.InputType.TYPE_CLASS_NUMBER
  fun show(row:JSONObject) { val state=when(row.optString("status")) { "disabled"->"Вимкнено";"waiting"->"Очікування";"applying"->"Застосування";"planning"->"Підготовка нічного плану";"restoring"->"Відновлення початкових налаштувань";"applied"->"Застосовано й перевірено";"migration_required"->"Потрібне повторне ввімкнення";else->row.optString("status") };val source=when(row.optString("target_source")) { "2"->"Лише сонце";"1"->"Сонце та мережа";"0"->"Спочатку сонце";else->"—" };detail.text="Стан: $state • джерело: $source • цільовий ліміт ${value(row,"target_a","А")}\n${row.optString("error")}\n${row.optJSONObject("applied_plan")?.optString("note") ?: ""}" }
  fun save()=task {
   val values=JSONObject().put("enabled",enabled.isChecked).put("day_a",day.text.toString().toInt()).put("night_a",night.text.toString().toInt()).put("adaptive_enabled",adaptive.isChecked).put("night_battery_share_pct",share.text.toString().replace(',','.').toDouble())
   val row=call("night_charge",values) as JSONObject;runOnUiThread { show(row);status.text=if(row.optBoolean("restore_pending"))"Розпочато відновлення; оновіть стан для перевірки" else "Розклад збережено; перевірте стан застосування" }
  }
  button(body,"Зберегти розклад") { if(enabled.isChecked)ua.ducksolar.shared.LocalizedDialog.Builder(this).setTitle("Дозволити автоматичні зміни?").setMessage("Вдень — лише сонце (мережевий ліміт ${day.text} А), вночі — сонце та мережа, до ${night.text} А. ${if(adaptive.isChecked)"Адаптивний план увімкнено; за недостовірних даних застосовується фіксований нічний струм." else "Фіксований розклад."} Сервер одразу застосує поточний період. Вимкнення відновить початкові параметри; пов’язані ручні зміни під час роботи заблоковані. Загальний ліміт автоматично не підвищується.").setNegativeButton("Скасувати",null).setPositiveButton("Дозволити") { _,_->save() }.show() else save() }
  button(body,"Оновити стан") { task { val row=call("night_charge") as JSONObject;runOnUiThread { show(row) } } }
  task { val row=call("night_charge") as JSONObject;runOnUiThread { enabled.isChecked=row.optBoolean("enabled");adaptive.isChecked=row.optBoolean("adaptive_enabled");share.setText(row.optString("night_battery_share_pct","100"));day.setText(row.optString("day_a","10"));night.setText(row.optString("night_a","60"));show(row) } }
 }
 private fun pvCorrection() {
  text(body,"Коригування генерації PV",25f);text(body,"Спільна поправка головної, графіків і обліку. Початкові виміри зберігаються. Фізична точність коефіцієнта +2% не підтверджена незалежним еталоном.",13f)
  val factor=input(body,"Коефіцієнт, 1.02 = +2%");val noise=input(body,"Нічний нуль до, Вт (0 — вимкнено)");val lat=input(body,"Широта");val lon=input(body,"Довгота")
  text(body,"Нічний фільтр обнуляє лише малі покази при сонці нижче −6°. Без координат не застосовується. Денна слабка генерація зберігається.",13f)
  button(body,"Зберегти коригування PV") { task {
   fun n(v:EditText)=v.text.toString().replace(',','.').toDoubleOrNull()
   val row=call("pv_correction",JSONObject().put("pv_correction_factor",n(factor) ?: throw IllegalArgumentException("Задайте коефіцієнт")).put("pv_night_noise_w",n(noise) ?: 0).put("weather_latitude",n(lat) ?: JSONObject.NULL).put("weather_longitude",n(lon) ?: JSONObject.NULL))
   runOnUiThread { status.text="Збережено. Похідні підсумки оновляться за новою моделлю." }
  } }
  task { val row=call("pv_correction") as JSONObject;runOnUiThread { factor.setText(row.optString("pv_correction_factor"));noise.setText(row.optString("pv_night_noise_w"));lat.setText(if(row.isNull("weather_latitude"))"" else row.optString("weather_latitude"));lon.setText(if(row.isNull("weather_longitude"))"" else row.optString("weather_longitude")) } }
 }
 private fun commands() {
  text(body,"Історія налаштувань",25f);val rows=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL };body.addView(rows)
  button(body,"Оновити історію") { task { val entries=call("commands") as JSONArray;runOnUiThread { rows.removeAllViews();for(i in 0 until entries.length()) { val e=entries.getJSONObject(i);text(rows,"${e.optString("created")} • ${e.optString("parameter")}\n${e.optString("old")} → ${e.optString("new")}\n${CommandText.status(e)}") };if(entries.length()==0)text(rows,"Команд цього акаунта ще немає.") } } }
 }
 private fun profiles() {
  text(body,"Профілі налаштувань",25f);text(body,"Зберігаються лише параметри з відомими командами. Застосування — після перегляду змін, послідовно, з контрольним читанням. Профіль не керує невідомими параметрами.",13f)
  val name=input(body,"Назва профілю");val selection=spinner(body,emptyList());var names=emptyList<String>()
  fun list()=task { val profiles=call("profiles") as JSONObject;runOnUiThread { names=profiles.keys().asSequence().toList();selection.adapter=ArrayAdapter(this,android.R.layout.simple_spinner_dropdown_item,names) } }
  button(body,"Зберегти поточні налаштування") { task {
   val snapshot=ClientBridge.parameters();if(snapshot.optBoolean("stale",true))throw IllegalArgumentException("Перечитайте параметри інвертора")
   val rows=snapshot.getJSONArray("rows");val values=JSONObject();for(i in 0 until rows.length()) { val row=rows.getJSONObject(i);if(row.optBoolean("writable") && row.optBoolean("present"))values.put(row.getString("canonical_id"),row.get("raw_value")) }
   call("profiles",name.text.toString().trim(),values);runOnUiThread { status.text="Профіль збережено; оновіть список" }
  } }
  button(body,"Оновити список") { list() }
  button(body,"Переглянути й застосувати") { if(selection.selectedItemPosition in names.indices)task {
   val selected=names[selection.selectedItemPosition];val preview=call("preview_profile",selected) as JSONArray
   runOnUiThread { ua.ducksolar.shared.LocalizedDialog.Builder(this).setTitle(selected).setMessage(if(preview.length()==0)"Усі значення вже встановлені" else (0 until preview.length()).joinToString("\n") { val c=preview.getJSONObject(it);"${c.optString("parameter")}: ${c.optString("old")} → ${c.optString("new")}" }).setNegativeButton("Скасувати",null).setPositiveButton("Підтвердити виконання") { _,_->if(preview.length()>0)task { val job=call("apply_profile",selected,preview) as JSONObject;runOnUiThread { profileJob=job.getString("id") } } }.show() }
  } }
  button(body,"Видалити вибраний профіль") { if(selection.selectedItemPosition in names.indices) { val selected=names[selection.selectedItemPosition];ua.ducksolar.shared.LocalizedDialog.Builder(this).setMessage("Видалити профіль «$selected»?").setNegativeButton("Скасувати",null).setPositiveButton("Видалити") { _,_->task { call("delete_profile",selected);runOnUiThread { status.text="Видалено; оновіть список" } } }.show() } }
  button(body,"Відкрити параметри інвертора") { startActivity(Intent(this,ParameterActivity::class.java)) };list()
 }
 private fun forecast() {
  text(body,"Прогноз і планування",25f)
  for((title,page) in listOf("Генерація сьогодні: факт + залишок" to "forecast_live","Точність прогнозу за7/30днів" to "forecast_stats","План нічного заряду" to "charge_plan"))button(body,title) { startActivity(Intent(this,InsightsActivity::class.java).putExtra("page",page)) }
  val rows=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL };body.addView(rows)
  button(body,"Показати збережений прогноз") { task { val result=ClientBridge.weatherStatus().optJSONObject("result") ?: throw IllegalArgumentException("Спочатку оновіть прогноз погоди");runOnUiThread {
   rows.removeAllViews();val hourly=result.optJSONArray("hourly") ?: JSONArray();val today=LocalDate.now(java.time.ZoneId.of("Europe/Kiev")).toString();val now=java.time.Instant.now().epochSecond;var remaining=0.0
   val points=JSONArray();var best:JSONObject?=null
   for(i in 0 until hourly.length()) { val row=hourly.getJSONObject(i);if(row.optString("day")!=today)continue
    val at=java.time.OffsetDateTime.parse(row.getString("time")).toEpochSecond();if(at+3600>now)remaining+=row.optDouble("kwh")*((at+3600-now).coerceIn(0,3600))/3600
    if(at>=now && (best==null || row.optDouble("power_w")>best!!.optDouble("power_w")))best=row
    points.put(JSONObject().put("x",at.toDouble()*1000).put("label",row.getString("time")).put("forecast",row.optDouble("power_w")))
   }
   text(rows,"Очікується до кінця дня: ≈${String.format(Locale.getDefault(),"%.2f",remaining)}кВт·год\nНайкраща наступна година: ${best?.optString("time") ?: "—"}",19f)
   if(points.length()>0)rows.addView(GraphPlot(this,JSONObject().put("kind","line").put("points",points).put("fields",JSONArray().put(JSONObject().put("key","forecast").put("label","ПрогнозPV").put("unit","Вт"))),mapOf("forecast" to AppStyle.accent),1.5f,240.dp()).body)
   else text(rows,"Для погодинного прогнозу оновіть погоду після встановлення цього патча.")
   for(i in 0 until hourly.length()) { val row=hourly.getJSONObject(i);if(row.optString("day")==today)text(rows,"${row.optString("time")} • ${value(row,"power_w","Вт")} • ${value(row,"kwh","кВт·год")}",13f) }
   text(rows,"Прогноз є оцінкою. Порівняння з фактом і помилка доступні у звіті за завершений день зі збереженим напередодні прогнозом.",13f)
  } } }
  button(body,"Оновити прогноз у розділі погоди") { startActivity(Intent(this,WeatherActivity::class.java)) }
 }
 override fun onResume() { super.onResume();ClientLifecycle.enter();visible=true;handler.post(poll) }
 override fun onPause() { visible=false;handler.removeCallbacks(poll);ClientLifecycle.leave();super.onPause() }
 override fun onDestroy() { handler.removeCallbacksAndMessages(null);super.onDestroy() }
}
