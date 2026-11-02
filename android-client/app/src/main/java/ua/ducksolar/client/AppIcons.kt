package ua.ducksolar.b2.client

import android.graphics.*
import android.graphics.drawable.Drawable

/** One consistent 24 dp outline icon family; no emoji/font dependencies. */
class AppIcon(private val kind:String,private val tint:Int=AppStyle.accent):Drawable() {
 private val paint=Paint(Paint.ANTI_ALIAS_FLAG)
 override fun draw(c:Canvas) {
  c.save();c.translate(bounds.left.toFloat(),bounds.top.toFloat());c.scale(bounds.width()/24f,bounds.height()/24f)
  paint.color=if(state.contains(android.R.attr.state_selected))AppStyle.accent else tint
  paint.style=Paint.Style.STROKE;paint.strokeWidth=1.7f;paint.strokeCap=Paint.Cap.ROUND;paint.strokeJoin=Paint.Join.ROUND
  fun line(vararg v:Float) { val p=Path();p.moveTo(v[0],v[1]);for(i in 2 until v.size step 2)p.lineTo(v[i],v[i+1]);c.drawPath(p,paint) }
  when(kind) {
   "analytics"->{ for((x,h) in listOf(4f to 7f,10f to 11f,16f to 15f))c.drawRoundRect(x,23f-h,x+3f,23f,0.5f,0.5f,paint);line(3f,11f,9f,6f,14f,8f,20f,2f);c.drawCircle(20f,2f,1f,paint) }
   "battery_menu"->{ c.drawRoundRect(2f,5f,20f,20f,3f,3f,paint);line(22f,10f,22f,15f);for(x in listOf(6f,10f,14f))line(x,9f,x,16f) }
   "planning"->{ c.drawRoundRect(2f,4f,19f,21f,2f,2f,paint);line(2f,9f,19f,9f);line(6f,1f,6f,6f);line(15f,1f,15f,6f);line(6f,13f,8f,13f);line(6f,17f,8f,17f);paint.style=Paint.Style.FILL;paint.color=Color.WHITE;c.drawCircle(17f,17f,6f,paint);paint.color=tint;paint.style=Paint.Style.STROKE;c.drawCircle(17f,17f,5f,paint);line(17f,14f,17f,17f,19f,18f) }
   "commands"->{ c.drawRoundRect(2f,2f,18f,21f,2f,2f,paint);line(5f,6f,7f,8f,10f,5f);line(5f,12f,7f,14f,10f,11f);paint.style=Paint.Style.FILL;paint.color=Color.WHITE;c.drawRoundRect(11f,12f,23f,23f,2f,2f,paint);paint.color=tint;paint.style=Paint.Style.STROKE;c.drawRoundRect(11f,12f,23f,23f,2f,2f,paint);line(14f,15f,17f,18f,14f,20f);line(19f,20f,21f,20f) }
   "balance"->{ c.drawRoundRect(3f,5f,21f,22f,2f,2f,paint);line(3f,10f,21f,10f);line(8f,2f,8f,7f);line(16f,2f,16f,7f);line(7f,19f,7f,17f);line(12f,19f,12f,15f);line(17f,19f,17f,13f) }
   "meter"->{ c.drawRoundRect(3f,2f,21f,20f,2f,2f,paint);c.drawRoundRect(6f,5f,18f,10f,1f,1f,paint);for(x in listOf(9f,12f,15f))line(x,6f,x,9f);line(7f,14f,9f,14f);line(14f,14f,17f,14f);line(9f,20f,9f,23f,15f,23f,15f,20f) }
   "events"->{ val p=Path().apply { moveTo(4f,18f);quadTo(7f,15f,7f,9f);cubicTo(7f,2f,17f,2f,17f,9f);quadTo(17f,15f,20f,18f);quadTo(12f,22f,4f,18f) };c.drawPath(p,paint);line(12f,2f,12f,1f);c.drawArc(9f,19f,15f,24f,0f,180f,false,paint);line(13f,8f,10f,13f,14f,13f,11f,17f) }
   "server"->{ for(y in listOf(3f,10f,17f)) { c.drawRoundRect(3f,y,21f,y+5f,1.5f,1.5f,paint);line(6f,y+2.5f,7f,y+2.5f);line(15f,y+2.5f,18f,y+2.5f) } }
   "archive"->{ c.drawRoundRect(3f,7f,21f,22f,2f,2f,paint);c.drawRoundRect(2f,3f,22f,7f,1f,1f,paint);line(9f,12f,15f,12f);line(7f,17f,17f,17f) }
   "tariff"->{ line(4f,3f,15f,3f,22f,10f,11f,21f,3f,13f,3f,3f);c.drawCircle(8f,7f,1f,paint);line(15f,9f,11f,14f,15f,14f,12f,18f) }
   "home"->{ line(3f,11f,12f,3f,21f,11f);line(5f,9f,5f,21f,19f,21f,19f,9f);line(10f,21f,10f,14f,14f,14f,14f,21f) }
   "monitor"->{ c.drawRoundRect(3f,4f,21f,18f,3f,3f,paint);line(6f,12f,9f,12f,11f,8f,14f,15f,16f,11f,19f,11f);line(9f,21f,15f,21f) }
   "chart"->{ line(4f,3f,4f,21f,22f,21f);line(7f,16f,11f,11f,15f,13f,21f,5f) }
   "more"->{ paint.style=Paint.Style.FILL;for(x in listOf(5f,12f,19f))c.drawCircle(x,12f,1.8f,paint) }
   "sun"->{ c.drawCircle(12f,12f,4f,paint);for(i in 0..7) { val a=i*Math.PI/4;c.drawLine(12+7*kotlin.math.cos(a).toFloat(),12+7*kotlin.math.sin(a).toFloat(),12+10*kotlin.math.cos(a).toFloat(),12+10*kotlin.math.sin(a).toFloat(),paint) } }
   "grid"->{ line(12f,2f,6f,22f);line(12f,2f,18f,22f);line(4f,8f,20f,8f);line(5f,14f,19f,14f);line(9f,9f,16f,20f);line(15f,9f,8f,20f) }
   "battery"->{ c.drawRoundRect(5f,4f,19f,22f,2.5f,2.5f,paint);line(9f,2f,15f,2f);line(9f,10f,15f,10f);line(9f,15f,15f,15f) }
   "settings"->{ for(y in listOf(6f,12f,18f))line(3f,y,21f,y);c.drawCircle(8f,6f,2f,paint);c.drawCircle(16f,12f,2f,paint);c.drawCircle(10f,18f,2f,paint) }
   "pc"->{ c.drawRoundRect(2f,3f,22f,17f,2f,2f,paint);line(8f,21f,16f,21f);line(12f,17f,12f,21f) }
   "history"->{ c.drawCircle(12f,12f,9f,paint);line(12f,6f,12f,12f,16f,14f) }
   "calendar"->{ c.drawRoundRect(3f,5f,21f,22f,2f,2f,paint);line(3f,10f,21f,10f);line(8f,2f,8f,7f);line(16f,2f,16f,7f);line(8f,15f,11f,15f);line(15f,15f,17f,15f) }
   "wallet"->{ c.drawRoundRect(3f,5f,21f,21f,3f,3f,paint);c.drawRoundRect(14f,10f,22f,16f,1f,1f,paint);line(5f,5f,17f,2f) }
   "weather"->{ c.drawCircle(7f,7f,4f,paint);val p=Path().apply { moveTo(5f,20f);cubicTo(-1f,15f,4f,10f,8f,12f);cubicTo(12f,4f,20f,8f,19f,13f);cubicTo(25f,15f,22f,20f,18f,20f);close() };c.drawPath(p,paint) }
   "arrow"->line(9f,5f,16f,12f,9f,19f)
   "down"->line(6f,9f,12f,15f,18f,9f)
   else->{ c.drawRoundRect(4f,3f,20f,21f,3f,3f,paint);line(8f,8f,16f,8f);line(8f,12f,16f,12f);line(8f,16f,13f,16f) }
  }
  c.restore()
 }
 override fun isStateful()=true
 override fun onStateChange(state:IntArray):Boolean { invalidateSelf();return true }
 override fun setAlpha(alpha:Int) { paint.alpha=alpha }
 override fun setColorFilter(filter:ColorFilter?) { paint.colorFilter=filter }
 @Deprecated("Deprecated in Android") override fun getOpacity()=PixelFormat.TRANSLUCENT
}
