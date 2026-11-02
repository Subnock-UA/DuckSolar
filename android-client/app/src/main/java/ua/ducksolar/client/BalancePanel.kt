package ua.ducksolar.b2.client

import android.app.Activity
import android.graphics.Color
import android.widget.*
import org.json.JSONObject
import java.time.YearMonth
import java.util.Locale
import java.util.concurrent.Executors

object BalanceText {
 fun energy(row:JSONObject?):String {
  if(row==null || row.isNull("kwh"))return "— (немає даних)"
  val value=row.optDouble("kwh",Double.NaN)
  if(!value.isFinite())return "— (некоректні дані)"
  val estimated=row.optDouble("estimated_pct",0.0)>0
  return String.format(Locale.getDefault(),"%.3f кВт·год",value)+(if(estimated)" (розрах.)" else "")
 }
 fun coverage(row:JSONObject?):String = if(row==null)"Покриття: —" else
  String.format(Locale.getDefault(),"Покриття %.1f%% • розраховане %.1f%% • відсутнє %.1f%%",row.optDouble("coverage_pct",0.0),row.optDouble("estimated_pct",0.0),row.optDouble("missing_pct",100.0))
 fun day(row:JSONObject):String = row.optString("date")+"\nPV: "+energy(row.optJSONObject("pv"))+"\n"+coverage(row.optJSONObject("pv"))+"\nІмпорт: "+energy(row.optJSONObject("inverter_import"))+"\n"+coverage(row.optJSONObject("inverter_import"))+"\nЕкспорт: "+energy(row.optJSONObject("inverter_export"))+"\n"+coverage(row.optJSONObject("inverter_export"))
}

