package ua.ducksolar.b2.client
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.json.JSONObject
@RunWith(AndroidJUnit4::class)
class Patch22Test {
 @Test fun contractsOnTargetAndroid() {
  assertEquals(33,android.os.Build.VERSION.SDK_INT)
  ClientBridge.initialize(InstrumentationRegistry.getInstrumentation().targetContext)
  val result=JSONObject(com.chaquo.python.Python.getInstance().getModule("patch22_checks").callAttr("run").toString())
  assertTrue(result.getBoolean("passed"))
 }
 @Test fun staleValuesAreHiddenAndZeroRemainsVisible() {
  val metric=JSONObject().put("value",0).put("quality","good").put("unit","V")
  assertTrue(MetricText.value(metric,false).startsWith("0"));assertEquals("—",MetricText.value(metric,true))
  metric.put("stale",true);assertEquals("—",HomeMetrics.text(metric,false))
 }
 @Test fun settingsContainBothRouteButtonsAndSnapshot() {
  val inst=InstrumentationRegistry.getInstrumentation();val context=inst.targetContext
  val activity=inst.startActivitySync(android.content.Intent(context,MainActivity::class.java).addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK or android.content.Intent.FLAG_ACTIVITY_CLEAR_TASK)) as MainActivity
  fun views(v:android.view.View):List<android.view.View> = listOf(v)+(if(v is android.view.ViewGroup)(0 until v.childCount).flatMap { views(v.getChildAt(it)) } else emptyList())
  try {
   inst.runOnMainSync {
    val buttons=views(activity.window.decorView).filterIsInstance<android.widget.Button>()
    buttons.single { it.text.toString()=="Додатково" }.performClick()
    buttons.single { it.text.toString()=="Налаштування" }.performClick()
    for(title in listOf("Підключитись віддалено","Підключитись по LAN","Останній збережений знімок"))assertTrue(buttons.any { it.text.toString()==title })
   }
  } finally { inst.runOnMainSync { activity.finish() } }
 }
}
