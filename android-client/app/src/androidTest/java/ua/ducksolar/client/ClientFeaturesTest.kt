package ua.ducksolar.b2.client

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import android.content.Intent
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.util.UUID
import java.io.File
import android.graphics.Bitmap

@RunWith(AndroidJUnit4::class)
class ClientFeaturesTest {
 @Test fun missingValuesValidationAndCommandStates() {
  assertTrue(RecordText.value(JSONObject().put("x",0),"x","грн").startsWith("0"))
  assertTrue(RecordText.value(JSONObject(),"x","грн").contains("немає даних"))
  val noTariff=JSONObject().put("finance",JSONObject().put("green_net_uah",0).put("import_cost_uah",0))
  assertTrue(RecordText.financeValue(noTariff,"green_net_uah").contains("тариф не заданий"))
  assertTrue(RecordText.financeValue(noTariff,"import_cost_uah").startsWith("0"))
  assertTrue(CommandText.status(JSONObject().put("status","verifying")).contains("Очікуємо"))
  assertFalse(CommandText.status(JSONObject().put("status","verifying")).contains("Підтверджено"))
  assertTrue(CommandText.status(JSONObject().put("status","unknown")).contains("не повторюється"))
  assertTrue(CommandText.value(JSONObject().put("present",true).put("raw_value","54").put("display_value","54").put("value_confidence","protocol_family"),false).contains("НП"))
  assertTrue(RecordText.event(JSONObject().put("time","2026-10-11T08:00:00+00:00").put("confidence","unknown").put("message","Попередження")).contains("11:00:00"))
  assertTrue(RecordText.event(JSONObject().put("confidence","unknown").put("message","Попередження")).contains("НП"))
  val parsed=MeterEntry.parse("2026-10-11 12:30",listOf("1234,5","2","3","0"))
  assertEquals(1234.5,parsed.second.getDouble("import_day"),0.0)
  assertEquals(0.0,parsed.second.getDouble("export_night"),0.0)
  for(values in listOf(listOf("","1","2","3"),listOf("NaN","1","2","3"),listOf("-1","1","2","3"))) {
   var rejected=false;try { MeterEntry.parse("2026-10-11 12:30",values) } catch(_:Exception) { rejected=true };assertTrue(rejected)
  }
  var invalidDate=false;try { MeterEntry.parse("2026-02-30 12:00",listOf("1","2","3","4")) } catch(_:Exception) { invalidDate=true };assertTrue(invalidDate)
 }
 @Test fun newScreensUseRealIsolatedServerAndKeepConnection() {
  val inst=InstrumentationRegistry.getInstrumentation();val context=inst.targetContext;val args=InstrumentationRegistry.getArguments()
  ClientBridge.initialize(context)
  val user="fixture_"+UUID.randomUUID().toString().replace("-","").take(12)
  ClientBridge.connect("https://127.0.0.1:28766","",user,"fixture-pass-"+UUID.randomUUID(),args.getString("serial")!!,args.getString("pair_code")!!,true)
  var end=System.currentTimeMillis()+15000
  while(!ClientBridge.snapshot().optBoolean("connected") && System.currentTimeMillis()<end)Thread.sleep(100)
  assertTrue(ClientBridge.snapshot().optBoolean("connected"))
  val events=ClientBridge.events();assertTrue(events.length()>0);assertTrue(RecordText.event(events.getJSONObject(0)).contains("НП"))
  val finance=ClientBridge.financeMonth("2026-09").getJSONObject("selected")
  assertEquals(2026,finance.getInt("year"));assertEquals(9,finance.getInt("month"))
  assertEquals(20.0,finance.getJSONObject("finance").getDouble("import_day_kwh"),0.0)
  val stamp=if(android.os.Build.VERSION.SDK_INT==26)"2026-10-12T12:00" else "2026-10-13T12:00"
  val offset=if(android.os.Build.VERSION.SDK_INT==26)0 else 10
  ClientBridge.addMeterReading(stamp,JSONObject().put("import_day",150+offset).put("import_night",250+offset).put("export_day",360+offset).put("export_night",415+offset))
  val readings=ClientBridge.meterReadings();assertTrue(readings.length()>=3);assertTrue(readings.getJSONObject(0).getString("reading_date").contains(" 12:00:00"))
  ClientBridge.balanceStart("2026-09");end=System.currentTimeMillis()+15000
  var balance=ClientBridge.balanceStatus()
  while(balance.optString("state")=="running" && System.currentTimeMillis()<end) { Thread.sleep(100);balance=ClientBridge.balanceStatus() }
  assertEquals(balance.toString(),"complete",balance.optString("state"))
  assertEquals(0,balance.getJSONObject("report").getJSONObject("diagnostics").getInt("selected_files"))
  val activity=inst.startActivitySync(Intent(context,ParameterActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
  try {
   Thread.sleep(10000)
   assertTrue("Internal screen navigation stopped live connection",ClientBridge.snapshot().optBoolean("connected"))
   assertTrue(ClientBridge.parameters().getBoolean("stale"))
  } finally { inst.runOnMainSync { activity.finish() } }
  val records=inst.startActivitySync(Intent(context,RecordsActivity::class.java).putExtra("page","finance").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
  try {
   fun texts(v:View):List<TextView> = if(v is TextView)listOf(v) else if(v is ViewGroup)(0 until v.childCount).flatMap { texts(v.getChildAt(it)) } else emptyList()
   inst.runOnMainSync {
    texts(records.window.decorView).filterIsInstance<android.widget.EditText>().first().setText("2026-09")
    texts(records.window.decorView).filterIsInstance<android.widget.Button>().first { it.text.toString()=="Отримати фінанси" }.performClick()
   }
   Thread.sleep(1500)
   inst.runOnMainSync { assertTrue(texts(records.window.decorView).any { it.text.toString().contains("Місяць 2026-09") }) }
   val bitmap=inst.uiAutomation.takeScreenshot();File(context.filesDir,"FINANCE_SCREEN.png").outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG,100,it) };bitmap.recycle()
  } finally { inst.runOnMainSync { records.finish() } }
 }
}