object BalancePanel {
 private val worker=Executors.newSingleThreadExecutor()
 fun attach(activity:Activity,parent:LinearLayout,includeMeters:Boolean=true,title:String="Місячний баланс"):BalanceController {
  fun text(value:String,size:Float=16f)=TextView(activity).apply {
   text=value;textSize=size;setTextColor(Color.rgb(38,54,65));setPadding(0,12,0,12);setTextIsSelectable(true);parent.addView(this)
  }
  parent.post { AppStyle.apply(parent) }
  text(title,22f)
  text("Енергія на стороні інвертора. Оберіть місяць у календарі.",14f)
  val preferences=activity.getSharedPreferences("BalancePeriod",Activity.MODE_PRIVATE)
  val month=EditText(activity).apply { setSingleLine();setText(preferences.getString("month",YearMonth.now().toString()));parent.addView(this) }
  month.addTextChangedListener(object:android.text.TextWatcher { override fun beforeTextChanged(s:CharSequence?,start:Int,count:Int,after:Int){};override fun onTextChanged(s:CharSequence?,start:Int,before:Int,count:Int){ preferences.edit().putString("month",s.toString()).apply() };override fun afterTextChanged(s:android.text.Editable?){} })
  PeriodPicker.bind(activity,month,{"month"})
  val sources=listOf("Local","SmartESS","Auto")
  val source=Spinner(activity).apply {
   adapter=ArrayAdapter(activity,android.R.layout.simple_spinner_dropdown_item,listOf("Local — локальні журнали","SmartESS — історія ESS","Auto — Local із доповненням ESS"));parent.addView(this)
  }
  text("Auto доповнює проміжки історією ESS. Джерело та покриття показані в результаті.",13f)
  val status=text("Оберіть місяць і натисніть «Оновити».",14f)
  val warning=text("",14f).apply { visibility=android.view.View.GONE }
  val button=Button(activity).apply { text="Оновити баланс";parent.addView(this) }
  val cancel=Button(activity).apply { text="Скасувати розрахунок";isEnabled=false;visibility=android.view.View.GONE;parent.addView(this) }
  val results=LinearLayout(activity).apply { orientation=LinearLayout.VERTICAL;parent.addView(this) }
  var renderedQuery=""
  var activeQuery=""
  val controller=BalanceController(activity) { job ->
   val state=job.optString("state");val working=state=="running" || state=="cancelling" || job.optBoolean("active")
   button.isEnabled=!working;month.isEnabled=!working;source.isEnabled=!working;cancel.isEnabled=state=="running"
   cancel.visibility=if(working)android.view.View.VISIBLE else android.view.View.GONE
   if(working && activeQuery!=job.optString("query_id")) { activeQuery=job.optString("query_id");results.removeAllViews();month.setText(job.optString("month"));source.setSelection(sources.indexOf(job.optString("source","Local")).coerceAtLeast(0)) }
   if(state!="complete")warning.visibility=android.view.View.GONE
   if(state in listOf("error","cancelled")) { results.removeAllViews();renderedQuery="" }
   when(state) {
    "running" -> status.text="Баланс ${job.optString("month")} • ${job.optString("source","Local")} • очікування ${DurationText.seconds(job.optDouble("elapsed_s",Double.NaN))}\n${AppStyle.job(job)}"
    "cancelling" -> status.text="Очікуємо завершення скасування…"
    "cancelled" -> status.text="Розрахунок скасовано. Можна обрати інший місяць."
    "error" -> status.text="Не вдалося отримати баланс: ${job.optString("error")}\nАвтоматичного повтору немає."
    "complete" -> if(renderedQuery!=job.optString("query_id")) {
     renderedQuery=job.optString("query_id");month.setText(job.optString("month"));results.removeAllViews()
     val report=job.getJSONObject("report");val days=report.getJSONArray("days")
     source.setSelection(sources.indexOf(job.optString("source","Local")).coerceAtLeast(0))
       fun result(value:String,size:Float=16f)=TextView(activity).apply { text=value;textSize=size;setTextColor(Color.rgb(38,54,65));setPadding(0,12,0,12);setTextIsSelectable(true);results.addView(this) }
       for((key,title) in listOf("pv" to "Сонячна генерація","inverter_import" to "З мережі до інвертора","inverter_export" to "З інвертора в мережу")) {
        val row=report.optJSONObject(key);result(title,19f);result(BalanceText.energy(row));result(BalanceText.coverage(row),13f)
       }
       result(EnergySaldo.inverter(report),19f)
       report.optJSONObject("house_meter")?.let { HouseMeterView.add(activity,results,it) }
       result(report.optString("quality_note"),13f)
       val method=when { report.optBoolean("cache_hit")->"збережений розрахунок";report.optBoolean("incremental")->"додано нові дані";else->"розраховано сервером" }
       status.text="Місяць ${job.optString("month")} • "+"отримано за "+DurationText.seconds(job.optDouble("elapsed_s",Double.NaN))+" • "+method
       val timing=report.optJSONObject("diagnostics")?.optDouble("total_s",Double.NaN) ?: Double.NaN
       if(timing.isFinite())status.append(" • сервер "+DurationText.seconds(timing))
       result("Період: ${report.optString("start").take(16)} — ${report.optString("end").take(16)}",13f)

     val diagnostic=report.optJSONObject("diagnostics")
       result("Джерело: ${report.optString("history_source",job.optString("source","Local"))}",16f)
       val available=diagnostic?.optJSONObject("available_files_by_source")
       if(available!=null)result("Файлів за період: Local ${available.optInt("Local")} • SmartESS ${available.optInt("SmartESS")}",13f)
       val sourceNote=diagnostic?.optString("source_note","") ?: ""
       if(sourceNote.isNotBlank())result(sourceNote,13f)
     val records=diagnostic?.optLong("read_records",-1) ?: -1
     if(diagnostic?.optInt("selected_files",-1)==0) {
      warning.text="За цей місяць сервер не знайшов файлів історії. Це не підтверджений нульовий баланс.";warning.visibility=android.view.View.VISIBLE
     } else warning.visibility=android.view.View.GONE
     if(records>=0 && !report.optBoolean("cache_hit"))result("Прочитано записів: $records • файлів: ${diagnostic?.optInt("opened_files",0)}",13f)
    }
   }
  }
  button.setOnClickListener {
   val selected=try { YearMonth.parse(month.text.toString().trim()).toString() } catch(_:Exception) { status.text="Вкажіть місяць як 2026-10";return@setOnClickListener }
   controller.start(selected,sources[source.selectedItemPosition])
  }
  cancel.setOnClickListener { controller.cancel() }
  if(includeMeters)attachMeters(activity,parent)
  return controller
 }
 fun attachMeters(activity:Activity,parent:LinearLayout) {
  fun text(value:String,size:Float=16f)=TextView(activity).apply { text=value;textSize=size;setTextColor(Color.rgb(38,54,65));setPadding(0,12,0,12);setTextIsSelectable(true);parent.addView(this) }
  text("Показники лічильників",21f)
  val meterStatus=text("Показники збережені на підключеному сервері.",13f)
  val meterRows=LinearLayout(activity).apply { orientation=LinearLayout.VERTICAL;parent.addView(this) }
  Button(activity).apply { text="Додати показники лічильника";parent.addView(this);setOnClickListener { MeterEntry.show(activity) } }
  val meterButton=Button(activity).apply { text="Показати останні показники";parent.addView(this) }
  meterButton.setOnClickListener {
   meterButton.isEnabled=false;meterStatus.text="Завантаження показників…"
   worker.execute {
    try {
     val rows=ClientBridge.meterReadings()
     activity.runOnUiThread { if(!activity.isDestroyed && !activity.isFinishing) {
      meterRows.removeAllViews()
      for(i in 0 until rows.length()) {
       val r=rows.getJSONObject(i)
       TextView(activity).apply {
        text="Лічильник №${r.optInt("meter_id")} • ${r.optString("reading_date")}\n"+
         "Імпорт: день ${r.optDouble("import_day")} / ніч ${r.optDouble("import_night")} кВт·год\n"+
         "Експорт: день ${r.optDouble("export_day")} / ніч ${r.optDouble("export_night")} кВт·год"
        textSize=14f;setPadding(0,12,0,16);setTextIsSelectable(true);meterRows.addView(this)
       }
      }
      meterStatus.text="Останні ${rows.length()} записів (до 200)";meterButton.isEnabled=true
     } }
    } catch(error:Exception) { activity.runOnUiThread { if(!activity.isDestroyed) { meterStatus.text=error.message ?: "Не вдалося отримати показники";meterButton.isEnabled=true } } }
   }
  }
 }
}
