package ua.ducksolar.b2.client

import android.content.Context
import android.graphics.*
import android.view.MotionEvent
import android.view.View
import android.view.ScaleGestureDetector
import android.view.GestureDetector
import org.json.JSONArray
import org.json.JSONObject
import kotlin.math.*
import java.util.Locale

/** Dimensional values use the left axis; PF has an independent 0..1 axis. */
class HistoryChart(context:Context,private val points:List<JSONObject>,private val fields:List<JSONObject>,private val bars:Boolean,private val colors:Map<String,Int>,private val lineWidth:Float,private val detail:(String)->Unit):View(context) {
 private val paint=Paint(Paint.ANTI_ALIAS_FLAG)
 private var zoom=1.0;private var offset=0.0;private var downX=0f;private var downY=0f;private var lastX=0f;private var dragging=false
 private var selected:Int?=null
 private val pinch=ScaleGestureDetector(context,object:ScaleGestureDetector.SimpleOnScaleGestureListener() {
  override fun onScale(detector:ScaleGestureDetector):Boolean {
   val fraction=((detector.focusX-55*d)/plotWidth()).toDouble().coerceIn(0.0,1.0)
   val focus=offset+fraction/zoom
   scale(detector.scaleFactor.toDouble());offset=(focus-fraction/zoom).coerceIn(0.0,1.0-1.0/zoom);return true
  }
  override fun onScaleBegin(detector:ScaleGestureDetector):Boolean { dragging=true;parent?.requestDisallowInterceptTouchEvent(true);return true }
 })
 private val gestures=GestureDetector(context,object:GestureDetector.SimpleOnGestureListener() {
  override fun onDown(event:MotionEvent)=true
  override fun onDoubleTap(event:MotionEvent):Boolean { reset();return true }
 })
 private val d=resources.displayMetrics.density
 private val dual=GraphUnits.dual(fields,bars)
 private val pfOnly=fields.isNotEmpty() && fields.all { it.optString("key")==GraphUnits.PF }
 private val rightInset get()=if(dual)48*d else 12*d
 private fun plotWidth()=(width-55*d-rightInset).coerceAtLeast(1f)
 private val fullStart=(points.firstOrNull()?.optDouble("x") ?: 0.0)-(if(bars).5 else 0.0)
 private val fullEnd=((points.lastOrNull()?.optDouble("x") ?: 1.0)+(if(bars).5 else 0.0)).coerceAtLeast(fullStart+1)
 private fun range():Pair<Double,Double> { val span=(fullEnd-fullStart)/zoom;return (fullStart+offset*(fullEnd-fullStart)) to span }
 private fun value(row:JSONObject,key:String):Double? { if(row.isNull(key))return null;return row.optDouble(key,Double.NaN).takeIf { it.isFinite() && (key!=GraphUnits.PF || it in 0.0..1.0) } }
 fun scale(multiplier:Double) { zoom=(zoom*multiplier).coerceIn(1.0,64.0);offset=offset.coerceIn(0.0,1.0-1.0/zoom);invalidate() }
 fun reset() { zoom=1.0;offset=0.0;selected=null;invalidate() }
 fun move(fraction:Double) { offset=(offset+fraction/zoom).coerceIn(0.0,1.0-1.0/zoom);invalidate() }
 var events:List<JSONObject> = emptyList()
 override fun onDraw(c:Canvas) {
  super.onDraw(c);val left=55*d;val right=width-rightInset;val top=if(dual)24*d else 16*d;val bottom=height-34*d
  if(right<=left)return
  val (start,span)=range();val visible=points.filter { it.optDouble("x") in start..start+span }
  val values=visible.flatMap { row->fields.mapNotNull { value(row,it.getString("key")) } }
  if(values.isEmpty()) { paint.color=Color.GRAY;paint.textSize=14*d;c.drawText(ua.ducksolar.shared.UiLanguage.text("Немає даних у цьому діапазоні"),left,top+60*d,paint);return }
  val primary=if(pfOnly)values else visible.flatMap { row->fields.filter { it.optString("key")!=GraphUnits.PF }.mapNotNull { value(row,it.getString("key")) } }
  val axis=if(pfOnly)ChartAxis.Scale(0.0,1.0,.2) else ChartAxis.scale(primary.minOrNull() ?: 0.0,primary.maxOrNull() ?: 1.0,((bottom-top)/(32*d)).toInt().coerceIn(3,8),bars)
  val low=axis.low;val high=axis.high
  fun x(t:Double)=(left+(t-start)/span*(right-left)).toFloat()
  fun y(v:Double)=(bottom-(v-low)/(high-low)*(bottom-top)).toFloat()
  fun seriesY(key:String,v:Double)=if(key==GraphUnits.PF)(bottom-v*(bottom-top)).toFloat() else y(v)
  paint.style=Paint.Style.FILL;paint.textSize=10*d;paint.strokeWidth=d
  for(v in axis.ticks) { val py=y(v);paint.color=Color.rgb(222,230,235);c.drawLine(left,py,right,py,paint);paint.color=Color.DKGRAY
   val label=axis.label(v);paint.textAlign=Paint.Align.RIGHT;c.drawText(ua.ducksolar.shared.UiLanguage.text(label),left-5*d,py+3*d,paint);paint.textAlign=Paint.Align.LEFT
  }
  if(dual) {
   paint.color=colors[GraphUnits.PF] ?: Color.rgb(137,82,196)
   paint.textAlign=Paint.Align.LEFT;c.drawText(ua.ducksolar.shared.UiLanguage.text("PF"),right+6*d,top-12*d,paint)
   for(v in ChartAxis.Scale(0.0,1.0,.2).ticks)c.drawText(ua.ducksolar.shared.UiLanguage.text(String.format(Locale.getDefault(),"%.1f",v)),right+6*d,seriesY(GraphUnits.PF,v)+3*d,paint)
  }
  for(event in events) {
   val position=event.optDouble("x",Double.NaN)
   if(position.isFinite() && position in start..start+span) {
    val px=x(position);paint.color=if(event.optString("code")=="grid")Color.rgb(211,115,47) else Color.rgb(99,117,151)
    paint.alpha=100;paint.pathEffect=DashPathEffect(floatArrayOf(3*d,3*d),0f);c.drawLine(px,top+8*d,px,bottom,paint);paint.pathEffect=null;paint.alpha=255
    c.drawCircle(px,top+4*d,3*d,paint)
   }
  }
  val target=((right-left)/(70*d)).toInt().coerceIn(2,6)
  val ticks=if(bars) {
   val step=ChartAxis.scale(0.0,span,target).step.coerceAtLeast(1.0).toInt()
   visible.filter { (it.optDouble("x").roundToInt()+1)%step==0 || it===visible.firstOrNull() }.map { ChartAxis.Tick(it.optDouble("x"),ChartAxis.categoryLabel(it.optString("label"))) }
  } else ChartAxis.timeTicks(start,start+span,target)
  var previousRight=Float.NEGATIVE_INFINITY
  for(tick in ticks) {
   val label=tick.label;val w=paint.measureText(ua.ducksolar.shared.UiLanguage.text(label));val px=(x(tick.x)-w/2).coerceIn(left,max(left,right-w))
   if(px<previousRight+8*d)continue
   paint.color=Color.DKGRAY;c.drawText(ua.ducksolar.shared.UiLanguage.text(label),px,bottom+20*d,paint);previousRight=px+w
  }
  c.save();c.clipRect(left,top,right,bottom)
  fields.forEachIndexed { index,field->
   val key=field.getString("key");paint.color=colors[key] ?: if(key==GraphUnits.PF)Color.rgb(137,82,196) else Color.BLUE;paint.strokeWidth=lineWidth*d
   if(bars) {
    val step=(right-left)/max(1,visible.size);val barWidth=step/(fields.size+1)
    for(row in visible) {
     val v=value(row,key) ?: continue;val px=x(row.optDouble("x"))-barWidth*fields.size/2+index*barWidth
     val partial=key=="actual" && row.optBoolean("actual_partial")
     paint.alpha=if(partial)130 else 255
     paint.style=Paint.Style.FILL;c.drawRect(px,min(y(v),y(0.0)),px+barWidth*.8f,max(y(v),y(0.0)),paint)
     paint.alpha=255
     if(partial) { paint.style=Paint.Style.STROKE;paint.strokeWidth=d;c.drawRect(px,min(y(v),y(0.0)),px+barWidth*.8f,max(y(v),y(0.0)),paint) }
    }
   } else {
    paint.style=Paint.Style.STROKE;val path=Path();var previous=false
    for(row in points) {
     val v=value(row,key);val gaps=row.optJSONArray("breaks") ?: JSONArray();val broken=(0 until gaps.length()).any { gaps.optString(it)==key }
     if(v==null) { if(key!="pv_a" || broken)previous=false;continue }
     val px=x(row.optDouble("x"));val py=seriesY(key,v)
     if(!previous || broken)path.moveTo(px,py) else path.lineTo(px,py)
     previous=true
    }
    c.drawPath(path,paint)
   }
  }
  paint.style=Paint.Style.FILL
  selected?.let { i->paint.color=Color.GRAY;paint.strokeWidth=d;c.drawLine(x(points[i].optDouble("x")),top,x(points[i].optDouble("x")),bottom,paint) }
  c.restore()
 }
 override fun performClick():Boolean { super.performClick();return true }
 override fun onTouchEvent(event:MotionEvent):Boolean {
  pinch.onTouchEvent(event);gestures.onTouchEvent(event)
  if(event.actionMasked==MotionEvent.ACTION_POINTER_UP) { val remaining=if(event.actionIndex==0)1 else 0;lastX=event.getX(remaining);downX=lastX;downY=event.getY(remaining) }
  if(pinch.isInProgress || event.pointerCount>1)return true
  when(event.actionMasked) {
   MotionEvent.ACTION_DOWN->{ downX=event.x;downY=event.y;lastX=event.x;dragging=false;return true }
   MotionEvent.ACTION_MOVE->{
    if(zoom>1 && abs(event.x-downX)>12*d && abs(event.x-downX)>abs(event.y-downY)) { dragging=true;parent.requestDisallowInterceptTouchEvent(true) }
    if(dragging) { move((-(event.x-lastX)/plotWidth()).toDouble());lastX=event.x }
    return true
   }
   MotionEvent.ACTION_UP->{
    parent.requestDisallowInterceptTouchEvent(false)
    if(!dragging && points.isNotEmpty()) {
     performClick();val (start,span)=range();val t=start+((event.x-55*d)/plotWidth()).coerceIn(0f,1f)*span
     val i=points.indices.minByOrNull { abs(points[it].optDouble("x")-t) }!!;selected=i;val row=points[i]
     detail(events.filter { abs(it.optDouble("x")-t)<=span*14*d/plotWidth() }.joinToString("\n") { it.optString("time")+" • "+it.optString("message") }.let { if(it.isBlank())"" else it+"\n" }+row.optString("label")+"\n"+fields.joinToString("\n") { f->
      val k=f.getString("key");val v=value(row,k);var text=f.getString("label")+": "+(if(v==null)"— (немає даних)" else String.format(Locale.getDefault(),"%.3f %s",v,f.getString("unit")))
      val direction=if(k=="grid_import_w")"import" else if(k=="grid_export_w")"export" else ""
      if(direction.isNotEmpty())text+=" • "+when(row.optString("grid_${direction}_source")) { "measured"->"виміряно";"estimated"->"розраховано";else->"джерело недоступне" }+" • "+row.optString("grid_${direction}_origin")
      if(bars)row.optJSONObject("coverage_seconds")?.let { if(it.has(k))text+=" • покриття "+DurationText.seconds(it.optDouble(k)) }
      if(k=="actual" && row.optBoolean("actual_partial"))text+=" • неповні дані"
      text
     });invalidate()
    };return true
   }
   MotionEvent.ACTION_CANCEL->{ parent.requestDisallowInterceptTouchEvent(false);return true }
  };return true
 }
}
