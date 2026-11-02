package ua.ducksolar.b2.client

/** Distances are along the actual curved route, never its straight chord. */
object FlowHighlights {
 const val CYCLE_NS=2200000000L
 fun centers(length:Float,phase:Float,reverse:Boolean=false):FloatArray {
  val p=((if(reverse)-phase else phase)%1f+1f)%1f
  return floatArrayOf(p*length,((p+.5f)%1f)*length)
 }
 fun brightness(position:Float,centers:FloatArray,length:Float):Float {
  if(length<=0)return 0f
  val distance=centers.minOf { val d=kotlin.math.abs(position-it);minOf(d,length-d) }
  return (1f-distance/(length*.075f)).coerceIn(0f,1f)
 }
}
