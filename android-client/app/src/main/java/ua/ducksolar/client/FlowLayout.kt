package ua.ducksolar.b2.client
import android.graphics.Path
import android.graphics.RectF

/** Larger data cards, with four independent routes in a compact open corridor. */
object FlowLayout {
 data class Layout(val cards:Map<String,RectF>,val inverter:RectF,val routes:List<Path>,val information:RectF,val height:Float)
 fun create(fontScale:Float):Layout {
  val f=fontScale.coerceAtLeast(1f)
  fun upper(x:Float,endX:Float):Path {
   val sign=if(endX>x)1f else -1f
   return Path().apply { moveTo(x,172f*f);lineTo(x,188f*f);quadTo(x,198f*f,x+sign*10f,198f*f);lineTo(endX,198f*f) }
  }
  fun lower(x:Float,endX:Float):Path {
   val sign=if(endX>x)1f else -1f
   return Path().apply { moveTo(x,222f*f);lineTo(endX-sign*10f,222f*f);quadTo(endX,222f*f,endX,232f*f);lineTo(endX,258f*f) }
  }
  return Layout(linkedMapOf("pv" to RectF(0f,0f,174f,172f*f),"grid" to RectF(186f,0f,360f,172f*f),
   "battery" to RectF(0f,258f*f,174f,494f*f),"load" to RectF(186f,258f*f,360f,494f*f)),
   RectF(150f,182f*f,210f,238f*f),listOf(
    upper(87f,157f),upper(273f,203f),
    lower(157f,87f),lower(203f,273f)),
   RectF(0f,506f*f,360f,594f*f),596f*f)
 }
}
