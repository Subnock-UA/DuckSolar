package ua.ducksolar.b2.server
import android.app.Activity
import android.os.*
import android.widget.*
import org.json.JSONObject
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/** Screen only observes the server-owned job. Leaving never cancels the job. */
class CacheActivity:ua.ducksolar.shared.LocalizedActivity() {
 private val worker=Executors.newSingleThreadExecutor()
 private val handler=Handler(Looper.getMainLooper());private val busy=AtomicBoolean(false)
 private lateinit var state:TextView;private lateinit var progress:ProgressBar;private lateinit var start:Button;private lateinit var cancel:Button
 private val tick=object:Runnable { override fun run() { request { Bridge.cacheStatus() };handler.postDelayed(this,2500) } }
 override fun onCreate(savedInstanceState:Bundle?) {
  super.onCreate(savedInstanceState)
  val root=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL;setPadding(24,24,24,24);setBackgroundColor(AppStyle.canvas) }
  setContentView(ScrollView(this).apply { addView(root) })
  Button(this).apply { text="‹ До сервера";root.addView(this);setOnClickListener { finish() } }
  TextView(this).apply { text="Кеш графіків";textSize=25f;root.addView(this) }
  TextView(this).apply { text="Підготовка працює у фоновій службі сервера. Можна згорнути додаток або перейти в інше меню. Готові сумісні дані не перераховуються; для поточних даних додається лише новий хвіст. Ручний запуск не очікує зарядки.";textSize=15f;root.addView(this) }
  state=TextView(this).apply { text="Завантаження стану…";textSize=17f;setPadding(0,24,0,24);root.addView(this) }
  progress=ProgressBar(this,null,android.R.attr.progressBarStyleHorizontal).apply { root.addView(this) }
  start=Button(this).apply { id=android.view.View.generateViewId();text="Підготувати відсутні кеші / продовжити";root.addView(this);setOnClickListener { request(true) { Bridge.cacheStart() } } }
  cancel=Button(this).apply { text="Скасувати підготовку";root.addView(this);setOnClickListener { request(true) { Bridge.cacheCancel() } } }
  root.post { CompactSections.apply(root);AppStyle.apply(root) }
 }
 private fun request(force:Boolean=false,action:()->JSONObject) {
  if(!force && !busy.compareAndSet(false,true))return
  worker.execute {
   try { val result=action();runOnUiThread { if(!isDestroyed)render(result) } }
   catch(error:Exception) { runOnUiThread { if(!isDestroyed)state.text=error.message ?: "Не вдалося отримати стан" } }
   finally { if(!force)busy.set(false) }
  }
 }
 private fun render(job:JSONObject) {
  val stage=job.optString("state");val active=stage in listOf("queued","running","waiting_client","waiting_charging","waiting_resources","paused_server","cancelling")
  val title=when(stage) {
   "queued"->"У черзі";"running"->"Підготовка";"waiting_client"->"Очікування завершення запиту клієнта"
   "waiting_resources"->"Очікування доступних ресурсів";"waiting_charging"->"Очікування зарядки";"paused_server"->"Продовжиться після запуску сервера"
   "completed"->"Підготовку завершено";"cancelling"->"Скасування…";"cancelled"->"Підготовку скасовано";"error"->"Помилка підготовки";else->"Готово до запуску"
  }
  val done=job.optInt("completed");val total=job.optInt("total")
  state.text="$title\nПеревірено: $done / $total\nГотові: ${job.optInt("cache_hits")} (без повторного відкриття: ${job.optInt("skipped_unchanged")}) · підготовлено/доповнено: ${job.optInt("prepared")}\nПідхоплено старих проєкцій: ${job.optInt("adopted")}\nПаралельних завдань: ${job.optJSONArray("active_tasks")?.length() ?: 0} / ${job.optInt("worker_limit")}\n${job.optString("last_day")}\n${job.optString("error","")}"+
   (if(!job.optBoolean("server_running"))"\nСпочатку запустіть сервер." else "")
  progress.max=total.coerceAtLeast(1);progress.progress=done;progress.isIndeterminate=active && total==0
  start.isEnabled=job.optBoolean("server_running") && (!active || !job.optBoolean("manual") && stage!="cancelling");cancel.isEnabled=job.optBoolean("server_running") && active && stage!="cancelling"
 }
 override fun onResume() { super.onResume();handler.post(tick) }
 override fun onPause() { handler.removeCallbacks(tick);super.onPause() }
 override fun onDestroy() { worker.shutdown();super.onDestroy() }
}
