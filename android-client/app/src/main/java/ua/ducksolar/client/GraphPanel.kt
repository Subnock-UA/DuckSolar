package ua.ducksolar.b2.client

import android.app.Activity
import android.graphics.Color
import android.os.Handler
import android.os.Looper
import android.widget.*
import org.json.JSONArray
import org.json.JSONObject
import java.time.LocalDate

class GraphPanel(private val activity:Activity,private val parent:LinearLayout) {
 private val prefs=activity.getSharedPreferences("Graphs",Activity.MODE_PRIVATE)
 private val handler=Handler(Looper.getMainLooper())
 private var visible=false;private var running=false;private var shown="";private var last:JSONObject?=null
 private val names=linkedMapOf("pv_w" to "PV", "output_w" to "Навантаження", "battery_v" to "Напруга АКБ", "battery_pct" to "Заряд АКБ", "charge_a" to "Струм заряду", "discharge_a" to "Струм розряду", "grid_v" to "Напруга мережі", "grid_hz" to "Частота мережі", "grid_import_w" to "Імпорт", "grid_export_w" to "Експорт", "pv_v" to "Напруга PV", "pv_a" to "Струм PV", "output_va" to "Вихідна повна потужність", "output_pf" to "Коефіцієнт потужності PF", "output_v" to "Вихідна напруга", "output_hz" to "Вихідна частота", "load_pct" to "Навантаження, %", "temperature_c" to "Температура", "battery_charge_w" to "Потужність заряду АКБ")
 private val presets=linkedMapOf("PV і навантаження" to listOf("pv_w","output_w"),"АКБ" to listOf("battery_v","charge_a","discharge_a"),"Мережа" to listOf("grid_v","grid_hz"),"Потоки мережі" to listOf("grid_import_w","grid_export_w"),"PV" to listOf("pv_w","pv_v","pv_a"),"Вихід" to listOf("output_w","output_va","output_pf","output_v","output_hz","load_pct"),"Напруги" to listOf("pv_v","battery_v","grid_v","output_v"))
 private val selected=linkedSetOf<String>()
 private val energyPresets=linkedMapOf("Генерація і споживання" to listOf("pv_w","output_w"),"Імпорт і експорт" to listOf("grid_import_w","grid_export_w"),"Усі потоки" to listOf("pv_w","output_w","grid_import_w","grid_export_w"))
 private fun graphPresets()=if(mode.selectedItemPosition==1)energyPresets else presets
 private fun groupKey()=if(mode.selectedItemPosition==1)"energy_group" else "group"
 private val palette=listOf(Color.rgb(217,161,24),Color.rgb(51,132,208),Color.rgb(56,157,100),Color.rgb(181,72,120),Color.rgb(111,80,176),Color.rgb(229,115,35),Color.rgb(45,145,151))
 private val colors=names.keys.mapIndexed { i,k->k to prefs.getInt("color/$k",palette[i%palette.size]) }.toMap().toMutableMap()
 private lateinit var groupSpinner:Spinner
 private val periods=listOf("day","month","year","all");private val sources=listOf("Auto","Local","SmartESS")
 private lateinit var mode:Spinner;private lateinit var period:Spinner;private lateinit var source:Spinner;private lateinit var date:EditText;private lateinit var status:TextView;private lateinit var selection:TextView;private lateinit var output:LinearLayout;private lateinit var refresh:Button;private lateinit var cancel:Button;private lateinit var parameters:Button;private lateinit var automatic:CheckBox
 private lateinit var controller:GraphController
 private var customWindow=prefs.getBoolean("custom_window",false)
 private var windowStart=prefs.getString("window_start","08:00") ?: "08:00"
 private var windowEnd=prefs.getString("window_end","18:00") ?: "18:00"
 private lateinit var windowButton:Button
 private var width=prefs.getFloat("width",1.5f)
 private fun label(body:LinearLayout,value:String,size:Float=14f)=TextView(activity).apply { text=value;textSize=size;setTextColor(Color.rgb(38,54,65));setPadding(0,10,0,10);setTextIsSelectable(true);body.addView(this) }
 private fun button(body:LinearLayout,title:String,action:()->Unit)=Button(activity).apply { text=title;isAllCaps=false;body.addView(this);setOnClickListener { action() } }
 private fun choiceAdapter(values:List<String>)=object:ArrayAdapter<String>(activity,android.R.layout.simple_spinner_dropdown_item,values) {
  override fun getView(position:Int,convertView:android.view.View?,parent:android.view.ViewGroup):android.view.View=super.getView(position,convertView,parent).apply {
   if(this is TextView) { textSize=14f;setSingleLine();ellipsize=android.text.TextUtils.TruncateAt.END;setPadding(4.dp(),0,4.dp(),0) }
  }
 }
 private fun spinner(body:LinearLayout,values:List<String>)=Spinner(activity).apply { adapter=choiceAdapter(values);body.addView(this) }
 init {
  parent.setPadding(0,8.dp(),0,16.dp())
  parent.post { AppStyle.apply(parent) }
  val saved=JSONArray(prefs.getString("fields","[\"pv_w\",\"output_w\"]"));for(i in 0 until saved.length())if(names.containsKey(saved.optString(i)))selected.add(saved.getString(i));if(selected.isEmpty())selected.addAll(presets.values.first())
  val top=LinearLayout(activity);parent.addView(top)
  period=spinner(top,listOf("День","Місяць","Рік","Увесь час"));period.layoutParams=LinearLayout.LayoutParams(0,44.dp(),1f);period.setSelection(prefs.getInt("period",0).coerceIn(0,3))
  mode=spinner(top,listOf("Зміна показників","Енергія за період"))
  mode.adapter=object:ArrayAdapter<String>(activity,android.R.layout.simple_spinner_dropdown_item,listOf("Зміна показників","Енергія за період")) {
   override fun getView(position:Int,convertView:android.view.View?,parent:android.view.ViewGroup):android.view.View =
    (super.getView(position,convertView,parent) as TextView).apply { textSize=12f;setSingleLine(false);maxLines=2;setPadding(4.dp(),0,4.dp(),0) }
  }
  mode.layoutParams=LinearLayout.LayoutParams(0,44.dp(),1f);mode.setSelection(prefs.getInt("mode",0).coerceIn(0,1))
  period.onItemSelectedListener=object:AdapterView.OnItemSelectedListener {
   override fun onNothingSelected(parent:AdapterView<*>?) {}
   override fun onItemSelected(parent:AdapterView<*>?,view:android.view.View?,position:Int,id:Long) {
    if(position>=2)mode.setSelection(1)
    mode.isEnabled=position<2 && !running
    if(::windowButton.isInitialized)windowButton.visibility=if(position==0)android.view.View.VISIBLE else android.view.View.GONE
   }
  }
  parameters=Button(activity).apply { text="⚙";contentDescription="Налаштування графіка";top.addView(this,LinearLayout.LayoutParams(52.dp(),44.dp()));setOnClickListener { settings() } }
  val navigation=LinearLayout(activity);parent.addView(navigation)
  fun shift(step:Long) {
   try { val day=LocalDate.parse(date.text.toString().trim());date.setText(when(period.selectedItemPosition) { 0->day.plusDays(step);1->day.plusMonths(step);else->day.plusYears(step) }.toString());if(!running)start() } catch(_:Exception) { status.text="Оберіть дату" }
  }
  Button(activity).apply { text="‹";navigation.addView(this,LinearLayout.LayoutParams(44.dp(),44.dp()));setOnClickListener { shift(-1) } }
  date=EditText(activity).apply { setSingleLine();textSize=15f;setText(prefs.getString("date",LocalDate.now().toString()));navigation.addView(this,LinearLayout.LayoutParams(0,44.dp(),1f)) }
  PeriodPicker.bind(activity,date,{ periods[period.selectedItemPosition] })
  Button(activity).apply { text="›";navigation.addView(this,LinearLayout.LayoutParams(44.dp(),44.dp()));setOnClickListener { shift(1) } }
  windowButton=Button(activity).apply { isAllCaps=false;contentDescription="Часовий проміжок дня";navigation.addView(this,LinearLayout.LayoutParams(64.dp(),44.dp()));setOnClickListener { windowPicker() } }
  windowLabel()
  source=Spinner(activity).apply { adapter=ArrayAdapter(activity,android.R.layout.simple_spinner_dropdown_item,listOf("Auto — Local + ESS","Local","SmartESS"));setSelection(prefs.getInt("source",0).coerceIn(0,2)) }
  automatic=CheckBox(activity).apply { text="Автооновлення сьогодні (30 с)";isChecked=prefs.getBoolean("automatic",false) }
  selection=TextView(activity);saveSelection()
  val actions=LinearLayout(activity);parent.addView(actions)
  val group=spinner(actions,graphPresets().keys.toList()+"Власний набір");group.layoutParams=LinearLayout.LayoutParams(0,44.dp(),1f)
  groupSpinner=group
  group.setSelection(prefs.getInt(groupKey(),0).coerceIn(0,graphPresets().size))
  group.onItemSelectedListener=object:AdapterView.OnItemSelectedListener {
   override fun onNothingSelected(parent:AdapterView<*>?) {}
   override fun onItemSelected(parent:AdapterView<*>?,view:android.view.View?,position:Int,id:Long) {
    val choices=graphPresets();prefs.edit().putInt(groupKey(),position).apply()
    if(position<choices.size) { selected.clear();selected.addAll(choices.values.elementAt(position));saveSelection() }
   }
  }
  refresh=Button(activity).apply { text="Побудувати";isAllCaps=false;actions.addView(this,LinearLayout.LayoutParams(112.dp(),44.dp()));setOnClickListener { start() } }
  cancel=Button(activity).apply { text="Скасувати";isAllCaps=false;visibility=android.view.View.GONE;this@GraphPanel.parent.addView(this);setOnClickListener { controller.cancel() } }
  status=label(parent,"Оберіть період і побудуйте графік",12f)
  output=LinearLayout(activity).apply { orientation=LinearLayout.VERTICAL;this@GraphPanel.parent.addView(this) }
  controller=GraphController(activity) { show(it) }
  mode.onItemSelectedListener=object:AdapterView.OnItemSelectedListener {
   override fun onNothingSelected(parent:AdapterView<*>?) {}
   override fun onItemSelected(parent:AdapterView<*>?,view:android.view.View?,position:Int,id:Long) {
    val choices=graphPresets()
    group.adapter=choiceAdapter(choices.keys.toList()+"Власний набір")
    group.setSelection(prefs.getInt(groupKey(),0).coerceIn(0,choices.size))
   }
  }
 }
 private fun saveSelection() { prefs.edit().putString("fields",JSONArray(selected.toList()).toString()).apply();selectionIfReady() }
 private fun selectionIfReady() { if(::selection.isInitialized)selection.text="Параметри: "+selected.joinToString { names[it] ?: it } }
 private fun start() {
  try {
   val anchor=LocalDate.parse(date.text.toString().trim()).toString();val p=period.selectedItemPosition;val s=source.selectedItemPosition
   prefs.edit().putInt("period",p).putInt("source",s).putString("date",anchor).putInt("mode",mode.selectedItemPosition).apply()
   shown="";if(last!=null)status.text="Будується новий період • нижче попередній графік";controller.start(periods[p],anchor,sources[s],JSONArray(selected.toList()),if(p>=2 || mode.selectedItemPosition==1)"energy" else "power",if(p==0 && customWindow)windowStart else "",if(p==0 && customWindow)windowEnd else "")
  } catch(_:Exception) { status.text="Вкажіть дату РРРР-ММ-ДД" }
 }
 private fun show(job:JSONObject) {
  if(job.optString("state")=="complete" && !job.has("result"))return
  if(job.optString("state")!="running" && shown.isNotEmpty() && shown==job.optString("query_id"))return
  running=job.optString("state")=="running";refresh.isEnabled=!running;cancel.isEnabled=running;cancel.visibility=if(running)android.view.View.VISIBLE else android.view.View.GONE;parameters.isEnabled=!running;period.isEnabled=!running;mode.isEnabled=!running && period.selectedItemPosition<2;source.isEnabled=!running;date.isEnabled=!running;windowButton.isEnabled=!running
  if(job.optString("state")!="idle" && job.has("period")) { period.setSelection(periods.indexOf(job.getString("period")).coerceAtLeast(0));source.setSelection(sources.indexOf(job.getString("source")).coerceAtLeast(0));date.setText(job.optString("anchor"));mode.setSelection(if(job.optString("mode")=="energy")1 else 0);job.optJSONArray("fields")?.let { selected.clear();for(i in 0 until it.length())selected.add(it.getString(i));selectionIfReady() } }
  when(job.optString("state")) {
   "running"->{ status.text=AppStyle.job(job);last?.let { status.append(" • показано попередній ${it.optString("anchor")} (${it.optString("source")})") } }
   "error"->{ shown=job.optString("query_id");status.text="Графік не отримано: "+job.optString("error")+"\nДля часового проміжку дня потрібен Server a1.4.31 або новіший." }
   "cancelled"->{ shown=job.optString("query_id");status.text="Побудову скасовано" }
   "complete"->{
    val signature=job.optString("query_id");if(shown==signature)return;shown=signature
    last=job.getJSONObject("result");draw(last!!)
   }
  }
 }
 private fun draw(result:JSONObject) {
  output.removeAllViews();val array=result.getJSONArray("points");val points=(0 until array.length()).map { array.getJSONObject(it) }
  val interval=result.optJSONObject("window")?.let { " • "+it.optString("start").substring(11,16)+"–"+(if(it.optString("end").take(10)!=result.optString("anchor"))"24:00" else it.optString("end").substring(11,16)) } ?: ""
  status.text="${result.optString("anchor")}$interval • ${result.getString("source")} • ${points.size} точок"
  AppStyle.apply(output)
  if(points.isEmpty()) { label(output,"Немає даних за вибраний період і джерело");return }
  val plot=GraphPlot(activity,result,colors,width,(activity.resources.displayMetrics.heightPixels-270*activity.resources.displayMetrics.density).toInt().coerceAtLeast(280.dp()))
  output.addView(plot.body)

 }
 private fun windowLabel() { windowButton.text=if(customWindow)"Час ✓" else "Час";windowButton.contentDescription=if(customWindow)"Часовий проміжок дня $windowStart – $windowEnd" else "Часовий проміжок дня" }
 private fun windowPicker() {
  val body=LinearLayout(activity).apply { orientation=LinearLayout.VERTICAL;setPadding(16.dp(),8.dp(),16.dp(),8.dp()) }
  val all=CheckBox(activity).apply { text="Увесь день";isChecked=!customWindow;body.addView(this) }
  fun field(title:String,value:String):EditText=EditText(activity).apply {
   hint=title;setText(value);isFocusable=false;contentDescription=title;body.addView(this)
   setOnClickListener { val parts=text.toString().split(":");android.app.TimePickerDialog(activity,{ _,h,m->setText(String.format(java.util.Locale.ROOT,"%02d:%02d",h,m));all.isChecked=false },parts[0].toInt().coerceAtMost(23),parts[1].toInt(),true).show() }
  }
  val from=field("Початок проміжку",windowStart);val to=field("Кінець проміжку",windowEnd)
  button(body,"До кінця доби") { to.setText("24:00");all.isChecked=false }
  label(body,"Час інвертора: Київ. Графік і підсумки рахуються за обраний проміжок. Пропуски не замінюються нулями.",12f)
  ua.ducksolar.shared.LocalizedDialog.Builder(activity).setTitle("Часовий проміжок дня").setView(body).setNegativeButton("Скасувати",null).setPositiveButton("Застосувати") { _,_->
   val a=from.text.toString();val b=to.text.toString()
   if(!all.isChecked && a>=b) { ua.ducksolar.shared.LocalizedToast.makeText(activity,"Кінець має бути після початку",Toast.LENGTH_LONG).show();return@setPositiveButton }
   customWindow=!all.isChecked;windowStart=a;windowEnd=b
   prefs.edit().putBoolean("custom_window",customWindow).putString("window_start",a).putString("window_end",b).apply();windowLabel()
  }.show()
 }
 private fun Int.dp()=(this*activity.resources.displayMetrics.density).toInt()
 private fun settings() {
  val body=LinearLayout(activity).apply { orientation=LinearLayout.VERTICAL;setPadding(16.dp(),8.dp(),16.dp(),8.dp()) }
  (source.parent as? android.view.ViewGroup)?.removeView(source);(automatic.parent as? android.view.ViewGroup)?.removeView(automatic)
  label(body,"Джерело даних");body.addView(source);body.addView(automatic)
  button(body,"Власний набір параметрів") {
   val keys=names.keys.filter { mode.selectedItemPosition==0 || it in energyPresets.getValue("Усі потоки") };val checked=keys.map { it in selected }.toBooleanArray()
   ua.ducksolar.shared.LocalizedDialog.Builder(activity).setTitle("Параметри").setMultiChoiceItems(keys.map { names.getValue(it) }.toTypedArray(),checked) { _,i,value->checked[i]=value }.setPositiveButton("Застосувати") { _,_->
    if(checked.any { it }) { selected.clear();keys.forEachIndexed { i,key->if(checked[i])selected.add(key) };saveSelection();groupSpinner.setSelection(graphPresets().size);prefs.edit().putInt(groupKey(),graphPresets().size).apply() }
   }.setNegativeButton("Скасувати",null).show()
  }
  button(body,"Кольори й товщина ліній") { style() }
  button(body,"Перейти до сьогодні") { date.setText(LocalDate.now().toString()) }
  label(body,"Зміна показників — значення та їх зміни в часі; місяць — погодинні середні. Енергія за період — кВт·год: день по годинах, місяць по днях, рік і весь час по місяцях. Підсумки періоду показані під енергетичними графіками та графіком PV і споживання.",12f)
  ua.ducksolar.shared.LocalizedDialog.Builder(activity).setTitle("Налаштування графіка").setView(body).setPositiveButton("Готово") { _,_->prefs.edit().putInt("source",source.selectedItemPosition).putBoolean("automatic",automatic.isChecked).apply() }.show()
 }
 private fun style() {
  val body=LinearLayout(activity).apply { orientation=LinearLayout.VERTICAL }
  label(body,"Товщина ліній: $width")
  val slider=SeekBar(activity).apply { max=11;progress=(width*2-1).toInt().coerceIn(0,11);body.addView(this) }
  val field=spinner(body,names.values.toList());val color=spinner(body,listOf("Жовтий","Синій","Зелений","Рожевий","Фіолетовий","Помаранчевий","Бірюзовий"))
  button(body,"Застосувати колір параметра") { val key=names.keys.elementAt(field.selectedItemPosition);colors[key]=palette[color.selectedItemPosition];prefs.edit().putInt("color/$key",colors.getValue(key)).apply();last?.let { draw(it) } }
  ua.ducksolar.shared.LocalizedDialog.Builder(activity).setTitle("Вигляд").setView(body).setPositiveButton("Застосувати") { _,_->width=(slider.progress+1)/2f;prefs.edit().putFloat("width",width).apply();last?.let { draw(it) } }.setNegativeButton("Закрити",null).show()
 }
 private val tick=object:Runnable { override fun run() { if(!visible)return;if(automatic.isChecked && !running && period.selectedItemPosition==0 && date.text.toString()==LocalDate.now().toString())start();handler.postDelayed(this,30000) } }
 fun setVisible(value:Boolean) { visible=value;controller.setVisible(value);handler.removeCallbacks(tick);if(value)handler.postDelayed(tick,30000) }
 fun close() { visible=false;handler.removeCallbacksAndMessages(null);controller.close();last=null }
}
