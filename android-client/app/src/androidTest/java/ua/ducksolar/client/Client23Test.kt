package ua.ducksolar.b2.client
import android.app.Activity
import android.content.Intent
import android.view.View
import android.view.ViewGroup
import android.widget.*
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.json.JSONObject
@RunWith(AndroidJUnit4::class)
class Client23Test {
 private fun views(v:View):List<View> = listOf(v)+(if(v is ViewGroup)(0 until v.childCount).flatMap { views(v.getChildAt(it)) } else emptyList())
 @Test fun windowAndConnectionHealthContracts() {
  assertEquals(33,android.os.Build.VERSION.SDK_INT)
  ClientBridge.initialize(InstrumentationRegistry.getInstrumentation().targetContext)
  assertNotEquals(ChartAxis.categoryLabel("2026-10-25T03:00:00+03:00"),ChartAxis.categoryLabel("2026-10-25T03:00:00+02:00"))
  val dst=JSONObject(com.chaquo.python.Python.getInstance().getModule("dst_client_checks").callAttr("run").toString())
  assertTrue(dst.optString("output"),dst.getBoolean("passed"));assertEquals(2,dst.getInt("tests"))
  val r=JSONObject(com.chaquo.python.Python.getInstance().getModule("client23_checks").callAttr("run").toString())
  assertTrue(r.getBoolean("passed"));assertEquals(9,r.getInt("tests"))
 }
 @Test fun dayWindowControlAndHealthMenuAreReachable() {
  val inst=InstrumentationRegistry.getInstrumentation();val context=inst.targetContext
  context.getSharedPreferences("Graphs",0).edit().putInt("period",0).putBoolean("custom_window",false).apply()
  val activity=inst.startActivitySync(Intent(context,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)) as MainActivity
  try {
   Thread.sleep(500)
   inst.runOnMainSync {
    val buttons=views(activity.window.decorView).filterIsInstance<Button>();buttons.single { it.text.toString()=="Графіки" }.performClick()
    assertTrue(buttons.any { it.contentDescription?.toString()=="Часовий проміжок дня" && it.isShown })
    buttons.single { it.text.toString()=="Додатково" }.performClick()
    assertTrue(buttons.any { it.text.toString()=="Стан сервера" && it.isShown })
   }
  } finally { inst.runOnMainSync { activity.finish() } }
 }
 @Test fun healthScreenShowsLiveAndInverterStatesSeparately() {
  val inst=InstrumentationRegistry.getInstrumentation();val context=inst.targetContext
  val activity=inst.startActivitySync(Intent(context,ConnectionHealthActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as ConnectionHealthActivity
  try {
   Thread.sleep(1500)
   inst.runOnMainSync {
    val text=views(activity.window.decorView).filterIsInstance<TextView>().joinToString(" ") { it.text.toString() }
    assertTrue(text.contains("Сервер:"));assertTrue(text.contains("Інвертор:"));assertTrue(text.contains("За цей запуск клієнта:"))
   }
  } finally { inst.runOnMainSync { activity.finish() } }
 }
}
