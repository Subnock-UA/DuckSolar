package ua.ducksolar.b2.client

import android.graphics.*
import org.json.JSONObject
import java.util.Locale

/** Drawn only on a widget update; no animation, timers or equipment access. */
object WidgetRings {
 private fun number(row:JSONObject,key:String):Double?=row.optDouble(key,Double.NaN).takeIf { it.isFinite() && it>=0 && row.has(key) && !row.isNull(key) }
 fun render(row:JSONObject):Bitmap {
  val bitmap=Bitmap.createBitmap(720,270,Bitmap.Config.ARGB_8888)
  val canvas=Canvas(bitmap);val paint=Paint(Paint.ANTI_ALIAS_FLAG)
  val valid=row.optBoolean("valid");val old=System.currentTimeMillis()-row.optLong("time") !in 0..600000 || row.optString("error").isNotBlank()
  val items=listOf(Triple("pv","PV",Color.rgb(99,230,173)),Triple("load","Навантаження",Color.rgb(255,202,105)),Triple("soc","АКБ",Color.rgb(106,202,244)))
  for((index,item) in items.withIndex()) {
   val (key,label,base)=item;val center=120f+index*240f;val y=82f;val r=73f
   val value=if(valid)number(row,key) else null
   val max=if(key=="soc")100.0 else number(row,key+"_max")?.takeIf { it>0 }
   paint.style=Paint.Style.STROKE;paint.strokeWidth=12f;paint.strokeCap=Paint.Cap.ROUND;paint.color=Color.rgb(46,79,85)
   canvas.drawCircle(center,y,r,paint)
   if(value!=null && max!=null) {
    paint.color=if(old)Color.rgb(113,148,150) else if(key=="soc" && value<20)Color.rgb(255,131,123) else base
    canvas.drawArc(center-r,y-r,center+r,y+r,-90f,(360*value/max).coerceIn(0.0,360.0).toFloat(),false,paint)
   }
   paint.style=Paint.Style.FILL;paint.textAlign=Paint.Align.CENTER;paint.typeface=Typeface.create("sans-serif-medium",Typeface.NORMAL);paint.textSize=48f;paint.color=Color.rgb(239,250,247)
   val text=when { value==null->"—";key=="soc"->String.format(Locale.getDefault(),"%.0f",value);value>=1000->String.format(Locale.getDefault(),"%.2f",value/1000);else->String.format(Locale.getDefault(),"%.0f",value) }
   canvas.drawText(ua.ducksolar.shared.UiLanguage.text(text),center,y+7,paint)
   paint.typeface=Typeface.create("sans-serif",Typeface.NORMAL);paint.textSize=24f;paint.color=Color.rgb(166,198,199)
   canvas.drawText(ua.ducksolar.shared.UiLanguage.text(if(key=="soc")"%" else if(value!=null && value>=1000)"кВт" else "Вт"),center,y+34,paint)
   paint.textSize=29f;paint.color=base;canvas.drawText(ua.ducksolar.shared.UiLanguage.text(label),center,190f,paint)
   paint.textSize=29f;paint.color=Color.rgb(214,234,231)
   val voltageKey=when(key) { "pv"->"pv_v";"load"->"load_v";else->"battery_v" }
   canvas.drawText(ua.ducksolar.shared.UiLanguage.text(detail(row,voltageKey,"В")),center,226f,paint)
   val current=when(key) {
    "pv"->detail(row,"pv_a","А")
    "load"->detail(row,"load_a","А")
    else->"↑ ${detail(row,"charge_a","")} · ↓ ${detail(row,"discharge_a","А")}"
   }
   if(key=="soc")paint.textSize=26f
   canvas.drawText(ua.ducksolar.shared.UiLanguage.text(current),center,263f,paint)
  }
  return bitmap
 }
 fun detail(row:JSONObject,key:String,unit:String):String {
  val value=if(row.optBoolean("valid"))number(row,key) else null
  return (value?.let { String.format(Locale.getDefault(),"%.1f",it).removeSuffix(".0").removeSuffix(",0") } ?: "—")+(if(unit.isBlank())"" else " $unit")
 }
 fun description(row:JSONObject):String {
  fun text(key:String)=number(row,key)?.toString() ?: "немає даних"
  return "PV ${text("pv")} Вт, шкала ${text("pv_max")} Вт. Навантаження ${text("load")} Вт, шкала ${text("load_max")} Вт. Заряд АКБ за БМС ${text("soc")} відсотків. PV ${detail(row,"pv_v","В")}, ${detail(row,"pv_a","А")}. Навантаження ${detail(row,"load_v","В")}, ${detail(row,"load_a","А")}. АКБ ${detail(row,"battery_v","В")}, заряд ${detail(row,"charge_a","А")}, розряд ${detail(row,"discharge_a","А")}."
 }
}
