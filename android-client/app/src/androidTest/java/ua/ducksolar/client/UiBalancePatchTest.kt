package ua.ducksolar.b2.client

import android.app.Activity
import android.app.DatePickerDialog
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.PathMeasure
import android.view.View
import android.view.ViewGroup
import android.widget.*
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.util.Locale

@RunWith(AndroidJUnit4::class)
class UiBalancePatchTest {
 private fun views(v:View):List<View> = listOf(v)+(if(v is ViewGroup)(0 until v.childCount).flatMap { views(v.getChildAt(it)) } else emptyList())
 @Test fun highlightsAreHalfAPathApartAndKeepSpeed() {
  assertEquals(2200000000L,FlowHighlights.CYCLE_NS)
  for(path in FlowLayout.create(1f).routes) {
   val length=PathMeasure(path,false).length
   for(p in listOf(0f,.1f,.49f,.75f,.99f))for(reverse in listOf(false,true)) {
    val centers=FlowHighlights.centers(length,p,reverse)
    assertEquals(length*.5f,kotlin.math.abs(centers[0]-centers[1]),.001f)
    assertEquals(1f,FlowHighlights.brightness(centers[0],centers,length),.001f)
   }
  }
 }
 @Test fun stripeUsesOnlyFreshModesAndMetrics() {
  val state=JSONObject().put("mode_code","B").put("mode_stale",false)
  fun metric(v:Double)=JSONObject().put("value",v).put("quality","good")
  val metrics=JSONObject().put("pv.total_power",metric(600.0)).put("battery.channels.main.discharge_current",metric(0.0))
  assertEquals(InverterArtwork.PURPLE,InverterArtwork.stripe(state,metrics,false))
  metrics.getJSONObject("battery.channels.main.discharge_current").put("value",2.0)
  assertEquals(InverterArtwork.RED,InverterArtwork.stripe(state,metrics,false))
  state.put("mode_code","L");assertEquals(InverterArtwork.BLUE,InverterArtwork.stripe(state,metrics,false))
  state.put("mode_code","B").put("mode_stale",true);assertEquals(InverterArtwork.BLUE,InverterArtwork.stripe(state,metrics,false))
  state.put("mode_stale",false);assertEquals(InverterArtwork.BLUE,InverterArtwork.stripe(state,metrics,true))
  state.put("mode_code","?");assertEquals(InverterArtwork.BLUE,InverterArtwork.stripe(state,metrics,false))
 }
 @Test fun batteryHistoryExistsOnlyInReadOnlyBatteryPage() {
  val inst=InstrumentationRegistry.getInstrumentation();ClientBridge.initialize(inst.targetContext)
  for(page in listOf("battery","battery_settings")) {
   val a=inst.startActivitySync(Intent(inst.targetContext,InsightsActivity::class.java).putExtra("page",page).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
   try { inst.runOnMainSync {
    val rows=views(a.window.decorView)
    assertEquals(page=="battery",rows.filterIsInstance<Button>().any { it.text.toString()=="Історія АКБ" })
    assertEquals(if(page=="battery")0 else 2,rows.filterIsInstance<EditText>().size)
    assertEquals(page=="battery_settings",rows.filterIsInstance<Button>().any { it.text.toString()=="Зберегти параметри" })
   } } finally { inst.runOnMainSync { a.finish() } }
  }
 }
 @Test fun calendarIsUkrainianUnderRussianSystemLocale() {
  val inst=InstrumentationRegistry.getInstrumentation();val old=Locale.getDefault();Locale.setDefault(Locale("ru","RU"))
  val a=inst.startActivitySync(Intent(inst.targetContext,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
  try { inst.runOnMainSync {
   val localized=PeriodPicker.ukrainianContext(a)
   assertEquals("uk",localized.resources.configuration.locales[0].language)
   val dialog=DatePickerDialog(localized,null,2026,9,31);dialog.show()
   assertEquals("uk",dialog.datePicker.context.resources.configuration.locales[0].language)
   val months=java.text.DateFormatSymbols(localized.resources.configuration.locales[0]).months
   assertTrue(months[9].lowercase().startsWith("жовт"));dialog.dismiss()
   val field=EditText(a).apply { setText("2026-10-31") };a.setContentView(field)
   PeriodPicker.bind(a,field);field.performClick()
  }
   inst.waitForIdleSync()
   fun labels(node:android.view.accessibility.AccessibilityNodeInfo?):String {
    if(node==null)return ""
    return listOf(node.text?.toString() ?: "",node.contentDescription?.toString() ?: "").joinToString(" ")+" "+(0 until node.childCount).joinToString(" ") { labels(node.getChild(it)) }
   }
   val shown=labels(inst.uiAutomation.rootInActiveWindow)
   assertTrue(shown,shown.lowercase().contains("обрати"));assertTrue(shown,shown.lowercase().contains("скасувати"))
   assertTrue(shown,shown.lowercase().contains("жовт"))
   assertFalse(shown.lowercase().contains("октябр"))
   inst.uiAutomation.takeScreenshot().also { bitmap->File(inst.targetContext.cacheDir,"calendar-uk.png").outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG,100,it) };bitmap.recycle() }
   inst.sendKeyDownUpSync(android.view.KeyEvent.KEYCODE_BACK)
  } finally { Locale.setDefault(old);inst.runOnMainSync { a.finish() } }
 }
 @Test fun moreMenuRetainsRowsWithDistinctSymbolsAndScreenshot() {
  val inst=InstrumentationRegistry.getInstrumentation();val context=inst.targetContext
  val a=inst.startActivitySync(Intent(context,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
  try {
   inst.runOnMainSync { views(a.window.decorView).filterIsInstance<Button>().first { it.text.toString()=="Додатково" }.performClick() }
   inst.waitForIdleSync()
   inst.runOnMainSync {
    val entries=views(a.window.decorView).filterIsInstance<Button>().filter { it.getTag(R.id.style_kind)=="menu" }
    assertEquals(14,entries.size);assertEquals(14,entries.map { it.getTag(R.id.style_icon) }.toSet().size)
    assertEquals("Аналітика станції",entries.first().text.toString())
    assertEquals("Зв’язок з ПК",entries.last().text.toString())
   }
   inst.uiAutomation.takeScreenshot().also { bitmap->File(context.cacheDir,"more-updated.png").outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG,100,it) };bitmap.recycle() }
  } finally { inst.runOnMainSync { a.finish() } }
 }
 @Test fun forecastResultShowsComparisonWithoutEvents() {
  val inst=InstrumentationRegistry.getInstrumentation();val context=inst.targetContext
  val a=inst.startActivitySync(Intent(context,InsightsActivity::class.java).putExtra("page","forecast_actual").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
  try {
   val row=JSONObject().put("kind","forecast").put("events",org.json.JSONArray().put(JSONObject().put("message","UNWANTED_EVENT")))
   row.put("comparison",JSONObject().put("day","2026-10-31").put("forecast_day_kwh",12).put("forecast_period_kwh",12).put("actual_period_kwh",10).put("error_kwh",2).put("error_pct",16.7).put("covered_hours",24).put("expected_hours",24).put("period_end","2026-11-01T00:00:00+02:00").put("note","Прогноз − факт"))
   val points=org.json.JSONArray();for(i in 0 until 24)points.put(JSONObject().put("x",i).put("label","2026-10-31T"+"%02d".format(i)+":00:00+02:00").put("forecast",if(i in 7..17)1.0 else 0.0).put("actual",if(i in 7..17).8 else 0.0))
   row.put("graph",JSONObject().put("kind","bars").put("mode","energy").put("suppress_summary",true).put("points",points).put("fields",org.json.JSONArray().put(JSONObject().put("key","forecast").put("label","Прогноз").put("unit","кВт·год")).put(JSONObject().put("key","actual").put("label","Факт").put("unit","кВт·год"))))
   inst.runOnMainSync {
    InsightsActivity::class.java.getDeclaredMethod("renderResult",JSONObject::class.java).apply { isAccessible=true }.invoke(a,row)
    val labels=views(a.window.decorView).filterIsInstance<TextView>().joinToString("\n") { it.text.toString() }
    assertTrue(labels.contains("Прогноз на добу"));assertTrue(labels.contains("Відхилення"));assertFalse(labels.contains("UNWANTED_EVENT"))
    assertTrue(views(a.window.decorView).any { it is HistoryChart })
   }
   inst.waitForIdleSync();inst.runOnMainSync { views(a.window.decorView).filterIsInstance<ScrollView>().first().fullScroll(View.FOCUS_DOWN) };inst.waitForIdleSync()
   inst.uiAutomation.takeScreenshot().also { bitmap->File(context.cacheDir,"forecast-comparison.png").outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG,100,it) };bitmap.recycle() }
  } finally { inst.runOnMainSync { a.finish() } }
 }
}
