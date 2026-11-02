package ua.ducksolar.b2.client
import android.app.job.*
import android.appwidget.AppWidgetManager
import android.content.*
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/** One snapshot per five-minute target; Android may defer it during Doze. */
class WidgetRefreshJob:JobService() {
 companion object {
  private const val ID=4102
  private val busy=AtomicBoolean(false)
  private val worker=Executors.newSingleThreadExecutor()
  fun schedule(context:Context,manual:Boolean=false,replace:Boolean=false) {
   val scheduler=context.getSystemService(JobScheduler::class.java)
   val ids=AppWidgetManager.getInstance(context).getAppWidgetIds(ComponentName(context,SolarWidget::class.java))
   if(ids.isEmpty()) { scheduler.cancel(ID);return }
   if(!manual && !replace && scheduler.getPendingJob(ID)!=null)return
   val info=JobInfo.Builder(ID,ComponentName(context,WidgetRefreshJob::class.java)).setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
    .setMinimumLatency(if(manual)0L else 300000L).setOverrideDeadline(if(manual)1000L else 600000L).setPersisted(true).build()
   scheduler.schedule(info)
  }
 }
 override fun onStartJob(params:JobParameters):Boolean {
  if(!busy.compareAndSet(false,true))return false
  worker.execute {
   try { ClientBridge.initialize(this);SolarWidget.capture(this,ClientBridge.widgetSnapshot(),true) }
   catch(error:Exception) { SolarWidget.failure(this,error.message ?: "Сервер недоступний") }
   finally { busy.set(false);jobFinished(params,false);schedule(this,false,true) }
  }
  return true
 }
 override fun onStopJob(params:JobParameters):Boolean { schedule(this);return true }
}
