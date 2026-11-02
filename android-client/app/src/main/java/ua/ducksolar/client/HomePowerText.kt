package ua.ducksolar.b2.client
import java.util.Locale
import kotlin.math.abs
/** Display-only conversion; thresholds use the unrounded value. */
object HomePowerText {
 fun format(value:Double,unit:String):String? {
  if(!value.isFinite() || unit !in listOf("W","VA"))return null
  val kilo=abs(value)>=1000.0
  val n=if(kilo)value/1000.0 else value
  val digits=if(kilo)2 else if(n%1.0==0.0)0 else 1
  val number=String.format(Locale.getDefault(),"%.${digits}f",n)
  return number+" "+if(unit=="W") { if(kilo)"кВт" else "Вт" } else { if(kilo)"кВА" else "ВА" }
 }
}
