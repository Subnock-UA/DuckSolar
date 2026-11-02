package ua.ducksolar.b2.client

/** Presentation only. Original durations and timestamp values remain numeric. */
object DurationText {
 fun seconds(value:Double?):String {
  if(value==null || !value.isFinite() || value<0 || value>1e12)return "—"
  if(value<=1800.0) {
   val total=kotlin.math.floor(value+.5).toLong()
   val minutes=total/60;val seconds=total%60
   return if(minutes==0L)"$seconds с." else "$minutes хв."+(if(seconds>0)" $seconds с." else "")
  }
  val totalMinutes=kotlin.math.floor(value/60+.5).toLong()
  val hours=totalMinutes/60;val minutes=totalMinutes%60
  return if(hours>0)"$hours год. $minutes хв." else "$minutes хв."
 }
 fun hours(value:Double?):String=seconds(value?.times(3600))
 fun value(number:Double?,unit:String):String?=when(unit.trim().lowercase()) {
  "h","hr","hours","год","год."->hours(number)
  "min","minutes","хв","хв."->seconds(number?.times(60))
  "s","sec","seconds","с","с."->seconds(number)
  "ms","мс"->seconds(number?.div(1000))
  else->null
 }
}
