package ua.ducksolar.b2.client

import android.content.Context
import android.content.ClipData
import android.content.ClipboardManager
import android.graphics.*
import android.view.View
import android.widget.Toast
import org.json.JSONObject
import java.util.Locale
import kotlin.math.*

/** Approved dashboard structure, driven only by the server's real metrics. */
class FlowDiagram(context:Context):View(context) {
 private val ink=Color.rgb(20,38,56)
 private val muted=Color.rgb(83,99,113)
 private val sun=Color.rgb(249,181,0)
 private val green=Color.rgb(30,163,97)
 private val violet=Color.rgb(155,115,244)
 private val blue=Color.rgb(42,139,235)
 private val paint=Paint(Paint.ANTI_ALIAS_FLAG)
 private val equipmentBitmap=BitmapFactory.decodeResource(resources,R.drawable.station_equipment)
 private fun equipment(c:Canvas,index:Int,rect:RectF) {
  val ranges=listOf(0f to .23f,.235f to .39f,.40f to .64f,.65f to .79f,.83f to .98f)
  val (left,right)=ranges[index];val src=Rect((equipmentBitmap.width*left).toInt(),(equipmentBitmap.height*.12f).toInt(),(equipmentBitmap.width*right).toInt(),(equipmentBitmap.height*.83f).toInt())
  val ratio=minOf(rect.width()/src.width(),rect.height()/src.height());val w=src.width()*ratio;val h=src.height()*ratio
  paint.style=Paint.Style.FILL;paint.alpha=if(stale)125 else 255
  c.drawBitmap(equipmentBitmap,src,RectF(rect.centerX()-w/2,rect.centerY()-h/2,rect.centerX()+w/2,rect.centerY()+h/2),paint);paint.alpha=255
 }
 private var metrics:JSONObject?=null
 private var stale=true
 private var name="—"
 private var stripe=InverterArtwork.BLUE
 private val highlight=Path()
 private var animationEnabled=false
 private var animationRunning=false
 private var initialized=false
 private val frame=object:Runnable { override fun run() { if(animationRunning) { invalidate();postOnAnimation(this) } } }
 private val measure=PathMeasure()
 private val point=FloatArray(2)
 private val tangent=FloatArray(2)
 fun setActive(active:Boolean) { animationEnabled=active;syncAnimation() }
 private fun syncAnimation() {
  if(!initialized)return
  val moving=listOf("pv.total_power","grid.import_power","grid.export_power","battery.channels.main.charge_current","battery.channels.main.discharge_current","output.active_power").any { active(it) }
  val run=animationEnabled && isAttachedToWindow && isShown && windowVisibility==VISIBLE && moving
  if(run==animationRunning)return
  animationRunning=run;removeCallbacks(frame);if(run)post(frame)
 }
 override fun onAttachedToWindow() { super.onAttachedToWindow();syncAnimation() }
 override fun onDetachedFromWindow() { animationRunning=false;removeCallbacks(frame);super.onDetachedFromWindow() }
 override fun onVisibilityChanged(changedView:View,visibility:Int) { super.onVisibilityChanged(changedView,visibility);syncAnimation() }
 override fun onWindowVisibilityChanged(visibility:Int) { super.onWindowVisibilityChanged(visibility);syncAnimation() }
 init {
  isFocusable=true
  setOnLongClickListener {
   val manager=context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
   manager.setPrimaryClip(ClipData.newPlainText("Duck Solar",contentDescription))
   ua.ducksolar.shared.LocalizedToast.makeText(context,"Показники скопійовано",Toast.LENGTH_SHORT).show();true
  }
  initialized=true
 }
 fun update(updatedMetrics:JSONObject?,outdated:Boolean,inverter:String,state:JSONObject?=null) {
  metrics=HomeMetrics.withDisplayCurrents(updatedMetrics);stale=outdated;name=inverter
  stripe=InverterArtwork.stripe(state,metrics,stale)
  contentDescription=listOf(name,if(stale)"Дані застарілі" else "Дані актуальні","PV: "+value("pv.total_power"),"Мережа: "+value("grid.import_power"),
   "АКБ: "+value("battery.channels.main.soc"),"Навантаження: "+value("output.active_power")).joinToString("\n")
  contentDescription=contentDescription.toString()+"\nPV напруга: "+value("pv.inputs.aggregate.voltage")+"\nМережа — імпорт: "+value("grid.import_power")+"; експорт: "+value("grid.export_power")+"; напруга: "+value("grid.phases.L1.voltage")+"\nВихідна напруга: "+value("output.phases.L1.voltage")+"\n"+HomeMetrics.batteryRows(metrics).joinToString("\n") { it.first+": "+HomeMetrics.text(it.second,stale) }
  contentDescription=contentDescription.toString()+"\nКоефіцієнт потужності PF: "+value("output.power_factor")+"\nPV струм: "+value("pv.inputs.aggregate.current")+"\nСтрум мережі: "+value("grid.phases.L1.current")+"\nСтрум навантаження: "+value("output.phases.L1.current")
  contentDescription=contentDescription.toString()+"\nЧастота мережі: "+value("grid.phases.L1.frequency")+"\nПовна потужність: "+value("output.apparent_power")+"\nЗалишок енергії: "+value("battery.channels.main.remaining_energy")+"\nТемпература інвертора: "+value("temperature.inverter")+"\nDC-шина: "+value("dc.bus_voltage")+"\nSCC: "+value("battery.scc_voltage")
  syncAnimation();invalidate()
 }
 private fun value(key:String):String = display(metrics?.optJSONObject(key))
 private fun active(key:String):Boolean {
  val m=metrics?.optJSONObject(key) ?: return false
  return !stale && !m.optBoolean("stale") && m.optDouble("age_s",0.0)<=m.optDouble("valid_for_s",Double.POSITIVE_INFINITY) && m.optString("quality","good") in listOf("good","estimated") && m.optDouble("value",Double.NaN).let { it.isFinite() && (if(key=="pv.total_power")it>=20.0 else it>0) }
 }
 private fun text(c:Canvas,value:String,x:Float,y:Float,size:Float=15f,bold:Boolean=false,center:Boolean=false,maxWidth:Float=150f,color:Int?=null,right:Boolean=false) {
  paint.style=Paint.Style.FILL;paint.color=color ?: if(bold)ink else muted
  paint.typeface=if(bold)Typeface.create("sans-serif",Typeface.BOLD) else Typeface.create("sans-serif",Typeface.NORMAL)
  paint.textSize=size*resources.configuration.fontScale*(360f*resources.displayMetrics.density/width.coerceAtLeast(1)).coerceAtLeast(1f);paint.textAlign=if(right)Paint.Align.RIGHT else if(center)Paint.Align.CENTER else Paint.Align.LEFT
  val shown=android.text.TextUtils.ellipsize(value,android.text.TextPaint(paint),maxWidth,android.text.TextUtils.TruncateAt.END).toString()
  c.drawText(ua.ducksolar.shared.UiLanguage.text(shown),x,y,paint)
 }
 private fun stroke(color:Int,width:Float=2.5f) { paint.style=Paint.Style.STROKE;paint.strokeWidth=width;paint.color=color;paint.strokeCap=Paint.Cap.ROUND;paint.strokeJoin=Paint.Join.ROUND;paint.pathEffect=null }
 private fun route(c:Canvas,path:Path,color:Int,on:Boolean,reverse:Boolean=false) {
  stroke(if(on)color else Color.rgb(170,183,194),4f)
  c.drawPath(path,paint)
  if(on) {
   measure.setPath(path,false)
   val phase=(android.os.SystemClock.elapsedRealtimeNanos()%FlowHighlights.CYCLE_NS)/FlowHighlights.CYCLE_NS.toFloat()
   val length=measure.length;val centers=FlowHighlights.centers(length,phase,reverse)
   // Two identical highlights, exactly half a path apart, including the bend.
   val half=length*.075f
   fun tint(amount:Float)=Color.rgb((Color.red(color)+(255-Color.red(color))*amount).toInt(),(Color.green(color)+(255-Color.green(color))*amount).toInt(),(Color.blue(color)+(255-Color.blue(color))*amount).toInt())
   fun ramp(a:Float,b:Float,center:Float) {
    val left=maxOf(0f,a);val right=minOf(length,b);if(right-left<.01f)return
    measure.getPosTan(left,point,null);val x0=point[0];val y0=point[1]
    measure.getPosTan(right,point,null)
    paint.shader=LinearGradient(x0,y0,point[0],point[1],tint((1f-abs(left-center)/half).coerceIn(0f,1f)),tint((1f-abs(right-center)/half).coerceIn(0f,1f)),Shader.TileMode.CLAMP)
    highlight.reset();measure.getSegment(left,right,highlight,true);c.drawPath(highlight,paint);paint.shader=null
   }
   for(center in centers)for(copy in listOf(center-length,center,center+length)) { ramp(copy-half,copy,copy);ramp(copy,copy+half,copy) }

  }
 }
 private fun display(metric:JSONObject?):String {
  if(metric==null)return "—"
  val row=JSONObject(metric.toString())
  val unit=row.optString("unit")
  val raw=row.optDouble("value",Double.NaN)
  val formatted=HomePowerText.format(raw,unit)
  if(formatted!=null && !row.isNull("value"))row.put("value",formatted).put("unit","")
  if(unit.isBlank() && raw.isFinite() && !row.isNull("value"))row.put("value",String.format(Locale.getDefault(),"%.2f",raw))
  return HomeMetrics.text(row,stale).removeSuffix(" • застаріле").let { if(it.startsWith("—"))"—" else it }
 }
 private fun card(c:Canvas,r:RectF) {
  paint.style=Paint.Style.FILL;paint.color=Color.WHITE;c.drawRoundRect(r,12f,12f,paint)
  stroke(Color.rgb(224,233,238),.8f);c.drawRoundRect(r,12f,12f,paint)
 }
 override fun onDraw(canvas:Canvas) {
  super.onDraw(canvas)
  val scale=width/360f;canvas.save();canvas.scale(scale,scale)
  val c=canvas;val f=resources.configuration.fontScale.coerceAtLeast(1f);val layout=FlowLayout.create(f)
  val exporting=active("grid.export_power") && !active("grid.import_power")
  val charging=active("battery.channels.main.charge_current");val discharging=active("battery.channels.main.discharge_current")
  route(c,layout.routes[0],sun,active("pv.total_power"))
  route(c,layout.routes[1],blue,active(if(exporting)"grid.export_power" else "grid.import_power") && !(active("grid.import_power") && active("grid.export_power")),exporting)
  route(c,layout.routes[2],violet,charging!=discharging,discharging)
  route(c,layout.routes[3],green,active("output.active_power"))
  for(r in layout.cards.values)card(c,r)
  fun title(key:String,label:String) { val r=layout.cards.getValue(key);text(c,label,r.left+12,r.top+24*f,13f,true,maxWidth=r.width()-24) }
  fun image(key:String,index:Int) { val r=layout.cards.getValue(key);equipment(c,index,RectF(r.left+10,r.top+33*f,r.left+62,r.top+85*f)) }
  fun row(key:String,y:Float,label:String,v:String,color:Int?=null) {
   val r=layout.cards.getValue(key);text(c,label,r.left+12,r.top+y*f,10f,maxWidth=82f)
   text(c,v,r.right-12,r.top+y*f,13f,true,maxWidth=78f,color=color,right=true)
  }
  val pv=layout.cards.getValue("pv");title("pv","PV");image("pv",0)
  text(c,value("pv.total_power"),pv.right-12,pv.top+65*f,21f,true,maxWidth=98f,color=sun,right=true)
  row("pv",118f,"Напруга",value("pv.inputs.aggregate.voltage"));row("pv",151f,"Струм",value("pv.inputs.aggregate.current"))
  val grid=layout.cards.getValue("grid");title("grid","Мережа");image("grid",4)
  val importing=active("grid.import_power");val exportActive=active("grid.export_power")
  if(importing && exportActive) {
   text(c,"Імпорт",grid.left+69,grid.top+43*f,10f,maxWidth=88f)
   text(c,value("grid.import_power"),grid.right-12,grid.top+66*f,21f,true,maxWidth=98f,right=true)
   text(c,"Експорт",grid.left+69,grid.top+80*f,10f,maxWidth=88f)
   text(c,value("grid.export_power"),grid.right-12,grid.top+103*f,21f,true,maxWidth=98f,right=true)
  } else {
   val key=if(exportActive)"grid.export_power" else "grid.import_power"
   text(c,if(exportActive)"Експорт" else "Імпорт",grid.left+69,grid.top+47*f,10f,maxWidth=88f)
   text(c,value(key),grid.right-12,grid.top+78*f,21f,true,maxWidth=98f,right=true)
  }
  row("grid",120f,"Напруга",value("grid.phases.L1.voltage"))
  row("grid",141f,"Струм",value("grid.phases.L1.current"))
  row("grid",162f,"Частота",value("grid.phases.L1.frequency"))
  val node=layout.inverter;val inverterRect=RectF(node.left-4,node.top-8*f,node.right+4,node.bottom+6*f)
  if(name=="DAXTROMN AGH 6.2 PRO")InverterArtwork.draw(c,inverterRect,stripe,paint,resources) else equipment(c,1,inverterRect)
  text(c,name,180f,253*f,9.5f,false,true,174f)
  val battery=layout.cards.getValue("battery");title("battery","Акумулятор");image("battery",3)
  text(c,"SOC БМС",battery.left+69,battery.top+47*f,10f,maxWidth=90f)
  text(c,value("battery.channels.main.soc"),battery.right-12,battery.top+78*f,23f,true,maxWidth=94f,color=violet,right=true)
  row("battery",112f,"Напруга",value("battery.channels.main.voltage"))
  row("battery",138f,"Заряд",value("battery.channels.main.charge_current"))
  row("battery",164f,"Розряд",value("battery.channels.main.discharge_current"))
  row("battery",190f,"До АКБ",display(HomeMetrics.power(metrics,"charge")),violet)
  row("battery",216f,"Від АКБ",display(HomeMetrics.power(metrics,"discharge")))
  val load=layout.cards.getValue("load");title("load","Навантаження");image("load",2)
  text(c,value("output.active_power"),load.right-12,load.top+78*f,21f,true,maxWidth=98f,color=green,right=true)
  row("load",112f,"Напруга",value("output.phases.L1.voltage"))
  row("load",134f,"Струм",value("output.phases.L1.current"))
  row("load",156f,"Частота",value("output.phases.L1.frequency"))
  row("load",178f,"Навантаження",value("output.load_percent"))
  row("load",200f,"Повна потужн.",value("output.apparent_power"))
  row("load",222f,"PF",value("output.power_factor"))
  val info=layout.information;card(c,info)
  text(c,"Залишок енергії",info.left+12,info.top+23*f,12f,maxWidth=195f)
  text(c,value("battery.channels.main.remaining_energy"),info.right-12,info.top+23*f,13f,true,maxWidth=130f,right=true)
  text(c,"Температура інвертора",info.left+12,info.top+51*f,12f,maxWidth=210f)
  text(c,value("temperature.inverter"),info.right-12,info.top+51*f,13f,true,maxWidth=100f,right=true)
  text(c,"DC-шина · "+value("dc.bus_voltage")+"     SCC · "+value("battery.scc_voltage"),info.left+12,info.top+78*f,11.5f,maxWidth=info.width()-24)
  canvas.restore()
 }
 override fun onMeasure(widthMeasureSpec:Int,heightMeasureSpec:Int) {
  val w=MeasureSpec.getSize(widthMeasureSpec);setMeasuredDimension(w,(w*FlowLayout.create(resources.configuration.fontScale).height/360f).toInt())
 }
}
