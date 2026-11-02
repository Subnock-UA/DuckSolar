package ua.ducksolar.b2.server

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
 private val months=arrayOf("Січень","Лютий","Березень","Квітень","Травень","Червень","Липень","Серпень","Вересень","Жовтень","Листопад","Грудень")
 fun bind(activity:Activity,field:EditText,mode:()->String={"day"},withTime:Boolean=false) {
  field.isFocusable=false;field.isCursorVisible=false;field.contentDescription="Вибрати дату або період"
  field.setOnClickListener {
   val kind=mode();if(kind=="all")return@setOnClickListener
   val day=try { if(field.text.length==7)YearMonth.parse(field.text.toString()).atDay(1) else LocalDate.parse(field.text.toString().take(10)) } catch(_:Exception) { LocalDate.now() }
   fun commit(chosen:LocalDate) {
    if(withTime) {
     val previous=try { LocalDateTime.parse(field.text.toString(),DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm")) } catch(_:Exception) { LocalDateTime.now() }
     TimePickerDialog(activity,{ _,h,m->field.setText(chosen.atTime(h,m).format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm"))) },previous.hour,previous.minute,true).show()
    } else field.setText(if(field.text.length==7)YearMonth.from(chosen).toString() else chosen.toString())
   }
   if(kind=="day")DatePickerDialog(activity,{ _,y,m,d->commit(LocalDate.of(y,m+1,d)) },day.year,day.monthValue-1,day.dayOfMonth).apply {
    datePicker.minDate=LocalDate.of(2010,1,1).atStartOfDay(java.time.ZoneId.systemDefault()).toInstant().toEpochMilli()
    datePicker.maxDate=LocalDate.of(2100,12,31).atStartOfDay(java.time.ZoneId.systemDefault()).toInstant().toEpochMilli()
   }.show()
   else {
    val body=LinearLayout(activity).apply { orientation=LinearLayout.HORIZONTAL;gravity=android.view.Gravity.CENTER;setPadding(24,12,24,12) }
    val year=NumberPicker(activity).apply { minValue=2010;maxValue=2100;value=day.year.coerceIn(2010,2100);body.addView(this) }
    val month=NumberPicker(activity).apply { minValue=1;maxValue=12;displayedValues=months;value=day.monthValue;if(kind=="month")body.addView(this) }
    ua.ducksolar.shared.LocalizedDialog.Builder(activity).setTitle(if(kind=="month")"Вибрати місяць" else "Вибрати рік").setView(body).setNegativeButton("Скасувати",null).setPositiveButton("Обрати") { _,_->commit(LocalDate.of(year.value,if(kind=="month")month.value else 1,1)) }.show()
   }
  }
 }
}
