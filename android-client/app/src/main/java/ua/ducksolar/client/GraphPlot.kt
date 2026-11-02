package ua.ducksolar.b2.client

import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import android.view.View
import android.widget.*
import org.json.JSONObject

/** One dimensional group plus optional PF on its own 0..1 axis. */
class GraphPlot(private val activity:Activity,private val result:JSONObject,private val colors:Map<String,Int>,private val width:Float,private val height:Int) {
 val body=LinearLayout(activity).apply { orientation=LinearLayout.VERTICAL;setBackgroundColor(Color.WHITE) }
 private val detail=TextView(activity).apply { text="Торкніться точки • два пальці — масштаб • подвійне торкання — скинути";textSize=12f;setPadding(8,4,8,4) }
 private val chartHost=FrameLayout(activity)
 private val legend=LinearLayout(activity)
 private val points=result.getJSONArray("points").let { rows->(0 until rows.length()).map { rows.getJSONObject(it) } }
 private val groups=result.getJSONArray("fields").let { rows->(0 until rows.length()).map { rows.getJSONObject(it) }.let { GraphUnits.groups(it) } }
 private val enabled=mutableSetOf<String>()
 private var unit=""
 var chart:HistoryChart?=null;private set
 init {
  if(points.isEmpty() || groups.isEmpty()) { body.addView(TextView(activity).apply { text="Немає даних за вибраний період" }) }
  else {
   groups.values.flatten().forEach { enabled.add(it.getString("key")) }
   val controls=LinearLayout(activity)
   val units=Spinner(activity).apply { adapter=ArrayAdapter(activity,android.R.layout.simple_spinner_dropdown_item,groups.map { (key,fields)->GraphUnits.label(key,fields) }) }
   controls.addView(units,LinearLayout.LayoutParams(0,44.dp(),1f))
   if(activity !is GraphFullscreenActivity)Button(activity).apply { text="⛶";contentDescription="Повноекранний графік";isAllCaps=false;controls.addView(this,LinearLayout.LayoutParams(56.dp(),44.dp()));setOnClickListener { GraphFullscreenActivity.result=result;GraphFullscreenActivity.colors=colors;GraphFullscreenActivity.lineWidth=this@GraphPlot.width;activity.startActivity(Intent(activity,GraphFullscreenActivity::class.java)) } }
   body.addView(controls)
   body.addView(HorizontalScrollView(activity).apply { isHorizontalScrollBarEnabled=false;addView(legend) })
   body.addView(chartHost,LinearLayout.LayoutParams(-1,height));body.addView(detail)
   val keys=groups.values.flatten().map { it.optString("key") }.toSet()
   val energySummary=if(!result.optBoolean("suppress_summary") && (result.optString("mode")=="energy" || result.optString("kind")=="bars" || ("pv_w" in keys && "output_w" in keys)))GraphEnergySummary(activity,result) else null
   energySummary?.let { body.addView(it,LinearLayout.LayoutParams(-1,-2)) }
   result.optJSONObject("house_meter")?.let { HouseMeterView.add(activity,body,it) }
   body.viewTreeObserver.addOnGlobalLayoutListener {
    var ancestor=body.parent;var viewport:View?=null
    while(ancestor is View) { if(ancestor is ScrollView) { viewport=ancestor;break };ancestor=ancestor.parent }
    if(viewport==null)viewport=activity.window.decorView.findViewById(android.R.id.content)
    val top=IntArray(2);val bound=IntArray(2);chartHost.getLocationOnScreen(top);viewport?.getLocationOnScreen(bound)
    // Keep the plot readable on small phones. Totals remain immediately below
    // it in the same scroll container rather than shrinking the plot.
    val scrollOffset=(viewport as? ScrollView)?.scrollY ?: 0
    val available=(bound[1]+(viewport?.height ?: height)-top[1]-scrollOffset-36.dp()).coerceAtLeast(160.dp())
    if(chartHost.layoutParams.height!=available) { chartHost.layoutParams=chartHost.layoutParams.apply { this.height=available } }
   }
   // Draw once immediately. The Spinner's initial callback must not replace
   // an already measured chart with a fresh, not-yet-laid-out view.
   unit=groups.keys.first();updateLegend();draw()
   units.onItemSelectedListener=object:AdapterView.OnItemSelectedListener {
    override fun onNothingSelected(parent:AdapterView<*>?) {}
    override fun onItemSelected(parent:AdapterView<*>?,view:View?,position:Int,id:Long) { val next=groups.keys.elementAt(position);if(unit!=next) { unit=next;updateLegend();draw() } }
   }
  }
 }
 private fun Int.dp()=(this*activity.resources.displayMetrics.density).toInt()
 private fun updateLegend() {
  legend.removeAllViews()
  groups.getValue(unit).forEach { field->
   val key=field.getString("key")
   CheckBox(activity).apply { text=field.getString("label");textSize=12f;isChecked=key in enabled;setTextColor(colors[key] ?: if(key==GraphUnits.PF)Color.rgb(137,82,196) else Color.BLUE);legend.addView(this);setOnCheckedChangeListener { _,checked->if(checked)enabled.add(key) else enabled.remove(key);draw() } }
  }
 }
 private fun draw() {
  chartHost.removeAllViews()
  chart=HistoryChart(activity,points,groups.getValue(unit).filter { it.getString("key") in enabled },result.getString("kind")=="bars",colors,width) { detail.text=it }
  result.optJSONArray("events")?.let { rows -> chart?.events=(0 until rows.length()).map { rows.getJSONObject(it) } }
  chartHost.addView(chart,FrameLayout.LayoutParams(-1,-1))
 }
}

class GraphFullscreenActivity:ua.ducksolar.shared.LocalizedActivity() {
 companion object { var result:JSONObject?=null;var colors:Map<String,Int> = emptyMap();var lineWidth=1.5f }
 override fun onCreate(state:Bundle?) {
  super.onCreate(state)
  val root=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL;setPadding(8,0,8,0) };setContentView(root)
  Button(this).apply { text="‹ Графіки";isAllCaps=false;root.addView(this,LinearLayout.LayoutParams(-1,(40*resources.displayMetrics.density).toInt()));setOnClickListener { finish() } }
  result?.let { value->
   val plot=GraphPlot(this,value,colors,lineWidth,(resources.displayMetrics.heightPixels-200*resources.displayMetrics.density).toInt().coerceAtLeast((160*resources.displayMetrics.density).toInt()))
   root.addView(ScrollView(this).apply { isFillViewport=true;addView(plot.body) },LinearLayout.LayoutParams(-1,0,1f))
  }
   ?:root.addView(TextView(this).apply { text="Поверніться до графіків після перезапуску застосунку" })
 }
 override fun onDestroy() { if(isFinishing) { result=null;colors=emptyMap() };super.onDestroy() }
}
