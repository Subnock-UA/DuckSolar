package ua.ducksolar.b2.client

import android.graphics.*
import org.json.JSONObject

/** AGH PRO front casing; the RGB stripe is an estimate from fresh operation data. */
object InverterArtwork {
 const val BLUE=0xff2a8beb.toInt()
 const val RED=0xffee5261.toInt()
 const val PURPLE=0xffa46ae8.toInt()
 fun stripe(state:JSONObject?,metrics:JSONObject?,stale:Boolean):Int {
  if(stale || state==null || state.optBoolean("mode_stale",true))return BLUE
  fun value(key:String):Double {
   val m=metrics?.optJSONObject(key) ?: return Double.NaN
   return if(!m.optBoolean("stale") && m.optDouble("age_s",0.0)<=m.optDouble("valid_for_s",Double.POSITIVE_INFINITY) &&
    m.optString("quality","good") in listOf("good","estimated"))m.optDouble("value",Double.NaN) else Double.NaN
  }
  return when(state.optString("mode_code")) {
   "L"->BLUE
   "B"->{ val pv=value("pv.total_power");val discharge=value("battery.channels.main.discharge_current")
    if(discharge>0)RED else if(pv>=20 && discharge==0.0)PURPLE else if(pv.isFinite() && pv<20)RED else BLUE }
   else->BLUE
  }
 }
 private var cached:Map<Int,Bitmap>?=null
 @Synchronized private fun images(resources:android.content.res.Resources):Map<Int,Bitmap> {
  cached?.let { return it }
  val original=BitmapFactory.decodeResource(resources,R.drawable.inverter_agh_pro,BitmapFactory.Options().apply { inSampleSize=4;inScaled=false })
  return listOf(BLUE,RED,PURPLE).associateWith { recolor(original,it) }.also { cached=it;original.recycle() }
 }
 internal fun recolor(source:Bitmap,color:Int):Bitmap {
  val width=source.width;val height=source.height;val pixels=IntArray(width*height)
  source.getPixels(pixels,0,width,0,0,width,height)
  // Only the saturated red light in the approved bitmap is recolored. The casing,
  // dark display, control keys and original alpha remain exactly the same.
  for(y in (height*.08f).toInt() until (height*.38f).toInt())for(x in (width*.4f).toInt() until (width*.6f).toInt()) {
   val i=y*width+x;val pixel=pixels[i];val red=Color.red(pixel);val green=Color.green(pixel);val blue=Color.blue(pixel)
   if(red>100 && red>maxOf(green,blue)+8) {
    val strength=(red-minOf(green,blue))/255f
    fun channel(original:Int,target:Int,base:Int)=(original+(target-base)*strength).toInt().coerceIn(0,255)
    pixels[i]=Color.argb(Color.alpha(pixel),channel(red,Color.red(color),255),channel(green,Color.green(color),0),channel(blue,Color.blue(color),0))
   }
  }
  return Bitmap.createBitmap(pixels,width,height,Bitmap.Config.ARGB_8888)
 }
 fun draw(c:Canvas,r:RectF,color:Int,paint:Paint,resources:android.content.res.Resources) {
  val bitmap=images(resources)[color] ?: images(resources).getValue(BLUE)
  val scale=minOf(r.width()/bitmap.width,r.height()/bitmap.height)
  val width=bitmap.width*scale;val height=bitmap.height*scale
  val filtered=paint.isFilterBitmap;paint.isFilterBitmap=true;paint.shader=null;paint.alpha=255
  c.drawBitmap(bitmap,null,RectF(r.centerX()-width/2,r.centerY()-height/2,r.centerX()+width/2,r.centerY()+height/2),paint)
  paint.isFilterBitmap=filtered
 }
}
