package ua.ducksolar.b2.client

import kotlin.math.*
import java.time.*
import java.time.format.DateTimeFormatter
import java.util.Locale

/** Rounded ticks; visible data always fit, even for negative/constant series. */
object ChartAxis {
 data class Scale(val low:Double,val high:Double,val step:Double) {
  val ticks:List<Double> get()=(0..((high-low)/step).roundToInt().coerceIn(1,100)).map { low+it*step }
  fun label(v:Double):String {
   val digits=max(0,-floor(log10(step)).toInt()).coerceAtMost(9)
   val n=if(abs(v)<step*1e-8)0.0 else v
   return String.format(Locale.getDefault(),"%.${digits}f",n)
  }
 }
 private fun nice(value:Double):Double {
  val unit=10.0.pow(floor(log10(value)));val part=value/unit
  return (when { part<=1.0->1.0;part<=2.0->2.0;part<=5.0->5.0;else->10.0 })*unit
 }
 fun scale(minimum:Double,maximum:Double,target:Int=7,zero:Boolean=false):Scale {
  var low=minimum;var high=maximum
  if(!low.isFinite() || !high.isFinite())return Scale(0.0,1.0,.2)
  if(low>high) { val temp=low;low=high;high=temp }
  if(zero) { low=min(0.0,low);high=max(0.0,high) }
  if(low==high) { val pad=max(abs(high)*.05,.1);low-=pad;high+=pad;if(zero && minimum>=0)low=0.0 }
  val step=nice((high-low)/target.coerceIn(2,10))
  val a=floor(low/step)*step;var b=ceil(high/step)*step
  if(b<=a)b=a+step
  return Scale(a,b,step)
 }
 fun categoryLabel(label:String):String=when {
  label.length==10 && label.getOrNull(4)=='-'->label.takeLast(2)+"."+label.substring(5,7)
  label.length==7 && label.getOrNull(4)=='-'->label.substring(5,7)+"."+label.take(4)
  label.contains('T')->try {
   val t=OffsetDateTime.parse(label);val ambiguous=ZoneId.of("Europe/Kyiv").rules.getValidOffsets(t.toLocalDateTime()).size>1
   label.substringAfter('T').take(5)+(if(ambiguous) " ${t.offset}" else "")
  } catch(_:Exception) { label.substringAfter('T').take(5) }
  label.contains(' ')->label.substringAfter(' ').take(5)
  else->label
 }
 data class Tick(val x:Double,val label:String)
 fun timeTicks(start:Double,end:Double,target:Int):List<Tick> {
  if(!start.isFinite() || !end.isFinite() || end<=start)return emptyList()
  val zone=ZoneId.of("Europe/Kyiv");val span=end-start
  val wanted=span/target.coerceIn(2,8)
  val minutes=listOf(1,2,5,10,15,30,60,120,180,360,720)
  val step=minutes.firstOrNull { it*60000.0>=wanted }
  val first=Instant.ofEpochMilli(start.toLong()).atZone(zone)
  var cursor=when {
   step!=null->first.toLocalDate().atStartOfDay(zone).plusMinutes((first.hour*60L+first.minute)/step*step)
   wanted<=86400000->first.toLocalDate().atStartOfDay(zone)
   wanted<=7*86400000->first.toLocalDate().with(java.time.temporal.TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY)).atStartOfDay(zone)
   wanted<=31*86400000.0->first.withDayOfMonth(1).toLocalDate().atStartOfDay(zone)
   else->first.withDayOfYear(1).toLocalDate().atStartOfDay(zone)
  }
  fun next(v:ZonedDateTime):ZonedDateTime=when { step!=null->v.plusMinutes(step.toLong());wanted<=86400000->v.plusDays(1);wanted<=7*86400000->v.plusWeeks(1);wanted<=31*86400000.0->v.plusMonths(1);else->v.plusYears(1) }
  val format=DateTimeFormatter.ofPattern(if(span<=2*86400000.0)"HH:mm" else if(span<=366*86400000.0)"dd.MM" else "MM.yyyy")
  val ticks=mutableListOf<Tick>();var guard=0
  while(cursor.toInstant().toEpochMilli()<=end && guard++<100) {
   val x=cursor.toInstant().toEpochMilli().toDouble();if(x>=start)ticks.add(Tick(x,cursor.format(format)+(if(span<=2*86400000.0 && zone.rules.getValidOffsets(cursor.toLocalDateTime()).size>1) " ${cursor.offset}" else "")));cursor=next(cursor)
  }
  return ticks
 }
}
