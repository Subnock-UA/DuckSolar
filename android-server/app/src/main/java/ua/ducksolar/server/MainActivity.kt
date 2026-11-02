package ua.ducksolar.b2.server

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.os.*
import android.graphics.Color
import android.widget.*
import java.util.concurrent.Executors

class MainActivity :ua.ducksolar.shared.LocalizedActivity() {
    private val handler = Handler(Looper.getMainLooper())
    private val worker = Executors.newSingleThreadExecutor()
    private val refreshPending = java.util.concurrent.atomic.AtomicBoolean(false)
    private lateinit var status: TextView
    private lateinit var overview:TextView
    private lateinit var info: TextView
    private lateinit var pairing: TextView
    private lateinit var supportInfo:TextView
    private lateinit var resourcesInfo:TextView
    private val supportBusy=java.util.concurrent.atomic.AtomicBoolean(false)
    private val tick = object : Runnable {
        override fun run() {
            status.text = Bridge.state
            if(::supportInfo.isInitialized && HistorySyncController.running)supportInfo.text=HistorySyncController.status
            if(::supportInfo.isInitialized && ua.ducksolar.shared.UpdateInstaller.status.isNotEmpty())supportInfo.text=ua.ducksolar.shared.UpdateInstaller.status
            if (com.chaquo.python.Python.isStarted() && refreshPending.compareAndSet(false,true)) worker.execute {
                try {
                    val s = Bridge.status()
                    val resource=DiagnosticView.resources(this@MainActivity)
                    runOnUiThread {
                        resourcesInfo.text=resource
                        overview.text="${if(s.optBoolean("running"))"● Сервер працює" else "○ Сервер зупинено"}\n${if(s.optBoolean("stale",true))"Дані інвертора очікуються" else "Показники актуальні"} • ${s.optString("updated","—")}\nHTTPS:28766 • ${s.optJSONArray("lan_ips") ?: "—"}"
                        val polling=s.optJSONObject("ess_polling")
                        val route=s.optJSONObject("logger_route")
                        val routeState=when(route?.optString("state")) {
                            "CONFIGURING" -> "підготовка з’єднання"
                            "RECONNECTING" -> "очікування логера"
                            "ACTIVE" -> "підключено"
                            "RETRYING" -> "повторна спроба"
                            "WAITING_NETWORK" -> "очікування мережі Wi-Fi"
                            "RESTORING" -> "повернення прямого ESS"
                            "RESTORE_PENDING" -> "потрібне відновлення ESS"
                            else -> "очікування"
                        }
                        val modeLabel=when(s.optString("equipment_mode","normal")) {
                            "local_only" -> "Локальне опитування без хмари"
                            "relay_only" -> "Хмарна ретрансляція без локального опитування"
                            else -> "Звичайний"
                        }
                        info.text = if (s.optBoolean("running")) "Режим: $modeLabel\nAPI: HTTPS, порт 28766\nАдреси: ${s.optJSONArray("lan_ips") ?: "—"}\nЛогер: ${s.optString("logger_ip", "—")}\nEyBond: ${s.optString("connection", "—")}\nЗв’язок логера: $routeState${route?.optString("last_error")?.takeIf { it.isNotEmpty() }?.let { " • $it" } ?: ""}\nESS: ${s.optString("ess_connection", "—")} • ${s.optString("cloud_endpoint", "—")}\nДжерело поточних даних • джерело: ${s.optString("sample_source", "Local")}\nВикористано відповідей ESS: ${polling?.optInt("reuse") ?: 0}\nЗіставлення ESS: ${if(polling?.optBoolean("calibrated")==true) "перевірено читанням" else "очікує перевірки"}\nОновлено: ${s.optString("updated", "—")}\nДані застарілі: ${if (s.optBoolean("stale")) "так" else "ні"}\nВідбиток сервера:\n${s.optString("fingerprint")}" else "Дані зберігаються на цьому пристрої."
                    }
                } catch (_: Exception) { } finally { refreshPending.set(false) }
            }
            handler.postDelayed(this, 2000)
        }
    }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = Color.rgb(234,245,243)
        window.navigationBarColor=Color.rgb(245,248,251)
        window.decorView.systemUiVisibility=android.view.View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR or android.view.View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR
        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(28, 28, 28, 28); isFocusableInTouchMode = true }
        setContentView(ScrollView(this).apply {
            addView(root)
            if(Build.VERSION.SDK_INT>=35)setOnApplyWindowInsetsListener { view,insets ->
                view.setPadding(insets.systemWindowInsetLeft,insets.systemWindowInsetTop,
                    insets.systemWindowInsetRight,insets.systemWindowInsetBottom)
                insets
            }
        })
        root.post { CompactSections.apply(root);AppStyle.apply(root) }
        root.background=android.graphics.drawable.GradientDrawable(android.graphics.drawable.GradientDrawable.Orientation.TOP_BOTTOM,intArrayOf(Color.rgb(234,245,243),Color.rgb(246,248,252)))
        fun text(value: String, size: Float = 16f) = TextView(this).apply { text=value; textSize=size; setPadding(0, 12, 0, 12); root.addView(this) }
        text("DUCK SOLAR", 28f)
        Button(this).apply { text="Мова";root.addView(this);setOnClickListener { ua.ducksolar.shared.UiLanguage.select(this@MainActivity) } }
        Button(this).apply { text="Відкрити налаштування Wi-Fi";root.addView(this);setOnClickListener { startActivity(Intent(android.provider.Settings.Panel.ACTION_WIFI)) } }

        text("Сервер Android • ${AppVersion.name(this)}", 20f)
        Button(this).apply {
            text="Робота сервера без обмеження батареї";root.addView(this)
            setOnClickListener {
                val power=getSystemService(android.os.PowerManager::class.java)
                if(power.isIgnoringBatteryOptimizations(packageName))ua.ducksolar.shared.LocalizedToast.makeText(this@MainActivity,"Виняток уже увімкнений",android.widget.Toast.LENGTH_LONG).show()
                else startActivity(Intent(android.provider.Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,android.net.Uri.parse("package:$packageName")))
            }
        }
        status = text(Bridge.state, 18f)
        overview=text("Стан сервера",16f).apply { setPadding(20,20,20,20);background=AppStyle.shape(this@MainActivity,Color.WHITE,18) }
        val prefs = getPreferences(MODE_PRIVATE)
        text("Підключення до обладнання",20f)
        val ip = EditText(this).apply { hint="IP-адреса EyBond"; setSingleLine(); setText(prefs.getString("ip", "")); root.addView(this) }
        val pn = EditText(this).apply { hint="PN реєстратора EyBond"; setSingleLine(); setText(prefs.getString("pn", "")); root.addView(this) }
        val offline = Switch(this).apply { text="Без підключення до обладнання"; isChecked=prefs.getBoolean("offline", true); root.addView(this) }
        text("Режим обладнання (застосовується після зупинки й запуску сервера)")
        val modes=listOf("normal","local_only","relay_only")
        val equipmentMode=Spinner(this).apply {
            adapter=ArrayAdapter(this@MainActivity,android.R.layout.simple_spinner_dropdown_item,
                listOf("Звичайний режим","Локальне опитування без хмари","Хмарна ретрансляція без локального опитування"))
            setSelection(modes.indexOf(prefs.getString("equipment_mode","normal")).coerceAtLeast(0))
            root.addView(this)
        }
        text("Керування сервером",20f)
        Button(this).apply {
            text="Запустити сервер"; root.addView(this)
            setOnClickListener {
                prefs.edit().putString("equipment_mode",modes[equipmentMode.selectedItemPosition]).apply()
                prefs.edit().putBoolean("server_enabled",true).putString("ip",ip.text.toString().trim()).putString("pn",pn.text.toString().trim()).putBoolean("offline",offline.isChecked).apply()
                startForegroundService(Intent(this@MainActivity, ServerService::class.java).putExtra("ip",ip.text.toString().trim()).putExtra("pn",pn.text.toString().trim()).putExtra("offline",offline.isChecked))
            }
        }
        Button(this).apply { text="Зупинити сервер"; root.addView(this); setOnClickListener { prefs.edit().putBoolean("server_enabled",false).apply();if (com.chaquo.python.Python.isStarted()) startService(Intent(this@MainActivity,ServerService::class.java).setAction("STOP")) } }
        Button(this).apply { text="Кеш графіків · фонова підготовка";root.addView(this);setOnClickListener { startActivity(Intent(this@MainActivity,CacheActivity::class.java)) } }
        Button(this).apply { text="Прогноз генерації та навчання";root.addView(this);setOnClickListener { startActivity(Intent(this@MainActivity,ForecastActivity::class.java)) } }
        text("Деталі та доступ клієнтів",20f)
        pairing = text("Код підключення клієнта не створено")
        Button(this).apply {
            text="Створити код підключення"; root.addView(this)
            setOnClickListener { worker.execute { try { val code=Bridge.pairingCode(); runOnUiThread { pairing.text="Код: $code\nДіє 5 хвилин" } } catch (_: Exception) { runOnUiThread { pairing.text="Спочатку запустіть сервер" } } } }
        }
        info = text("Дані зберігаються на цьому пристрої.")
        info.setTextIsSelectable(true)
        text("Керування інвертором виконується через клієнт.\nБаланс, графіки та налаштування сповіщень доступні в клієнті.")
        text("Оновлення та копії журналів",20f)
        if (!prefs.contains("pc_url")) prefs.edit().putString("pc_url","").apply()
        val pcUrl=EditText(this).apply {
            hint="http://<адреса ПК>:28765";setSingleLine();setText(prefs.getString("pc_url",""));root.addView(this)
        }
        supportInfo=text("ПК-служба не налаштована");supportInfo.setTextIsSelectable(true)
        fun task(action:()->String) {
            if(!supportBusy.compareAndSet(false,true))return
            val address=pcUrl.text.toString().trim();prefs.edit().putString("pc_url",address).apply()
            supportInfo.text="Виконується…"
            worker.execute {
                try { val message=action();runOnUiThread { supportInfo.text=message } }
                catch(error:Exception) { ua.ducksolar.shared.UpdateDiagnostics.record(this@MainActivity,"support.error",error.message ?: error.javaClass.simpleName);runOnUiThread { supportInfo.text=error.message ?: "Операцію не завершено" } }
                finally { supportBusy.set(false) }
            }
        }
        Button(this).apply {
            text="Синхронізувати історію з ПК";root.addView(this)
            setOnClickListener {
                val address=pcUrl.text.toString().trim();prefs.edit().putString("pc_url",address).apply()
                HistorySyncController.start(this@MainActivity,address) { supportInfo.text=it }
            }
        }
        Button(this).apply { text="Запустити збір даних";root.addView(this);setOnClickListener {
            HistorySyncController.resume(this@MainActivity) { supportInfo.text=it }
        } }
        Button(this).apply {
            text="Зупинити синхронізацію";root.addView(this)
            setOnClickListener { HistorySyncController.cancel(this@MainActivity,pcUrl.text.toString().trim()) { supportInfo.text=it } }
        }
        Button(this).apply {
            text="Перевірити зелений тариф НКРЕКП";root.addView(this)
            setOnClickListener { task {
                val row=org.json.JSONObject(com.chaquo.python.Python.getInstance().getModule("android_bridge").callAttr("check_tariff").toString())
                val rate=row.optDouble("rate_uah",Double.NaN)
                require(rate.isFinite()) { "Некоректна відповідь перевірки тарифу" }
                fun date(key:String)=try { java.time.LocalDate.parse(row.getString(key)).format(java.time.format.DateTimeFormatter.ofPattern("dd.MM.yyyy")) } catch(_:Exception) { row.optString(key) }
                (if(row.optBoolean("changed"))"Тариф оновлено" else "Тариф актуальний")+": "+String.format(java.util.Locale.getDefault(),"%.4f грн/кВт·год",rate)+
                    "\nДіє з ${date("effective_from")}\nПостанова №${row.optString("resolution_number")} від ${date("resolution_date")}"+
                    (if(row.optBoolean("manual_override"))"\nУвімкнено ручне перевизначення тарифу" else "")+
                    "\n${row.optString("source_url")}"
            } }
        }
        Button(this).apply {
            text="Перевірити оновлення";root.addView(this)
            setOnClickListener {
                val address=pcUrl.text.toString().trim()
                ua.ducksolar.shared.UpdateInstaller.status=""
                task {
                    val client=ua.ducksolar.shared.LanSupportClient(this@MainActivity,address)
                    ua.ducksolar.shared.UpdateWorkflow.from(this@MainActivity,"server",client).check()
                }
            }
        }
        Button(this).apply {
            text="Встановити оновлення";root.addView(this)
            setOnClickListener {
                val address=pcUrl.text.toString().trim()
                ua.ducksolar.shared.UpdateInstaller.status=""
                task {
                    val client=ua.ducksolar.shared.LanSupportClient(this@MainActivity,address)
                    ua.ducksolar.shared.UpdateWorkflow.from(this@MainActivity,"server",client).install({done,total ->
                        runOnUiThread { supportInfo.text=ua.ducksolar.shared.DownloadProgress.text(done,total) }
                    }) { file,update ->
                        if(!ua.ducksolar.shared.UpdateInstaller.permissionReady(this@MainActivity))ua.ducksolar.shared.UpdateInstaller.status
                        else {
                            runOnUiThread { supportInfo.text="Пакет перевірено. Завершення запису журналів…" }
                            val resume=com.chaquo.python.Python.isStarted() && Bridge.status().optBoolean("running")
                            getSharedPreferences("ServerUpdate",MODE_PRIVATE).edit().putBoolean("resume",resume).putLong("target",update.versionCode).commit()
                            try {
                            if(com.chaquo.python.Python.isStarted())startService(Intent(this@MainActivity,ServerService::class.java).setAction("STOP"))
                            val until=System.currentTimeMillis()+120000
                            while(com.chaquo.python.Python.isStarted() && Bridge.status().optBoolean("running") && System.currentTimeMillis()<until)Thread.sleep(100)
                            check(!com.chaquo.python.Python.isStarted() || !Bridge.status().optBoolean("running")) { "Сервер ще завершує запис журналів" }
                            Bridge.initialize(this@MainActivity)
                                Bridge.updateCheckpoint(update.version)
                                val id=ua.ducksolar.shared.UpdateInstaller.install(this@MainActivity,file,update)
                                if(id<0) { UpdateCoordinator.recover(this@MainActivity,true);ua.ducksolar.shared.UpdateInstaller.status }
                                else "Підтвердьте оновлення у вікні Android"
                            } catch(error:Exception) { UpdateCoordinator.recover(this@MainActivity,true);throw error }
                        }
                    }
                }
            }
        }
        Button(this).apply {
            text="Передати журнали на ПК";root.addView(this)
            setOnClickListener {
                val address=pcUrl.text.toString().trim()
                task { Bridge.initialize(this@MainActivity);ServerMaintenance.sync(this@MainActivity,address) }
            }
        }
        Button(this).apply { text="Відновити збережений endpoint ESS з ПК";root.addView(this);setOnClickListener {
            val address=pcUrl.text.toString().trim();val expectedPn=pn.text.toString().trim()
            task {
                Bridge.initialize(this@MainActivity)
                check(!Bridge.status().optBoolean("running")) { "Спочатку зупиніть сервер" }
                val client=ua.ducksolar.shared.LanSupportClient(this@MainActivity,address)
                val array=client.archiveSources()
                val sources=(0 until array.length()).map { array.getJSONObject(it) }.filter { it.getString("id")!="pc" }
                check(sources.isNotEmpty()) { "ПК не має журналів попереднього сервера" }
                runOnUiThread {
                    ua.ducksolar.shared.LocalizedDialog.Builder(this@MainActivity).setTitle("Попередній сервер")
                        .setItems(sources.map { it.getString("label") }.toTypedArray()) { _,index -> task {
                            val routes=client.archiveRoutes(sources[index].getString("id"))
                            val route=(0 until routes.length()).map { routes.getJSONObject(it) }.lastOrNull { it.getString("pn")==expectedPn }
                            check(route!=null) { "У журналі немає підтвердженого штатного endpoint для цього PN" }
                            runOnUiThread {
                                ua.ducksolar.shared.LocalizedDialog.Builder(this@MainActivity).setTitle("Зберегти endpoint ESS?")
                                    .setMessage("PN: ${route.getString("pn")}\nESS: ${route.getString("original_endpoint")}:${route.getInt("original_port")}\nБуде збережено лише локальний запис відновлення. Поточні налаштування обладнання зараз не змінюються. Після цього запустіть сервер звичайною кнопкою.")
                                    .setPositiveButton("Зберегти") { _,_ -> task { val result=Bridge.recoverEssRoute(route);"Збережено ${result.getString("endpoint")}:${result.getInt("port")}. Запустіть сервер." } }
                                    .setNegativeButton("Скасувати",null).show()
                            }
                            "Перевірте PN та endpoint"
                        } }.setNegativeButton("Скасувати",null).show()
                }
                "Оберіть попередній сервер"
            }
        } }
        Button(this).apply { text="Історія ESS";root.addView(this);setOnClickListener {
            Bridge.initialize(this@MainActivity);EssHistoryPanel.show(this@MainActivity,pn.text.toString().trim())
        } }
        Button(this).apply { text="Перевірити історію сервера";root.addView(this);setOnClickListener { task {
            Bridge.initialize(this@MainActivity)
            val history=Bridge.historyInventory()
            "Історія: ${history.optInt("days")} днів • ${history.optString("first","—")} — ${history.optString("last","—")}\nФайлів Local: ${history.optInt("local_files")}; SmartESS: ${history.optInt("ess_files")}\nСинхронізованих файлів: ${history.optJSONObject("archive")?.optInt("synchronized_files") ?: 0}. Кількість файлів не підтверджує повноту покриття."
        } } }
        text("Ресурси та журнал",20f)
        resourcesInfo=text("Очікування вимірювання ресурсу");resourcesInfo.setTextIsSelectable(true)
        val journal=text("");journal.setTextIsSelectable(true)
        Button(this).apply { text="Переглянути останні події";root.addView(this);setOnClickListener {
            worker.execute {
                val file=java.io.File(filesDir,"DuckSolar/Logs/DS_Server_Beta_2/Events.jsonl")
                val tail=DiagnosticView.tail(file,16384)
                runOnUiThread { journal.text=if(tail.isEmpty())"Подій ще немає" else tail }
            }
        } }
        Switch(this).apply {
            text="Запуск після перезавантаження Android";isChecked=prefs.getBoolean("auto_boot",false);root.addView(this)
            setOnCheckedChangeListener { _,checked ->prefs.edit().putBoolean("auto_boot",checked).apply() }
        }
        fun fold(title:String,endTitle:String?=null) {
            val children=(0 until root.childCount).map { root.getChildAt(it) }
            val begin=children.indexOfFirst { it is TextView && it !is Button && ua.ducksolar.shared.UiLanguage.sourceText(it)==title }
            if(begin<0)return
            val end=if(endTitle==null)children.size else children.indexOfFirst { it is TextView && it !is Button && ua.ducksolar.shared.UiLanguage.sourceText(it)==endTitle }.let { if(it<0)children.size else it }
            val body=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL;setPadding(16,12,16,12);background=AppStyle.shape(this@MainActivity,Color.WHITE);visibility=android.view.View.GONE }
            for(i in begin+1 until end) { root.removeView(children[i]);body.addView(children[i]) }
            root.removeView(children[begin])
            val header=Button(this).apply { text="› $title";isAllCaps=false;setOnClickListener { val opened=body.visibility==android.view.View.VISIBLE;body.visibility=if(opened)android.view.View.GONE else android.view.View.VISIBLE;text=(if(opened)"› " else "⌄ ")+title } }
            root.addView(header,begin);root.addView(body,begin+1)
        }
        fold("Підключення до обладнання","Керування сервером")
        fold("Деталі та доступ клієнтів","Оновлення та копії журналів")
        fold("Оновлення та копії журналів","Ресурси та журнал")
        fold("Ресурси та журнал")
        root.requestFocus()
        if (Build.VERSION.SDK_INT >= 33) requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
    }
    override fun onResume() { super.onResume();UpdateCoordinator.recover(this);ua.ducksolar.shared.UpdateInstaller.foreground=true; handler.post(tick) }
    override fun onPause() { ua.ducksolar.shared.UpdateInstaller.foreground=false;handler.removeCallbacks(tick); super.onPause() }
    override fun onDestroy() { worker.shutdown(); super.onDestroy() }
}
