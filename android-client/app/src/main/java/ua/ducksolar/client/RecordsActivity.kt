package ua.ducksolar.b2.client

import android.app.Activity
import android.os.Bundle
import android.graphics.Color
import android.widget.*
import org.json.JSONObject
import java.time.OffsetDateTime
import java.time.YearMonth
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

object RecordText {
 fun financeValue(record:JSONObject,key:String):String =
  if(key!="import_cost_uah" && record.optJSONObject("tariff")==null)"— (зелений тариф не заданий)"
  else value(record.optJSONObject("finance"),key,"грн")
 fun value(row:JSONObject?,key:String,unit:String):String {
  val v=if(row==null || row.isNull(key))Double.NaN else row.optDouble(key,Double.NaN)
  return DurationText.value(v,unit) ?: if(v.isFinite())String.format(Locale.getDefault(),"%.2f %s",v,unit) else "— (немає даних)"
 }
 fun event(row:JSONObject):String {
  // The older alias is available in Android 8's bundled timezone database too.
  val time=try { OffsetDateTime.parse(row.optString("time")).atZoneSameInstant(ZoneId.of("Europe/Kiev")).format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")) } catch(_:Exception) { row.optString("time") }
  return "$time • Київ\n${DisplayText.clean(row.optString("message"))}"+"\n${row.optString("device_id")} • ${row.optString("code")}" 
 }
}

class RecordsActivity:ua.ducksolar.shared.LocalizedActivity() {
 companion object { private val worker=Executors.newSingleThreadExecutor() }
 private val pending=AtomicBoolean(false)
 private var page="events"
 private var generation=0
 private lateinit var content:LinearLayout
 private var monthText=YearMonth.now().toString()
 override fun onCreate(state:Bundle?) {
  super.onCreate(state);page=state?.getString("page") ?: intent.getStringExtra("page") ?: "events"
  window.statusBarColor=Color.rgb(244,247,249);window.navigationBarColor=Color.rgb(244,247,249)
  window.decorView.systemUiVisibility=ViewFlags.lightBars
  monthText=state?.getString("month") ?: monthText
  val root=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL;setPadding(20,8,20,12);background=AppStyle.backdrop() }
  setContentView(root)
  root.setOnApplyWindowInsetsListener { _,i -> root.setPadding(20+i.systemWindowInsetLeft,8+i.systemWindowInsetTop,20+i.systemWindowInsetRight,12+i.systemWindowInsetBottom);i }
  val nav=LinearLayout(this);root.addView(nav)
  Button(this).apply {
   text="‹ Додатково";isAllCaps=false;nav.addView(this,LinearLayout.LayoutParams(-1,52.dp()))
   setOnClickListener { finish() }
  }
  AppStyle.apply(nav)
  content=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL }
  root.addView(ScrollView(this).apply { addView(content) },LinearLayout.LayoutParams(-1,0,1f));showPage()
 }
 private fun Int.dp()=(this*resources.displayMetrics.density).toInt()
 private fun label(parent:LinearLayout,value:String,size:Float=16f)=TextView(this).apply { text=value;textSize=size;setTextColor(Color.rgb(38,54,65));setPadding(0,10.dp(),0,10.dp());setTextIsSelectable(true);parent.addView(this) }
 private fun showPage() {
  content.post { CompactSections.apply(content);AppStyle.apply(content) }
  generation++;content.removeAllViews();val selected=generation
  if(page=="events") {
   label(content,"Події інвертора",24f);label(content,"Останні 100 подій сервера, нові зверху. Опис подій залежить від даних інвертора.",14f)
   val status=label(content,"Натисніть «Оновити події».",14f)
   val button=Button(this).apply { text="Оновити події";content.addView(this) }
   val rows=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL;content.addView(this) }
   button.setOnClickListener {
    if(!pending.compareAndSet(false,true)) { status.text="Попередній запит ще виконується";return@setOnClickListener }
    button.isEnabled=false;status.text="Завантаження…"
    worker.execute {
     try {
      val data=ClientBridge.events()
      runOnUiThread { if(current(selected)) { rows.removeAllViews();for(i in 0 until data.length()) {
        val item=data.getJSONObject(i)
        label(rows,RecordText.event(item),14f).setOnClickListener {
         val d=item.optJSONObject("event_detail")
         val detail=if(d==null)"Час: ${item.optString("time")}\nКод: ${item.optString("code")}" else "${d.optString("status")}\nПерша поява у доступному журналі: ${if(d.isNull("first_seen"))"—" else d.optString("first_seen")}\nОстанній запис: ${d.optString("last_seen","—")}\nЗавершення: ${if(d.isNull("ended"))"—" else d.optString("ended")}\nТривалість: ${if(d.isNull("duration_s"))"невідома" else DurationText.seconds(d.optDouble("duration_s",Double.NaN))}\n"+if(d.optBoolean("start_confirmed"))"Початок зафіксовано" else "Фактичний початок може бути раніше доступного журналу"
         ua.ducksolar.shared.LocalizedDialog.Builder(this).setTitle("Подія інвертора").setMessage(DisplayText.clean(item.optString("message"))+"\n\n"+detail).setPositiveButton("Закрити",null).show()
        }
       };status.text=if(data.length()==0)"Подій поки немає" else "Показано ${data.length()} останніх подій" } }
     } catch(e:Exception) { runOnUiThread { if(current(selected))status.text=e.message ?: "Події недоступні" } }
     finally { pending.set(false);runOnUiThread { if(current(selected))button.isEnabled=true } }
    }
   }
  } else if(page=="history") {
   label(content,"Наявна історія",24f)
   label(content,"Дати, які знаходить сервер у сховищі історії. Повноту записів і джерело Local, SmartESS або Auto перевіряйте у місячному балансі.",14f)
   val status=label(content,"Натисніть «Перевірити історію».",14f)
   val button=Button(this).apply { text="Перевірити історію";content.addView(this) }
   val rows=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL;content.addView(this) }
   button.setOnClickListener {
    if(!pending.compareAndSet(false,true)) { status.text="Попередній запит ще виконується";return@setOnClickListener }
    button.isEnabled=false;status.text="Перевірка…"
    worker.execute {
     try {
      val result=ClientBridge.historyDates()
      runOnUiThread { if(current(selected)) {
       rows.removeAllViews()
       status.text=if(result.optInt("count")==0)"Сервер не знайшов дат історії" else "Днів: ${result.optInt("count")}\nПерша дата: ${result.optString("first")} • остання: ${result.optString("last")}"
       val dates=result.getJSONArray("dates");if(dates.length()>0)label(rows,"Останні ${dates.length()} дат",18f)
       for(i in 0 until dates.length())label(rows,dates.getString(i),14f)
      } }
     } catch(e:Exception) { runOnUiThread { if(current(selected))status.text=e.message ?: "Історія недоступна" } }
     finally { pending.set(false);runOnUiThread { if(current(selected))button.isEnabled=true } }
    }
   }
  } else if(page=="tariff") {
   label(content,"Зелений тариф",24f)
   label(content,"Офіційні дані НКРЕКП для категорії, налаштованої на сервері. Ручні ставки зберігаються.",14f)
   val status=label(content,"Натисніть, щоб переглянути збережені дані.",16f)
   val history=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL }
   fun load(check:Boolean) {
    if(!pending.compareAndSet(false,true))return
    status.text=if(check)"Перевіряємо офіційне джерело…" else "Завантаження…"
    worker.execute {
     try { val data=if(check)ClientBridge.tariffCheck() else ClientBridge.tariffStatus()
      runOnUiThread { if(current(selected)) {
       status.text=if(data.optString("state")=="error")"Остання перевірка неуспішна: ${data.optString("error")}\nЗбережені ставки залишаються чинними."
        else if(!data.has("effective_from"))"Офіційне джерело ще не перевірено. Збережені ставки показані нижче."
        else "Чинність: ${data.optString("effective_from")}\nОфіційна ставка: ${RecordText.value(data,"rate_uah","грн/кВт·год")}\nПостанова №${data.optString("resolution_number")} від ${data.optString("resolution_date")}\n${if(data.optBoolean("manual_override"))"Для розрахунків збережено ручну ставку" else "Офіційні дані"}\nПеревірено: ${data.optString("checked_at")}\n${data.optString("source_url")}"
       history.removeAllViews();label(history,"Історія ставок",20f)
       val saved=data.optJSONArray("history")
       if(saved==null || saved.length()==0)label(history,"Збережених ставок немає. Дохід без ставки не визначається.",14f)
       else for(i in saved.length()-1 downTo 0) {
        val row=saved.getJSONObject(i)
        label(history,"З ${row.optString("effective_from")}: ${RecordText.value(row,"uah_per_kwh","грн/кВт·год")}\n"+
         if(row.optBoolean("user_override") || row.optInt("user_override")==1)"Ручна ставка" else "${row.optString("source")} · постанова №${row.optString("resolution_number")} від ${row.optString("resolution_date")}",14f)
       }
      } }
     } catch(e:Exception) { runOnUiThread { if(current(selected))status.text=e.message ?: "Немає зв’язку із сервером" } }
     finally { pending.set(false) }
    }
   }
   Button(this).apply { text="Показати збережений тариф";content.addView(this);setOnClickListener { load(false) } }
   Button(this).apply { text="Перевірити НКРЕКП";content.addView(this);setOnClickListener { load(true) } }
   content.addView(history)
   load(false)
  } else {
   content.post { CompactSections.apply(content);AppStyle.apply(content) }
   label(content,"Фінанси будинку",24f);label(content,"Розрахунок сервера за показниками лічильника будинку. Облік інвертора показаний окремо у балансі.",14f)
   val month=EditText(this).apply { setSingleLine();hint="РРРР-ММ";setText(monthText);content.addView(this) }
   PeriodPicker.bind(this,month,{"month"})
   val status=label(content,"Оберіть місяць.",14f)
   val button=Button(this).apply { text="Отримати фінанси";content.addView(this) }
   val rows=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL;content.addView(this) }
   button.setOnClickListener {
    val chosen=try { YearMonth.parse(month.text.toString().trim()).toString() } catch(_:Exception) { status.text="Вкажіть місяць як 2026-10";return@setOnClickListener }
    if(!pending.compareAndSet(false,true)) { status.text="Попередній запит ще виконується";return@setOnClickListener }
    monthText=chosen;button.isEnabled=false;month.isEnabled=false;status.text="Завантаження…"
    worker.execute {
     try {
      val data=ClientBridge.financeMonth(chosen)
      runOnUiThread { if(current(selected)) {
       rows.removeAllViews();val record=data.optJSONObject("selected")
       if(record==null)status.text="За $chosen немає достатніх показників лічильника для розрахунку. Це не нульовий дохід."
       else {
        status.text="Місяць $chosen • розраховано сервером"
        val delta=record.optJSONObject("delta");val finance=record.optJSONObject("finance")
        label(rows,"Період обліку: ${delta?.optString("period_start")} — ${delta?.optString("period_end")}",14f)
        if(delta?.optBoolean("interim")==true)label(rows,"Поточний місяць: проміжний результат",14f)
        if(delta?.optBoolean("boundary_adjusted")==true)label(rows,"Межі обліку скориговані за наявними показниками",14f)
        label(rows,EnergySaldo.financeLabel(record),19f)
        label(rows,"Сальдо коштів після податків: "+EnergySaldo.money(record),19f)
        val details=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL;visibility=android.view.View.GONE }
        Button(this).apply { text="Показати розрахунок і тарифи";rows.addView(this);setOnClickListener { val open=details.visibility!=android.view.View.VISIBLE;details.visibility=if(open)android.view.View.VISIBLE else android.view.View.GONE;text=if(open)"Сховати розрахунок і тарифи" else "Показати розрахунок і тарифи" } }
        rows.addView(details)
        for((key,title) in listOf("import_day_kwh" to "Імпорт — день","import_night_kwh" to "Імпорт — ніч","export_day_kwh" to "Експорт — день","export_night_kwh" to "Експорт — ніч","sale_kwh" to "Надлишок до продажу"))label(details,"$title: ${RecordText.value(finance,key,"кВт·год")}")
        val tariff=record.optJSONObject("tariff");val rates=record.optJSONObject("rates")
        label(details,"Розраховані суми",20f)
        if(tariff==null)label(details,"Зелений тариф не заданий на сервері: нарахування за продаж та пов’язані податки не визначені.",14f)
        for((key,title) in listOf("import_cost_uah" to "Вартість споживання","green_gross_uah" to "Нарахування до податків","personal_income_tax_uah" to "ПДФО","military_tax_uah" to "Військовий збір","green_net_uah" to "Нарахування після податків"))label(details,"$title: ${RecordText.financeValue(record,key)}")
        if(tariff==null)label(details,"Зелений тариф: —",14f)
        else label(details,"Зелений тариф: ${RecordText.value(tariff,"uah_per_kwh","грн/кВт·год")}",14f)
        label(details,"Денний тариф: ${RecordText.value(rates,"retail_day_tariff_uah","грн/кВт·год")}\nПДФО: ${RecordText.value(rates,"pit_pct","%")} • військовий збір: ${RecordText.value(rates,"military_pct","%")}",14f)
       }
      } }
     } catch(e:Exception) { runOnUiThread { if(current(selected))status.text=e.message ?: "Фінанси недоступні" } }
     finally { pending.set(false);runOnUiThread { if(current(selected)) { button.isEnabled=true;month.isEnabled=true } } }
    }
   }
  }
 }
 private fun current(id:Int)=!isDestroyed && !isFinishing && generation==id
 override fun onResume() { super.onResume();ClientLifecycle.enter() }
 override fun onPause() { ClientLifecycle.leave();super.onPause() }
 override fun onSaveInstanceState(out:Bundle) { out.putString("page",page);out.putString("month",monthText);super.onSaveInstanceState(out) }
 override fun onDestroy() { generation++;super.onDestroy() }
}
