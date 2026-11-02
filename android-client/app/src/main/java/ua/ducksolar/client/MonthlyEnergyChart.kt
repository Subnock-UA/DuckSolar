package ua.ducksolar.b2.client

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.view.View
import org.json.JSONArray
import java.util.Locale

/** At most 31 daily summaries, no raw history transferred to the client. */
class MonthlyEnergyChart(context:Context,days:JSONArray):View(context) {
 private val rows=(0 until minOf(31,days.length())).map { days.getJSONObject(it) }
 private val paint=Paint(Paint.ANTI_ALIAS_FLAG)
 private val series=listOf("pv" to Color.rgb(217,161,24),"inverter_import" to Color.rgb(51,132,208),"inverter_export" to Color.rgb(56,157,100))
 private fun value(i:Int,key:String):Double? {
  val row=rows[i].optJSONObject(key) ?: return null
  if(row.isNull("kwh"))return null
  val v=row.optDouble("kwh",Double.NaN)
  return if(v.isFinite() && v>=0)v else null
 }
 init {
  minimumHeight=(250*resources.displayMetrics.density).toInt()
  contentDescription="Добова енергія: PV — жовтий, імпорт — синій, експорт — зелений. Значення й покриття доступні у списку за днями. Відсутні дані позначені рискою."
 }
 override fun onDraw(canvas:Canvas) {
  super.onDraw(canvas);val d=resources.displayMetrics.density
  val left=48*d;val right=width-8*d;val top=38*d;val bottom=height-32*d
  if(rows.isEmpty() || right<=left || bottom<=top)return
  val values=rows.indices.flatMap { i ->series.mapNotNull { value(i,it.first) } }
  val axis=ChartAxis.scale(0.0,values.maxOrNull() ?: 0.0,5,true);val maximum=axis.high
  paint.textSize=11*d;paint.strokeWidth=d
  for(v in axis.ticks) {
   val y=(bottom-(bottom-top)*v/maximum).toFloat();paint.color=Color.rgb(220,228,233);canvas.drawLine(left,y,right,y,paint)
   paint.color=Color.DKGRAY;canvas.drawText(ua.ducksolar.shared.UiLanguage.text(axis.label(v)),0f,y,paint)
  }
  paint.color=Color.DKGRAY;canvas.drawText(ua.ducksolar.shared.UiLanguage.text("кВт·год / день"),0f,14*d,paint)
  val step=(right-left)/rows.size;val bar=(step/4).coerceAtLeast(d)
  for(i in rows.indices) {
   val x=left+i*step
   for((j,s) in series.withIndex()) {
    val v=value(i,s.first);paint.color=s.second
    val bx=x+j*bar
    if(v==null)canvas.drawLine(bx,bottom-3*d,bx+bar*.8f,bottom-3*d,paint)
    else canvas.drawRect(bx,(bottom-(bottom-top)*(v/maximum)).toFloat(),bx+bar*.8f,bottom,paint)
   }
   if(i==0 || i==rows.lastIndex || (i+1)%5==0) {
    paint.color=Color.DKGRAY;canvas.drawText(ua.ducksolar.shared.UiLanguage.text(rows[i].optString("date").takeLast(2)),x,bottom+17*d,paint)
   }
  }
 }
}
