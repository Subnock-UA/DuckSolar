package ua.ducksolar.b2.client
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.json.JSONObject
import java.io.File
import android.os.Debug
import java.util.UUID
import android.content.Intent

@RunWith(AndroidJUnit4::class)
class ClientIntegrationTest {
 @Test fun pairingTlsLiveAndResume() {
  val instrumentation=InstrumentationRegistry.getInstrumentation();val context=instrumentation.targetContext
  val args=InstrumentationRegistry.getArguments();val code=args.getString("pair_code")!!;val serial=args.getString("serial")!!
  ClientBridge.initialize(context)
  val activity=instrumentation.startActivitySync(Intent(context,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
  val user="android_"+UUID.randomUUID().toString().replace("-","").take(12)
  val password="TESTONLY-"+UUID.randomUUID().toString()
  try {
   val response=ClientBridge.connect("https://127.0.0.1:9","https://127.0.0.1:28766",user,password,serial,code,true)
   assertEquals(args.getString("server_version") ?: "1.4.10",response.getString("server_version"))
   fun waitConnected():JSONObject {
    val end=System.currentTimeMillis()+15000
    var result=ClientBridge.snapshot()
    while(!result.optBoolean("connected") && System.currentTimeMillis()<end) { Thread.sleep(100);result=ClientBridge.snapshot() }
    assertTrue("SSE did not connect: "+result.optString("connection_state"),result.optBoolean("connected"))
    return result
   }
   val state=waitConnected().getJSONObject("state")
   assertEquals(3,state.getInt("api_version"));assertTrue(state.getBoolean("stale"))
   val saved=File(context.filesDir,"connection.json").readText();assertFalse(saved.contains(password));assertFalse(saved.contains(code))
   val identity=JSONObject(saved).getString("client_id")
   val meters=ClientBridge.meterReadings()
   assertEquals(5,meters.length())
   assertEquals("2026-10-08 15:42:00",meters.getJSONObject(0).getString("reading_date"))
   assertEquals(2352.08,meters.getJSONObject(0).getDouble("import_day"),0.0)
   repeat(4) { ClientBridge.stop();ClientBridge.resume();waitConnected() }
   assertEquals(identity,JSONObject(File(context.filesDir,"connection.json").readText()).getString("client_id"))
   val balanceBefore=Debug.MemoryInfo();Debug.getMemoryInfo(balanceBefore)
   repeat(10) {
    val month=ClientBridge.compactMonth("2026-10")
    assertEquals("energy.month.compact.v1",month.getString("schema"))
    assertTrue(month.getJSONArray("days").length()<=31)
   }
   System.gc();com.chaquo.python.Python.getInstance().getModule("gc").callAttr("collect")
   val balanceAfter=Debug.MemoryInfo();Debug.getMemoryInfo(balanceAfter)
   assertTrue("Repeated compact balance adds over 16MiB",balanceAfter.totalPss-balanceBefore.totalPss<16384)
   File(context.filesDir,"BALANCE_PSS_RESULT.json").writeText(JSONObject().put("before_kib",balanceBefore.totalPss).put("after_kib",balanceAfter.totalPss).put("requests",10).toString())
   assertTrue(com.chaquo.python.Python.getInstance().getModule("android_client_checks").callAttr("saved_session_connect_failover_check").toBoolean())
   val bad=com.chaquo.python.Python.getInstance().getModule("android_client_checks").callAttr("bad_pin_check","https://127.0.0.1:28766").toBoolean()
   assertTrue(bad)
   assertTrue(com.chaquo.python.Python.getInstance().getModule("android_client_checks").callAttr("route_failover_check").toBoolean())
   assertTrue(com.chaquo.python.Python.getInstance().getModule("android_client_checks").callAttr("reconnect_keeps_live_channel").toBoolean())
   val current=java.util.concurrent.atomic.AtomicReference<android.app.Activity?>(activity)
   val application=context.applicationContext as android.app.Application
   val observer=object:android.app.Application.ActivityLifecycleCallbacks {
    override fun onActivityResumed(a:android.app.Activity) { if(a is MainActivity)current.set(a) }
    override fun onActivityCreated(a:android.app.Activity,b:android.os.Bundle?) {}
    override fun onActivityStarted(a:android.app.Activity) {}
    override fun onActivityPaused(a:android.app.Activity) {}
    override fun onActivityStopped(a:android.app.Activity) {}
    override fun onActivitySaveInstanceState(a:android.app.Activity,b:android.os.Bundle) {}
    override fun onActivityDestroyed(a:android.app.Activity) {}
   }
   fun buttons(view:android.view.View):List<android.widget.Button> =
    if(view is android.widget.Button)listOf(view) else if(view is android.view.ViewGroup)(0 until view.childCount).flatMap { buttons(view.getChildAt(it)) } else emptyList()
   val module=com.chaquo.python.Python.getInstance().getModule("android_client_checks")
   val liveIdentity=module.callAttr("live_identity").toLong()
   application.registerActivityLifecycleCallbacks(observer)
   try {
    instrumentation.runOnMainSync { buttons(activity.window.decorView).first { it.text.toString()=="Баланс" }.performClick() }
    repeat(3) {
     val old=current.get()!!
     instrumentation.runOnMainSync { old.recreate() }
     val end=System.currentTimeMillis()+10000
     while(current.get()===old && System.currentTimeMillis()<end)Thread.sleep(50)
     assertNotSame(old,current.get());Thread.sleep(500)
     assertEquals(liveIdentity,module.callAttr("live_identity").toLong())
     assertTrue(ClientBridge.snapshot().optBoolean("connected"))
     instrumentation.runOnMainSync {
      val savedPage=android.os.Bundle();instrumentation.callActivityOnSaveInstanceState(current.get()!!,savedPage)
      assertEquals(2,savedPage.getInt("selected_page"))
      assertEquals(android.content.pm.ActivityInfo.SCREEN_ORIENTATION_PORTRAIT,current.get()!!.requestedOrientation)
     }
    }
   } finally { application.unregisterActivityLifecycleCallbacks(observer) }
   val memory=Debug.MemoryInfo();Debug.getMemoryInfo(memory)
   File(context.filesDir,"CLIENT_INTEGRATION_RESULT.json").writeText(JSONObject().put("spake2_pairing",true).put("tls13_and_pin",true)
    .put("live_state",true).put("stop_resume_cycles",4).put("password_not_saved",true).put("client_identity_preserved",true)
    .put("route_failover_and_lan_preference",true).put("bad_pin_rejected",true).put("recovering_channel_preserved",true)
    .put("active_recreation_preserves_connection_and_tab",true).put("portrait_locked",true).put("pss_kib",memory.totalPss).toString())
  } finally { ClientBridge.stop() }
 }
 @Test fun missingStaleAndUnconfirmedAreVisible() {
  assertEquals("—",MetricText.value(null,false))
  val value=JSONObject().put("value",0).put("unit","W").put("confidence","verified_profile")
  assertTrue(MetricText.value(value,false).startsWith("0"))
  assertTrue(MetricText.value(value,true).contains("застаріле"))
  value.put("confidence","unverified");assertTrue(MetricText.value(value,false).contains("НП"))
  value.put("quality","invalid");assertTrue(MetricText.value(value,false).startsWith("—"))
 }
 @Test fun activityRecreationMemoryBudget() {
  val instrumentation=InstrumentationRegistry.getInstrumentation();val context=instrumentation.targetContext
  ClientBridge.initialize(context)
  val current=java.util.concurrent.atomic.AtomicReference<android.app.Activity?>()
  val application=context.applicationContext as android.app.Application
  val observer=object:android.app.Application.ActivityLifecycleCallbacks {
   override fun onActivityResumed(a:android.app.Activity) { if(a is MainActivity)current.set(a) }
   override fun onActivityCreated(a:android.app.Activity,b:android.os.Bundle?) { }
   override fun onActivityStarted(a:android.app.Activity) { }
   override fun onActivityPaused(a:android.app.Activity) { }
   override fun onActivityStopped(a:android.app.Activity) { }
   override fun onActivitySaveInstanceState(a:android.app.Activity,b:android.os.Bundle) { }
   override fun onActivityDestroyed(a:android.app.Activity) { }
  }
  application.registerActivityLifecycleCallbacks(observer)
  val samples=org.json.JSONArray()
  try {
   val a=instrumentation.startActivitySync(Intent(context,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
   current.set(a)
   repeat(10) { i ->
    val old=current.get()!!
    instrumentation.runOnMainSync { old.recreate() }
    val end=System.currentTimeMillis()+10000
    while(current.get()===old && System.currentTimeMillis()<end)Thread.sleep(50)
    assertNotSame(old,current.get())
    Thread.sleep(300)
    if(i==1 || i==9) {
     System.gc();com.chaquo.python.Python.getInstance().getModule("gc").callAttr("collect")
     val memory=Debug.MemoryInfo();Debug.getMemoryInfo(memory);samples.put(memory.totalPss)
    }
   }
   assertTrue("Activity recreation grows PSS over 64MiB",samples.getInt(1)-samples.getInt(0)<65536)
   File(context.filesDir,"CLIENT_RECREATION_PSS_KIB.json").writeText(samples.toString())
  } finally { application.unregisterActivityLifecycleCallbacks(observer);ClientBridge.stop() }
 }

}
