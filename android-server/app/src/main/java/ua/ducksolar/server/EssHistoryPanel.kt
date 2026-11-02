package ua.ducksolar.b2.server
import android.app.Activity
import android.os.Handler
import android.os.Looper
import android.widget.*
import java.time.LocalDate
import java.util.concurrent.Executors
object EssHistoryPanel {
 private val worker=Executors.newSingleThreadExecutor()
 fun show(activity:Activity,pn:String) {
  val body=LinearLayout(activity).apply { orientation=LinearLayout.VERTICAL;setPadding(24,8,24,16) }
  fun field(hint:String,text:String="")=EditText(activity).apply { this.hint=hint;setSingleLine();setText(text);body.addView(this) }
  TextView(activity).apply { text="Історія завантажується на сервер, до 31 завершеного дня за раз. Пароль ESS не зберігається. Наявні коректні CSV зберігаються.";body.addView(this) }
  val user=field("Логін ESS");val password=field("Пароль ESS").apply { inputType=android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD }
  password.isSaveEnabled=false
  val collector=field("PN логера",pn)
  val end=LocalDate.now().minusDays(1);val start=field("Початок РРРР-ММ-ДД",end.withDayOfMonth(1).toString());val finish=field("Кінець РРРР-ММ-ДД",end.toString())
  PeriodPicker.bind(activity,start);PeriodPicker.bind(activity,finish)
  AppStyle.apply(body)
  val status=TextView(activity).apply { text="Очікування";setTextIsSelectable(true);body.addView(this) }
  val begin=Button(activity).apply { text="Завантажити історію ESS";body.addView(this) }
  val stop=Button(activity).apply { text="Зупинити завантаження";body.addView(this) }
  val dialog=ua.ducksolar.shared.LocalizedDialog.Builder(activity).setTitle("Історія ESS").setView(ScrollView(activity).apply { addView(body) }).setNegativeButton("Закрити",null).create()
  val handler=Handler(Looper.getMainLooper());var open=true;val pending=java.util.concurrent.atomic.AtomicBoolean(false)
  val poll=object:Runnable {
   override fun run() {
    if(!open)return
    if(pending.compareAndSet(false,true))worker.execute {
     try { val value=Bridge.essHistoryStatus();activity.runOnUiThread { if(open) { status.text=value.optString("message")+"\n${value.optInt("done")}/${value.optInt("total")} • без даних ${value.optInt("no_data_days")} • помилок ${value.optInt("failed_days")}";begin.isEnabled=!value.optBoolean("running") } } }
     catch(_:Exception) {} finally { pending.set(false) }
    }
    handler.postDelayed(this,2000)
   }
  }
  begin.setOnClickListener {
   val args=listOf(user.text.toString(),password.text.toString(),collector.text.toString(),start.text.toString().trim(),finish.text.toString().trim())
   begin.isEnabled=false
   worker.execute {
    try { Bridge.essHistoryStart(args[0],args[1],args[2],args[3],args[4]);activity.runOnUiThread { password.setText("") } }
    catch(e:Exception) { activity.runOnUiThread { if(open) { status.text=e.message ?: "Не вдалося почати завантаження";begin.isEnabled=true } } }
   }
  }
  stop.setOnClickListener { worker.execute { try { Bridge.essHistoryStop() } catch(_:Exception) {} } }
  dialog.setOnDismissListener { open=false;handler.removeCallbacks(poll);password.setText("") }
  dialog.show();handler.post(poll)
 }
}
