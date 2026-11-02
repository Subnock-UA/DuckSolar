package ua.ducksolar.b2.client

import android.app.Activity
import android.app.AlertDialog
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.InputType
import android.widget.*
import org.json.JSONObject
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

object CommandText {
 fun value(row:JSONObject,stale:Boolean):String {
  if(!row.optBoolean("present") || row.isNull("raw_value"))return "— (немає даних)"
  val text=DisplayText.clean(row.optString("display_value","—"))
    return text+(if(row.optString("unit").isNotBlank())" ${row.optString("unit")}" else "")+(if(stale)" (застаріле)" else "")
 }
 fun status(row:JSONObject):String {
  val title=when(row.optString("status")) {
   "queued"->"У черзі";"sending"->"Надсилання";"writing"->"Запис виконується"
   "verifying"->"Очікуємо контрольне читання";"verified"->"Підтверджено контрольним читанням"
   "rejected"->"Відхилено";"cancelled"->"Скасовано"
   "unknown"->"Результат невідомий — запис автоматично не повторюється"
   else->"Команд ще немає"
  }
  return title+"\n"+DisplayText.clean(row.optString("message"))+(if(row.has("actual") && !row.isNull("actual"))"\nФактичне значення: ${row.optString("actual")}" else "")
 }
}

class ParameterActivity:ua.ducksolar.shared.LocalizedActivity() {
 companion object { private val worker=Executors.newSingleThreadExecutor() }
 private val pending=AtomicBoolean(false)
 private val handler=Handler(Looper.getMainLooper())
 private var visible=false
 private lateinit var status:TextView
 private lateinit var operation:TextView
 private lateinit var rows:LinearLayout
 private var signature=""
 private var watchingCommand=false
 private val poll=object:Runnable {
  override fun run() {
   if(!visible)return
   execute(true) {
    val state=ClientBridge.parameters()
    val command=if(watchingCommand)ClientBridge.commandStatus() else null
    runOnUiThread { if(visible) {
     render(state)
     if(command!=null) { operation.text=CommandText.status(command);watchingCommand=command.optString("status") in setOf("queued","sending","writing","verifying") }
    } }
   }
   handler.postDelayed(this,2000)
  }
 }
 private fun label(parent:LinearLayout,value:String,size:Float=16f)=TextView(this).apply { text=DisplayText.clean(value);textSize=size;setTextColor(android.graphics.Color.rgb(38,54,65));setPadding(0,12,0,12);setTextIsSelectable(true);parent.addView(this) }
 override fun onCreate(state:Bundle?) {
  super.onCreate(state)
  window.statusBarColor=android.graphics.Color.rgb(244,247,249);window.navigationBarColor=android.graphics.Color.rgb(244,247,249)
  window.decorView.systemUiVisibility=ViewFlags.lightBars
  val root=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL;setPadding(24,12,24,12);background=AppStyle.backdrop() };setContentView(root)
  root.setOnApplyWindowInsetsListener { _,i -> root.setPadding(24+i.systemWindowInsetLeft,12+i.systemWindowInsetTop,24+i.systemWindowInsetRight,12+i.systemWindowInsetBottom);i }
  Button(this).apply { text="‹ Додатково";root.addView(this);setOnClickListener { finish() } }
  label(root,"Параметри інвертора",24f)
  status=label(root,"Очікування актуальних параметрів",14f)
  val controls=LinearLayout(this);root.addView(controls)
  Button(this).apply { text="Перечитати";controls.addView(this,LinearLayout.LayoutParams(0,-2,1f));setOnClickListener { execute { ClientBridge.refreshParameters();runOnUiThread { if(!isDestroyed)status.text="Сервер перечитує параметри…" } } } }
  Button(this).apply { text="Результат команди";isAllCaps=false;controls.addView(this,LinearLayout.LayoutParams(0,-2,1f));setOnClickListener { execute { val result=ClientBridge.commandStatus();runOnUiThread { if(!isDestroyed)operation.text=CommandText.status(result) } } } }
  operation=label(root,"Запис лише після підтвердження. Остаточний результат визначає контрольне читання сервера.",13f)
  CompactSections.apply(root)
  AppStyle.watch(root)
  rows=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL };root.addView(ScrollView(this).apply { addView(rows) },LinearLayout.LayoutParams(-1,0,1f))
 }
 private fun execute(silent:Boolean=false,action:()->Unit) {
  if(!pending.compareAndSet(false,true)) { if(!silent)operation.text="Попередній запит ще виконується; цю дію не надіслано.";return }
  worker.execute { try { action() } catch(e:Exception) { runOnUiThread { if(!isDestroyed && !isFinishing)operation.text=e.message ?: "Запит не виконано" } } finally { pending.set(false) } }
 }
 private fun render(data:JSONObject) {
  if(isDestroyed || isFinishing)return
  val stale=data.optBoolean("stale",true)
  status.text=(if(stale)"Параметри застарілі або відсутні • зміни недоступні" else "Актуальні параметри")+"\nОновлено: ${data.optString("updated")}"
  val list=data.optJSONArray("rows") ?: org.json.JSONArray()
  val current=list.toString()+stale+data.optString("device_id")+data.optString("server_profile")
  if(current==signature)return
  signature=current;rows.removeAllViews()
  val ordered=(0 until list.length()).map { list.getJSONObject(it) }.sortedByDescending { it.optBoolean("writable") }
  for(row in ordered) {
   val title=DisplayText.clean(row.optString("name",row.optString("ui_name",row.optString("canonical_id"))))
   val value=CommandText.value(row,stale)
   label(rows,"$title: $value")
   label(rows,if(row.optBoolean("writable"))row.optString("allowed_note") else "Лише перегляд • "+row.optString("write_reason","Команда запису не встановлена"),13f)
   if(row.optBoolean("writable") && row.optBoolean("present"))Button(this).apply {
    text="Змінити: $title";isAllCaps=false;isEnabled=!stale;rows.addView(this)
    setOnClickListener { confirm(row,title,data.optString("device_id"),data.optString("server_profile")) }
   }
  }
 }
 private fun confirm(row:JSONObject,title:String,device:String,profile:String):AlertDialog {
  val rule=row.optJSONObject("write_rule") ?: JSONObject()
  val options=rule.optJSONObject("enum")
  fun send(value:String) {
   val expected=row.optString("raw_value")
   val next=options?.optString(value,value) ?: value
   ua.ducksolar.shared.LocalizedDialog.Builder(this).setTitle("Підтвердити зміну?")
    .setMessage("$title\n${CommandText.value(row,false)} → $next\nСервер перевірить поточне значення та перечитає результат. Запис автоматично не повторюється.")
    .setNegativeButton("Скасувати",null).setPositiveButton("Надіслати") { _,_ ->
     execute {
      val result=ClientBridge.submitParameter(row.getString("canonical_id"),value,expected,device,profile)
      runOnUiThread { if(!isDestroyed) { operation.text=CommandText.status(result);watchingCommand=result.optString("status") in setOf("queued","sending","writing","verifying") } }
     }
    }.show()
  }
  if(options!=null && options.length()>0) {
   val keys=options.keys().asSequence().toList().sortedBy { it.toDoubleOrNull() ?: 0.0 }
   val labels=keys.map { options.getString(it) }.toTypedArray()
   return ua.ducksolar.shared.LocalizedDialog.Builder(this).setTitle(title).setSingleChoiceItems(labels,keys.indexOf(row.optString("raw_value"))) { dialog,index -> dialog.dismiss();send(keys[index]) }.setNegativeButton("Скасувати",null).show()
  }
  val values=rule.optJSONArray("values")
  if(values!=null) {
   val keys=(0 until values.length()).map { values.get(it).toString() }
   return ua.ducksolar.shared.LocalizedDialog.Builder(this).setTitle(title).setItems(keys.map { "$it ${row.optString("unit")}" }.toTypedArray()) { _,index -> send(keys[index]) }.setNegativeButton("Скасувати",null).show()
  }
  val input=EditText(this).apply { hint="Нове значення";setSingleLine();inputType=InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_FLAG_DECIMAL;setText(row.optString("raw_value"));selectAll() }
  val dialog=ua.ducksolar.shared.LocalizedDialog.Builder(this).setTitle(title).setMessage("Поточне: ${CommandText.value(row,false)}\n${DisplayText.clean(row.optString("allowed_note"))}").setView(input).setNegativeButton("Скасувати",null).setPositiveButton("Перевірити",null).create()
  dialog.setOnShowListener { dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
   val value=input.text.toString().trim().replace(',','.')
   val number=value.toDoubleOrNull()
   if(number==null || !number.isFinite()) { input.error="Вкажіть скінченне числове значення";return@setOnClickListener }
   if(rule.has("minimum") && (number<rule.optDouble("minimum") || number>rule.optDouble("maximum"))) { input.error="Значення поза допустимим діапазоном";return@setOnClickListener }
   dialog.dismiss();send(value)
  } }
  dialog.show()
  return dialog
 }
 override fun onResume() { super.onResume();ClientLifecycle.enter();visible=true;handler.removeCallbacks(poll);handler.post(poll) }
 override fun onPause() { ClientLifecycle.leave();visible=false;handler.removeCallbacks(poll);super.onPause() }
 override fun onDestroy() { handler.removeCallbacksAndMessages(null);super.onDestroy() }
}
