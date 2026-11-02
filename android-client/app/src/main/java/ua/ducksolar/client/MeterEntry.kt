package ua.ducksolar.b2.client

import android.app.Activity
import android.app.AlertDialog
import android.text.InputType
import android.widget.*
import org.json.JSONObject
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import java.time.format.ResolverStyle
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

object MeterEntry {
 private val worker=Executors.newSingleThreadExecutor()
 private val saving=AtomicBoolean(false)
 private val format=DateTimeFormatter.ofPattern("uuuu-MM-dd HH:mm").withResolverStyle(ResolverStyle.STRICT)
 fun parse(stamp:String,values:List<String>):Pair<String,JSONObject> {
  val time=LocalDateTime.parse(stamp.trim(),format)
  require(values.size==4)
  val keys=listOf("import_day","import_night","export_day","export_night")
  val data=JSONObject()
  values.forEachIndexed { i,s ->
   val v=s.trim().replace(',','.').toDoubleOrNull()
   require(v!=null && v.isFinite() && v>=0) { "Заповніть усі чотири показники невід’ємними числами" }
   data.put(keys[i],v)
  }
  return time.toString() to data
 }
 fun show(activity:Activity) {
  if(saving.get()) { ua.ducksolar.shared.LocalizedToast.makeText(activity,"Попередні показники ще зберігаються",Toast.LENGTH_LONG).show();return }
  val body=LinearLayout(activity).apply { orientation=LinearLayout.VERTICAL;setPadding(24,12,24,12) }
  fun field(title:String,numeric:Boolean=false)=EditText(activity).apply {
   hint=title;setSingleLine();if(numeric)inputType=InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_FLAG_DECIMAL
   body.addView(this)
  }
  TextView(activity).apply { text="Накопичені показники поточного лічильника, кВт·год. Час — місцевий час сервера. Значення не підставляються автоматично.";setTextIsSelectable(true);body.addView(this) }
  val date=field("РРРР-ММ-ДД ГГ:ХХ")
  date.setText(LocalDateTime.now().format(format));PeriodPicker.bind(activity,date,withTime=true)
  val titles=listOf("Імпорт — день","Імпорт — ніч","Експорт — день","Експорт — ніч")
  val fields=titles.map { field(it,true) }
  val status=TextView(activity).apply { body.addView(this) }
  val scroll=ScrollView(activity).apply { addView(body) }
  val dialog=ua.ducksolar.shared.LocalizedDialog.Builder(activity).setTitle("Нові показники лічильника").setView(scroll).setNegativeButton("Скасувати",null).setPositiveButton("Перевірити",null).create()
  dialog.setOnShowListener { dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
   val parsed=try { parse(date.text.toString(),fields.map { it.text.toString() }) } catch(e:Exception) { status.text=e.message ?: "Перевірте дату та показники";return@setOnClickListener }
   val summary="Час: ${date.text}\n"+titles.mapIndexed { i,title -> "$title: ${fields[i].text} кВт·год" }.joinToString("\n")
   ua.ducksolar.shared.LocalizedDialog.Builder(activity).setTitle("Зберегти на сервері?").setMessage(summary).setNegativeButton("Назад",null).setPositiveButton("Зберегти") { _,_ ->
    if(!saving.compareAndSet(false,true))return@setPositiveButton
    dialog.getButton(AlertDialog.BUTTON_POSITIVE).isEnabled=false;status.text="Збереження…"
    worker.execute {
     val message=try { val result=ClientBridge.addMeterReading(parsed.first,parsed.second);"Збережено для лічильника №${result.optInt("meter_id")}" } catch(e:Exception) { "Не вдалося підтвердити збереження: ${e.message}\nПеревірте список показників перед повтором." }
     saving.set(false)
     activity.runOnUiThread { if(!activity.isDestroyed && !activity.isFinishing) { status.text=message;dialog.getButton(AlertDialog.BUTTON_POSITIVE).isEnabled=true } }
    }
   }.show()
  } }
  dialog.show()
 }
}
