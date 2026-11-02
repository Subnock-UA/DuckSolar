package ua.ducksolar.b2.client

import android.app.Activity
import android.app.AlertDialog
import android.app.DatePickerDialog
import android.app.TimePickerDialog
import android.widget.*
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.YearMonth
import java.time.format.DateTimeFormatter

/** Period anchors match the desktop selector: day, month, year, all. */
object PeriodPicker {
 // Framework picker delegates cache their Java formatters from Locale.default
 // during construction, even with localized resources. UI construction is on
 // the main thread; restore the previous process locale immediately afterwards.
 private fun <T> createUkrainianPicker(create:()->T):T {
  val previous=java.util.Locale.getDefault()
  return try { java.util.Locale.setDefault(java.util.Locale.forLanguageTag("uk-UA"));create() }
  finally { java.util.Locale.setDefault(previous) }
 }
 internal fun ukrainianContext(activity:Activity):android.content.Context {
  val locale=java.util.Locale.forLanguageTag("uk-UA")
  val configuration=android.content.res.Configuration(activity.resources.configuration)
  configuration.setLocales(android.os.LocaleList(locale));configuration.setLayoutDirection(locale)
  // Keep Activity's WindowManager/token while overriding only dialog resources.
  return android.view.ContextThemeWrapper(activity,R.style.DuckSolarTheme).apply { applyOverrideConfiguration(configuration) }
 }
 private val months=arrayOf("Січень","Лютий","Березень","Квітень","Травень","Червень","Липень","Серпень","Вересень","Жовтень","Листопад","Грудень")
 fun bind(activity:Activity,field:EditText,mode:()->String={"day"},withTime:Boolean=false) {
  field.isFocusable=false;field.isCursorVisible=false;field.contentDescription="Вибрати дату або період"
  field.setOnClickListener {
   val localized=ukrainianContext(activity)
   val kind=mode();if(kind=="all")return@setOnClickListener
   val day=try { if(field.text.length==7)YearMonth.parse(field.text.toString()).atDay(1) else LocalDate.parse(field.text.toString().take(10)) } catch(_:Exception) { LocalDate.now() }
   fun commit(chosen:LocalDate) {
    if(withTime) {
     val previous=try { LocalDateTime.parse(field.text.toString(),DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm")) } catch(_:Exception) { LocalDateTime.now() }
     createUkrainianPicker { TimePickerDialog(localized,{ _,h,m->field.setText(chosen.atTime(h,m).format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm"))) },previous.hour,previous.minute,true) }.apply { setTitle("Вибрати час");setButton(android.content.DialogInterface.BUTTON_POSITIVE,"Обрати",this);setButton(android.content.DialogInterface.BUTTON_NEGATIVE,"Скасувати",this) }.show()
    } else field.setText(if(field.text.length==7)YearMonth.from(chosen).toString() else chosen.toString())
   }
   if(kind=="day")createUkrainianPicker { DatePickerDialog(localized,{ _,y,m,d->commit(LocalDate.of(y,m+1,d)) },day.year,day.monthValue-1,day.dayOfMonth) }.apply {
    datePicker.firstDayOfWeek=java.util.Calendar.MONDAY
    setButton(android.content.DialogInterface.BUTTON_POSITIVE,"Обрати",this);setButton(android.content.DialogInterface.BUTTON_NEGATIVE,"Скасувати",this)
    datePicker.minDate=LocalDate.of(2010,1,1).atStartOfDay(java.time.ZoneId.systemDefault()).toInstant().toEpochMilli()
    datePicker.maxDate=LocalDate.of(2100,12,31).atStartOfDay(java.time.ZoneId.systemDefault()).toInstant().toEpochMilli()
   }.show()
   else {
    val body=LinearLayout(localized).apply { orientation=LinearLayout.HORIZONTAL;gravity=android.view.Gravity.CENTER;setPadding(24,12,24,12) }
    val year=NumberPicker(localized).apply { minValue=2010;maxValue=2100;value=day.year.coerceIn(2010,2100);body.addView(this) }
    val month=NumberPicker(localized).apply { minValue=1;maxValue=12;displayedValues=months;value=day.monthValue;if(kind=="month")body.addView(this) }
    ua.ducksolar.shared.LocalizedDialog.Builder(localized).setTitle(if(kind=="month")"Вибрати місяць" else "Вибрати рік").setView(body).setNegativeButton("Скасувати",null).setPositiveButton("Обрати") { _,_->commit(LocalDate.of(year.value,if(kind=="month")month.value else 1,1)) }.show()
   }
  }
 }
}
