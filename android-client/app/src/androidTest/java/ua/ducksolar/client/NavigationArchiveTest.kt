package ua.ducksolar.b2.client
import android.app.Activity
import android.content.Intent
import android.graphics.Bitmap
import android.view.View
import android.view.ViewGroup
import android.widget.*
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import java.io.File
@RunWith(AndroidJUnit4::class)
class NavigationArchiveTest {
 @Test fun fourTabsSeparateSubmenusEssSourceAndBoundedChart() {
  assertEquals(33,android.os.Build.VERSION.SDK_INT)
  val inst=InstrumentationRegistry.getInstrumentation();val context=inst.targetContext
  ClientBridge.initialize(context)
  val fixture=com.chaquo.python.Python.getInstance().getModule("navigation_fixture");fixture.callAttr("install")
  val main=inst.startActivitySync(Intent(context,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
  fun views(v:View):List<View> = listOf(v)+(if(v is ViewGroup)(0 until v.childCount).flatMap { views(v.getChildAt(it)) } else emptyList())
  fun click(title:String) { inst.runOnMainSync { views(main.window.decorView).filterIsInstance<Button>().first { it.isShown && it.text.toString()==title }.performClick() } }
  fun shot(name:String) { val image=inst.uiAutomation.takeScreenshot();File(context.filesDir,name).outputStream().use { image.compress(Bitmap.CompressFormat.PNG,100,it) };image.recycle() }
  try {
   Thread.sleep(700);click("Додатково")
   inst.runOnMainSync {
    val buttons=views(main.window.decorView).filterIsInstance<Button>().filter { it.isShown }.map { it.text.toString() }
    assertTrue(buttons.containsAll(listOf("Головна","Моніторинг","Графіки","Додатково","Налаштування","Зв’язок з ПК","Місячний баланс","Показники лічильників")))
    assertFalse(views(main.window.decorView).filterIsInstance<EditText>().any { it.isShown })
   };shot("EXTRA_MENU.png")
   click("Зв’язок з ПК");inst.runOnMainSync { assertTrue(views(main.window.decorView).filterIsInstance<Button>().any { it.isShown && it.text.toString()=="Перевірити оновлення" }) };shot("PC_SUBMENU.png")
   click("‹ Додатково");click("Налаштування")
   inst.runOnMainSync { assertTrue(views(main.window.decorView).filterIsInstance<EditText>().count { it.isShown }>=6) }
   click("‹ Додатково");click("Графіки")
   inst.runOnMainSync { views(main.window.decorView).filterIsInstance<Spinner>().filter { it.isShown }[1].setSelection(2) }
   click("Побудувати графік")
   val end=System.currentTimeMillis()+8000
   while(ClientBridge.graphStatus().optString("state")!="complete" && System.currentTimeMillis()<end)Thread.sleep(50)
   assertEquals("complete",ClientBridge.graphStatus().optString("state"));assertEquals("SmartESS",ClientBridge.graphStatus().optString("source"))
   Thread.sleep(1500)
   inst.runOnMainSync { assertTrue(views(main.window.decorView).any { it is HistoryChart && it.isShown });assertFalse(views(main.window.decorView).filterIsInstance<Button>().any { it.isShown && it.text.toString()=="Додати показники лічильника" }) }
   shot("GRAPHS_ESS.png")
   inst.runOnMainSync { assertFalse(views(main.window.decorView).filterIsInstance<Button>().any { it.isShown && it.text.toString()=="Оновити баланс" }) }
   inst.runOnMainSync { views(main.window.decorView).filterIsInstance<ScrollView>().first { it.isShown }.fullScroll(View.FOCUS_DOWN) }
   Thread.sleep(400);shot("GRAPH_DAILY.png")
   click("Додатково");click("Показники лічильників")
   inst.runOnMainSync { assertTrue(views(main.window.decorView).filterIsInstance<Button>().any { it.isShown && it.text.toString()=="Додати показники лічильника" }) }
   shot("METERS_SUBMENU.png")
  } finally { inst.runOnMainSync { main.finish() };fixture.callAttr("restore") }
 }
}
