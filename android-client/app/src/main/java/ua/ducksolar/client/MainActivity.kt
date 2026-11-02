package ua.ducksolar.b2.client
import android.app.Activity
import android.os.*
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.text.InputType
import android.widget.*
import org.json.JSONObject
import java.util.concurrent.Executors

class MainActivity:ua.ducksolar.shared.LocalizedActivity() {
 companion object {
  private val worker=Executors.newSingleThreadExecutor()
 }
 private val handler=Handler(Looper.getMainLooper())
 private val pending=java.util.concurrent.atomic.AtomicBoolean(false)
 @Volatile private var visible=false
 private lateinit var networks:NetworkWatch
 private val reroutePending=java.util.concurrent.atomic.AtomicBoolean(false)
 private val reroute=object:Runnable {
  override fun run() {
   if(!visible)return
   if(pending.get()) { handler.postDelayed(this,1500);return }
   if(!reroutePending.compareAndSet(false,true))return
   worker.execute { try { if(visible) { ClientBridge.networkChanged();android.util.Log.i("DuckSolarClient","Route reevaluated") } } catch(_:Exception) { } finally { reroutePending.set(false) } }
  }
 }
 private lateinit var status:TextView
 private lateinit var balance:GraphPanel
 private lateinit var flow:FlowDiagram
 private val homeCards=linkedMapOf<String,MetricCard>()
 private lateinit var pageTitle:TextView
 private val navigation=mutableListOf<Button>()
 private lateinit var inverterName:TextView
 private lateinit var details:TextView
 private lateinit var monitor:LinearLayout
 private val mainValues=mutableMapOf<String,TextView>()
 private lateinit var monitorPanel:MonitorPanel
 private var lastDevice=""
 private var lastMonitorOrder=listOf<String>()
 private var lastRouteCheck=0L
 private var selectedPage=0
 private var restoringPage=false
 private var extraRoute="menu"
 private var showExtra:((String)->Unit)?=null
 private val tick=object:Runnable {
  override fun run() {
   if(!visible)return
   if(pending.compareAndSet(false,true))worker.execute {
    try { val data=ClientBridge.snapshot();if(data.optString("connection_state")!="AUTH_REQUIRED" && (!data.optBoolean("connected") || data.optString("route")=="remote") && SystemClock.elapsedRealtime()-lastRouteCheck>15000) { lastRouteCheck=SystemClock.elapsedRealtime();try { ClientBridge.networkChanged() } catch(_:Exception){} };runOnUiThread { if(visible)render(data) } }
    catch(_:Exception) { }
    finally { pending.set(false) }
   }
   handler.postDelayed(this,2000)
  }
 }
 private fun dp(n:Int)=(n*resources.displayMetrics.density).toInt()
 private fun label(parent:LinearLayout,text:String,size:Float=16f):TextView=TextView(this).apply {
  this.text=text;textSize=size;setTextColor(Color.rgb(38,54,65));setPadding(0,dp(8),0,dp(8));setTextIsSelectable(true);parent.addView(this)
 }
 private fun panel():LinearLayout=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL;setPadding(dp(16),dp(8),dp(16),dp(16)) }
 override fun onCreate(savedInstanceState:Bundle?) {
  super.onCreate(savedInstanceState)
  restoringPage=savedInstanceState!=null
  selectedPage=savedInstanceState?.getInt("selected_page",0) ?: 0
  extraRoute=savedInstanceState?.getString("extra_route","menu") ?: "menu"
  window.statusBarColor=Color.rgb(244,247,249)
  window.navigationBarColor=Color.rgb(244,247,249)
  window.decorView.systemUiVisibility=android.view.View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR or android.view.View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR
  networks=NetworkWatch(this) { handler.post { handler.removeCallbacks(reroute);handler.postDelayed(reroute,1200) } }
  val root=panel();root.post { AppStyle.apply(root);navigation.forEachIndexed { i,b->AppStyle.navigation(b,listOf("home","monitor","chart","more")[i],i==selectedPage) } };root.background=AppStyle.backdrop();setContentView(root)
  root.setOnApplyWindowInsetsListener { _,insets ->
   root.setPadding(dp(16)+insets.systemWindowInsetLeft,dp(8)+insets.systemWindowInsetTop,dp(16)+insets.systemWindowInsetRight,dp(16)+insets.systemWindowInsetBottom);insets
  }
  val brand=label(root,"DUCK SOLAR",11f);brand.setPadding(0,dp(2),0,dp(2));brand.letterSpacing=.14f;pageTitle=label(root,"Головна",26f);status=label(root,"Підключіть сервер",12f)
  pageTitle.typeface=android.graphics.Typeface.create("sans-serif",android.graphics.Typeface.BOLD)
  status.setPadding(dp(10),dp(10),dp(10),dp(10))
  val tabs=LinearLayout(this)
  val content=FrameLayout(this);root.addView(content,LinearLayout.LayoutParams(-1,0,1f))
  val pages=mutableListOf<ScrollView>()
  fun page(name:String):LinearLayout {
   val body=panel();val scroll=ScrollView(this).apply { addView(body) };pages.add(scroll);content.addView(scroll)
   val index=pages.lastIndex
   Button(this).apply { text=name;textSize=12f;setTextColor(Color.rgb(92,105,115));background=GradientDrawable().apply { setColor(Color.WHITE);cornerRadius=dp(10).toFloat() };isAllCaps=false;isSingleLine=true;setPadding(dp(2),0,dp(2),0);ellipsize=android.text.TextUtils.TruncateAt.END;tabs.addView(this,LinearLayout.LayoutParams(0,dp(64),1f));navigation.add(this);setOnClickListener { selectedPage=index;compactHeader();brand.visibility=if(index==2)android.view.View.GONE else android.view.View.VISIBLE;pageTitle.visibility=if(selectedPage==0 || selectedPage==2)android.view.View.GONE else android.view.View.VISIBLE;if(::balance.isInitialized)balance.setVisible(visible && index==2);flow.setActive(visible && index==0);pageTitle.text=when(index) { 0->"Головна";1->"Моніторинг";2->"Графіки";else->"Додатково" };if(index==3)showExtra?.invoke("menu");navigation.forEachIndexed { i,b->AppStyle.navigation(b,listOf("home","monitor","chart","more")[i],i==index) };pages.forEach { it.visibility=if(it===scroll)android.view.View.VISIBLE else android.view.View.GONE } } }
   return body
  }
  val main=page("Головна")
  main.setPadding(0,dp(8),0,dp(16))
  inverterName=TextView(this) // FlowDiagram shows the actual active name.
  flow=FlowDiagram(this);main.addView(flow,LinearLayout.LayoutParams(-1,-2))
  details=label(main,"Дані ще не отримано",10f)
  monitor=page("Моніторинг");monitor.setPadding(0,dp(8),0,dp(16));label(monitor,"Показники інвертора",22f);monitorPanel=MonitorPanel(this,monitor)
  balance=GraphPanel(this,page("Графіки"))
  val extra=page("Додатково")
  extra.setPadding(0,dp(8),0,dp(16))
  val menu=panel();val connection=panel();val pc=panel();val meters=panel()
  for(body in listOf(menu,connection,pc,meters))body.setPadding(0,dp(8),0,dp(16))
  val extraPanels=mapOf("menu" to menu,"settings" to connection,"pc" to pc,"meters" to meters)
  extraPanels.values.forEach { extra.addView(it) }
  showExtra={ route ->
   extraRoute=if(extraPanels.containsKey(route))route else "menu"
   extraPanels.forEach { (key,body)->body.visibility=if(key==extraRoute)android.view.View.VISIBLE else android.view.View.GONE }
   if(selectedPage==3)pageTitle.text=when(extraRoute) { "settings"->"Налаштування";"pc"->"Зв’язок з ПК";"meters"->"Лічильники";else->"Додатково" }
  }
  for(body in listOf(connection,pc,meters))Button(this).apply { text="‹ Додатково";isAllCaps=false;body.addView(this);setOnClickListener { showExtra?.invoke("menu") } }
  label(menu,"Функції та налаштування",21f)
  Button(this).apply { text="Мова";menu.addView(this);setOnClickListener { ua.ducksolar.shared.UiLanguage.select(this@MainActivity) } }
  fun entry(title:String,action:()->Unit)=Button(this).apply {
   text=title;isAllCaps=false;menu.addView(this,LinearLayout.LayoutParams(-1,dp(64)).apply { bottomMargin=dp(8) })
   val icon=when(title) { "Аналітика станції"->"analytics";"Акумулятор"->"battery_menu";"Прогноз і планування"->"planning";"Історія команд"->"commands";"Місячний баланс"->"balance";"Показники лічильників"->"meter";"Події інвертора"->"events";"Стан сервера"->"server";"Історія"->"archive";"Налаштування"->"settings";"Фінанси будинку"->"wallet";"Зелений тариф"->"tariff";"Погода та прогноз"->"weather";"Зв’язок з ПК"->"pc";else->"history" }
   AppStyle.menu(this,icon);setOnClickListener { action() }
  }
  entry("Аналітика станції") { startActivity(android.content.Intent(this,InsightsActivity::class.java)) }
  entry("Акумулятор") { startActivity(android.content.Intent(this,InsightsActivity::class.java).putExtra("page","battery")) }
  entry("Прогноз і планування") { startActivity(android.content.Intent(this,InsightsActivity::class.java).putExtra("page","forecast")) }
  entry("Історія команд") { startActivity(android.content.Intent(this,InsightsActivity::class.java).putExtra("page","commands")) }
  entry("Місячний баланс") { startActivity(android.content.Intent(this,BalanceActivity::class.java)) }
  entry("Показники лічильників") { showExtra?.invoke("meters") }
  for((title,target) in listOf("Події інвертора" to "events","Фінанси будинку" to "finance","Історія" to "history"))entry(title) { startActivity(android.content.Intent(this,RecordsActivity::class.java).putExtra("page",target)) }
  entry("Зелений тариф") { startActivity(android.content.Intent(this,RecordsActivity::class.java).putExtra("page","tariff")) }
  entry("Погода та прогноз") { startActivity(android.content.Intent(this,WeatherActivity::class.java)) }
  entry("Стан сервера") { startActivity(android.content.Intent(this,ConnectionHealthActivity::class.java)) }
  entry("Налаштування") { showExtra?.invoke("settings") }
  entry("Зв’язок з ПК") { showExtra?.invoke("pc") }
  BalancePanel.attachMeters(this,meters)
  UpdatePanel.attach(this,pc)
  label(menu,"Версія "+packageManager.getPackageInfo(packageName,0).versionName,12f)
  for(section in listOf(connection,pc,meters))section.post { CompactSections.apply(section) }
  root.addView(tabs,LinearLayout.LayoutParams(-1,dp(68)))
  tabs.background=AppStyle.shape(this,Color.WHITE,18)
  navigation.forEachIndexed { i,b->AppStyle.navigation(b,listOf("home","monitor","chart","more")[i],i==selectedPage) }
  label(connection,"Налаштування станції",21f)
  for((title,target) in listOf("Нічний заряд" to "night","Коригування PV" to "pv_correction","Параметри АКБ" to "battery_settings","Профілі налаштувань" to "profiles"))Button(this).apply { text=title;connection.addView(this);setOnClickListener { startActivity(android.content.Intent(this@MainActivity,InsightsActivity::class.java).putExtra("page",target)) } }
  Button(this).apply { text="Параметри інвертора";connection.addView(this);setOnClickListener { startActivity(android.content.Intent(this@MainActivity,ParameterActivity::class.java)) } }
  label(connection,"Підключення до сервера",21f)
  Button(this).apply { text="Сповіщення";isAllCaps=false;connection.addView(this);setOnClickListener { startActivity(android.content.Intent(this@MainActivity,NotificationSettingsActivity::class.java)) } }
  fun input(hint:String,password:Boolean=false)=EditText(this).apply {
   this.hint=hint;setSingleLine();if(password)inputType=InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
   connection.addView(this)
  }
  val lan=input("Домашня адреса HTTPS");val remote=input("Internet адреса HTTPS (необов’язково)")
  val username=input("Ім’я користувача");val password=input("Пароль",true)
  val serial=input("Серійний номер / PN");val code=input("Код підключення з сервера")
  val register=CheckBox(this).apply { text="Створити новий особистий акаунт";connection.addView(this) }
  val message=label(connection,"Створіть код підключення у застосунку сервера.",14f)
  Button(this).apply { text="Підключитися";connection.addView(this);setOnClickListener {
   if(!pending.compareAndSet(false,true))return@setOnClickListener
   val values=listOf(lan.text.toString().trim(),remote.text.toString().trim(),username.text.toString().trim(),password.text.toString(),serial.text.toString().trim(),code.text.toString().trim())
   val create=register.isChecked;message.text="Підключення…"
   worker.execute {
    try {
     ClientBridge.connect(values[0],values[1],values[2],values[3],values[4],values[5],create)
     runOnUiThread { AlertMonitoring.request(this@MainActivity);selectedPage=0;pageTitle.text="Головна";message.text="Підключено";password.setText("");code.setText("");register.isChecked=false;pages.forEachIndexed { i,p->p.visibility=if(i==0)android.view.View.VISIBLE else android.view.View.GONE } }
    } catch(error:Exception) { runOnUiThread { message.text=error.message ?: "Підключення не виконано" } }
    finally { pending.set(false) }
   }
  } }
  for((title,route) in listOf("Підключитись віддалено" to "remote","Підключитись по LAN" to "local")) {
   Button(this).apply { text=title;isAllCaps=false;connection.addView(this);setOnClickListener {
    if(!pending.compareAndSet(false,true))return@setOnClickListener
    val lanAddress=lan.text.toString().trim();val remoteAddress=remote.text.toString().trim()
    message.text="Зміна підключення…"
    worker.execute {
     try { ClientBridge.switchRoute(route,lanAddress,remoteAddress);runOnUiThread { message.text="Підключено "+if(route=="local")"по LAN" else "віддалено";message.append(". Автоматичне відновлення увімкнено.") } }
     catch(e:Exception) { runOnUiThread { message.text=e.message ?: "Маршрут недоступний; автоматичне відновлення залишається активним" } }
     finally { pending.set(false) }
    }
   } }
  }
  label(connection,"Обраний вручну маршрут має пріоритет 2 хвилини. Потім у домашній Wi-Fi мережі клієнт автоматично перевіряє LAN. При втраті зв’язку автоматичне відновлення працює одразу.",13f)
  Button(this).apply { text="Останній збережений знімок";isAllCaps=false;connection.addView(this);setOnClickListener {
   worker.execute { try { val saved=ClientBridge.lastSnapshot();runOnUiThread { SnapshotView.show(this@MainActivity,saved) } } catch(e:Exception) { runOnUiThread { message.text=e.message ?: "Знімок відсутній" } } }
  } }
  if(!restoringPage) { selectedPage=3;extraRoute="settings" }
  pageTitle.text=when(selectedPage) { 0->"Головна";1->"Моніторинг";2->"Графіки";else->"Додатково" }
  showExtra?.invoke(extraRoute)
  brand.visibility=if(selectedPage==2)android.view.View.GONE else android.view.View.VISIBLE;pageTitle.visibility=if(selectedPage==0 || selectedPage==2)android.view.View.GONE else android.view.View.VISIBLE
  pages.forEachIndexed { i,p->p.visibility=if(i==selectedPage)android.view.View.VISIBLE else android.view.View.GONE }
  worker.execute {
   try { val saved=ClientBridge.initialize(this);runOnUiThread { if(saved.optBoolean("saved"))AlertMonitoring.request(this@MainActivity);lan.setText(saved.optString("lan"));remote.setText(saved.optString("remote"));username.setText(saved.optString("username"));serial.setText(saved.optString("serial"));if(saved.optBoolean("saved") && !restoringPage) { selectedPage=0;pageTitle.text="Головна";pages.forEachIndexed { i,p->p.visibility=if(i==0)android.view.View.VISIBLE else android.view.View.GONE } } };ClientBridge.resume() }
   catch(error:Exception) { runOnUiThread { message.text=error.message ?: "Введіть дані підключення" } }
  }
 }
 private fun compactHeader() {
  pageTitle.visibility=if(selectedPage==0 || selectedPage==2)android.view.View.GONE else android.view.View.VISIBLE
  status.maxLines=if(selectedPage==0 || selectedPage==2)1 else 3
  status.ellipsize=android.text.TextUtils.TruncateAt.END
  status.setPadding(dp(10),dp(if(selectedPage==0 || selectedPage==2)4 else 10),dp(10),dp(if(selectedPage==0 || selectedPage==2)4 else 10))
 }
 private fun render(envelope:JSONObject) {
  compactHeader()
  navigation.forEachIndexed { i,b->AppStyle.navigation(b,listOf("home","monitor","chart","more")[i],i==selectedPage) }
  val state=envelope.optJSONObject("state") ?: JSONObject();val connected=envelope.optBoolean("connected")
  val stale=!connected || state.optBoolean("stale",true)
  val maintenance=connected && state.optJSONObject("maintenance")?.optBoolean("active")==true
  status.text=if(connected)"Сервер підключено "+(if(envelope.optString("route")=="local")"локально" else "віддалено")+" • "+if(stale)"дані інвертора недоступні / застарілі" else "дані актуальні" else "Немає зв’язку із сервером"
  if(envelope.optString("connection_state")=="AUTH_REQUIRED")status.text="Потрібен вхід у свій акаунт • авторизація завершена або відкликана"
  if(envelope.has("connection_message"))status.text=envelope.optString("connection_message")+(if(connected)" • "+if(envelope.optString("route")=="local")"локально" else "віддалено" else "")
  if(maintenance)status.text="Сервер обслуговує історію • поточні значення застарілі"
  status.setTextColor(if(connected && !stale)Color.rgb(15,118,90) else Color.rgb(141,90,18))
  status.background=GradientDrawable().apply { setColor(if(connected && !stale)Color.rgb(218,242,223) else Color.rgb(248,240,218));cornerRadius=dp(10).toFloat() }
  val descriptor=state.optJSONObject("descriptor") ?: JSONObject()
  inverterName.text=InverterName.display(descriptor,state.optJSONObject("parameters")?.optJSONObject("identity"))
  details.setOnClickListener { startActivity(android.content.Intent(this,RecordsActivity::class.java).putExtra("page","events")) }
  details.text="Оновлено: "+state.optString("updated").ifBlank { "—" }+"\n"+DisplayText.clean(state.optString("warnings_display")).replace(" (розрах.)","")
  val metrics=HomeMetrics.withDisplayCurrents(state.optJSONObject("normalized")?.optJSONObject("metrics"))
  flow.update(metrics,stale,inverterName.text.toString(),state)
  flow.setActive(visible && selectedPage==0)
  fun rows(vararg definitions:Pair<String,String>)=definitions.map { it.first to metrics?.optJSONObject(it.second) }
  homeCards["battery"]?.update(rows("Заряд" to "battery.channels.main.soc","Напруга" to "battery.channels.main.voltage")+HomeMetrics.batteryRows(metrics),stale)
  homeCards["pv"]?.update(rows("Потужність" to "pv.total_power","Напруга" to "pv.inputs.aggregate.voltage","Струм" to "pv.inputs.aggregate.current"),stale)
  homeCards["grid"]?.update(rows("Імпорт" to "grid.import_power","Експорт" to "grid.export_power","Напруга" to "grid.phases.L1.voltage","Струм" to "grid.phases.L1.current","Частота" to "grid.phases.L1.frequency"),stale)
  homeCards["load"]?.update(rows("Потужність" to "output.active_power","Повна потужність" to "output.apparent_power","Напруга" to "output.phases.L1.voltage","Струм" to "output.phases.L1.current","Частота" to "output.phases.L1.frequency","Навантаження" to "output.load_percent"),stale)
  homeCards["inverter"]?.update(rows("Залишок енергії" to "battery.channels.main.remaining_energy","Температура" to "temperature.inverter","Напруга DC-шини" to "dc.bus_voltage","Напруга SCC" to "battery.scc_voltage"),stale)
  monitorPanel.update(descriptor.optJSONArray("metric_definitions"),metrics,stale)
 }
 override fun onRequestPermissionsResult(requestCode:Int,permissions:Array<out String>,grantResults:IntArray) { super.onRequestPermissionsResult(requestCode,permissions,grantResults);if(requestCode==3874)AlertMonitoring.start(this) }
 override fun onDestroy() { if(::balance.isInitialized)balance.close();super.onDestroy() }
 @Deprecated("Legacy Android back callback")
 override fun onBackPressed() { if(selectedPage==3 && extraRoute!="menu")showExtra?.invoke("menu") else super.onBackPressed() }
 override fun onSaveInstanceState(out:Bundle) { out.putInt("selected_page",selectedPage);out.putString("extra_route",extraRoute);super.onSaveInstanceState(out) }
 override fun onResume() { super.onResume();ClientLifecycle.enter();AlertMonitoring.start(this);visible=true;if(::balance.isInitialized)balance.setVisible(selectedPage==2);if(::flow.isInitialized)flow.setActive(selectedPage==0);ua.ducksolar.shared.UpdateInstaller.foreground=true;if(::networks.isInitialized)networks.start();handler.removeCallbacks(tick);handler.post(tick) }
 override fun onPause() { ClientLifecycle.leave();visible=false;if(::balance.isInitialized)balance.setVisible(false);if(::flow.isInitialized)flow.setActive(false);ua.ducksolar.shared.UpdateInstaller.foreground=false;if(::networks.isInitialized)networks.stop();handler.removeCallbacks(tick);handler.removeCallbacks(reroute);super.onPause() }
}

