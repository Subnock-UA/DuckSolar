package ua.ducksolar.b2.client
import android.app.PendingIntent
import android.appwidget.*
import android.content.*
import android.os.SystemClock
import android.widget.RemoteViews
import org.json.JSONObject

/** A cache consumer. No Python initialization, login, socket or equipment read in onUpdate. */
class SolarWidget:AppWidgetProvider() {
 companion object {
  private var last=0L
  @Synchronized fun capture(context:Context,envelope:JSONObject,force:Boolean=false) {
   val state=envelope.optJSONObject("state") ?: return
   if(!envelope.optBoolean("connected") || state.optBoolean("stale",true))return
   val now=SystemClock.elapsedRealtime();if(!force && last!=0L && now-last<30000)return;last=now
   val data=state.optJSONObject("data") ?: JSONObject()
   val row=JSONObject().put("time",System.currentTimeMillis()).put("updated",state.optString("updated"))
    .put("pv",state.opt("pv_accounted_w") ?: data.opt("pv_w") ?: JSONObject.NULL).put("load",data.opt("output_w") ?: JSONObject.NULL)
    .put("soc",state.optJSONObject("battery")?.optJSONObject("values")?.opt("soc") ?: JSONObject.NULL)
    .put("grid",state.optJSONObject("normalized")?.optJSONObject("grid")?.opt("voltage_present") ?: JSONObject.NULL)
    .put("valid",envelope.optBoolean("connected") && !state.optBoolean("stale",true))
   val metrics=HomeMetrics.withDisplayCurrents(state.optJSONObject("normalized")?.optJSONObject("metrics"))
   fun metric(key:String):Any {
    val m=metrics?.optJSONObject(key) ?: return JSONObject.NULL
    if(m.optBoolean("stale") || m.optDouble("age_s",0.0)>m.optDouble("valid_for_s",Double.POSITIVE_INFINITY) || m.optString("quality","good") !in listOf("good","estimated") || m.isNull("value"))return JSONObject.NULL
    return m.optDouble("value",Double.NaN).takeIf { it.isFinite() && it>=0 } ?: JSONObject.NULL
   }
   for((key,id) in listOf("pv_v" to "pv.inputs.aggregate.voltage","pv_a" to "pv.inputs.aggregate.current",
    "load_v" to "output.phases.L1.voltage","load_a" to "output.phases.L1.current",
    "battery_v" to "battery.channels.main.voltage","charge_a" to "battery.channels.main.charge_current",
    "discharge_a" to "battery.channels.main.discharge_current","grid_v" to "grid.phases.L1.voltage","grid_a" to "grid.phases.L1.current"))row.put(key,metric(id))
   val profile=state.optJSONObject("descriptor")?.optJSONObject("pv_profile")
   val pvLimit=profile?.optDouble("installed_kw",Double.NaN)?.times(1000)
   if(pvLimit!=null && pvLimit.isFinite() && pvLimit>0)row.put("pv_max",pvLimit)
   val fields=state.optJSONObject("parameters")?.optJSONObject("raw")?.optString("QPIRI")?.trim()?.removePrefix("(")?.split(Regex("\\s+"))
   val loadLimit=fields?.getOrNull(6)?.toDoubleOrNull()
   if(loadLimit!=null && loadLimit.isFinite() && loadLimit>0)row.put("load_max",loadLimit)
   context.getSharedPreferences("solar_widget",0).edit().putString("cache",row.toString()).apply()
   val manager=AppWidgetManager.getInstance(context);val ids=manager.getAppWidgetIds(ComponentName(context,SolarWidget::class.java));render(context,manager,ids)
  }
  fun failure(context:Context,message:String) {
   val prefs=context.getSharedPreferences("solar_widget",0)
   val row=try { JSONObject(prefs.getString("cache","{}")!!) } catch(_:Exception) { JSONObject() }
   row.put("error",message.take(120));prefs.edit().putString("cache",row.toString()).apply()
   val manager=AppWidgetManager.getInstance(context);render(context,manager,manager.getAppWidgetIds(ComponentName(context,SolarWidget::class.java)))
  }
  private fun render(context:Context,manager:AppWidgetManager,ids:IntArray) {
   if(ids.isEmpty())return
   val row=try { JSONObject(context.getSharedPreferences("solar_widget",0).getString("cache","{}")!!) } catch(_:Exception) { JSONObject() }
   manager.updateAppWidget(ids,views(context,row))
  }
  fun views(context:Context,row:JSONObject):RemoteViews {
   val valid=row.optBoolean("valid")
   ua.ducksolar.shared.UiLanguage.load(context)
   val views=RemoteViews(context.packageName,R.layout.solar_widget)
   views.setTextViewText(R.id.widget_refresh,ua.ducksolar.shared.UiLanguage.text("↻ Оновити"))
   views.setContentDescription(R.id.widget_refresh,ua.ducksolar.shared.UiLanguage.text("Оновити дані віджета"))
   views.setImageViewBitmap(R.id.widget_rings,WidgetRings.render(row))
   views.setContentDescription(R.id.widget_rings,WidgetRings.description(row))
   val updated=row.optString("updated").replace('T',' ').substringAfter(' ',"").take(5)
   val grid=if(!valid || row.isNull("grid"))"Мережа —" else if(row.optBoolean("grid"))"Мережа є" else "Без мережі"
   views.setTextViewText(R.id.widget_grid,ua.ducksolar.shared.UiLanguage.text("$grid · ${WidgetRings.detail(row,"grid_v","В")} · ${WidgetRings.detail(row,"grid_a","А")}"))
   val age=System.currentTimeMillis()-row.optLong("time")
   views.setTextViewText(R.id.widget_stamp,ua.ducksolar.shared.UiLanguage.text(if(!valid)"Відкрийте Duck Solar" else "Знімок $updated"+(if(age !in 0..600000)" • застарілий" else "")))
   views.setOnClickPendingIntent(R.id.widget_root,PendingIntent.getActivity(context,0,Intent(context,MainActivity::class.java),PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT))
   views.setOnClickPendingIntent(R.id.widget_refresh,PendingIntent.getBroadcast(context,1,Intent(context,SolarWidget::class.java).setAction("ua.ducksolar.b2.client.WIDGET_REFRESH"),PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT))
   if(row.optString("error").isNotBlank())views.setTextViewText(R.id.widget_stamp,ua.ducksolar.shared.UiLanguage.text("Не оновлено • знімок "+row.optString("updated").replace('T',' ').substringAfter(' ',"").take(5)))
   return views

  }
 }
 override fun onUpdate(context:Context,manager:AppWidgetManager,ids:IntArray) { render(context,manager,ids);WidgetRefreshJob.schedule(context) }
 override fun onEnabled(context:Context) { WidgetRefreshJob.schedule(context,true) }
 override fun onDisabled(context:Context) { context.getSystemService(android.app.job.JobScheduler::class.java).cancel(4102) }
 override fun onReceive(context:Context,intent:Intent) { super.onReceive(context,intent);if(intent.action==context.packageName+".LANGUAGE_CHANGED") { val manager=AppWidgetManager.getInstance(context);render(context,manager,manager.getAppWidgetIds(ComponentName(context,SolarWidget::class.java))) };if(intent.action=="ua.ducksolar.b2.client.WIDGET_REFRESH")WidgetRefreshJob.schedule(context,true) }
}
