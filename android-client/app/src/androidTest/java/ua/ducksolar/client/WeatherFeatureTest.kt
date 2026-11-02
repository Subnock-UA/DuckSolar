package ua.ducksolar.b2.client
import android.app.Activity
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Canvas
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
class WeatherFeatureTest {
 @Test fun forecastCacheRecreationAndOfflineFallback() {
  assertEquals(33,android.os.Build.VERSION.SDK_INT)
  val inst=InstrumentationRegistry.getInstrumentation();val context=inst.targetContext
  ClientBridge.initialize(context)
  val fixture=com.chaquo.python.Python.getInstance().getModule("weather_fixture")
  fixture.callAttr("install",context.cacheDir.absolutePath)
  var activity:Activity?=null
  fun views(v:View):List<View> = listOf(v)+(if(v is ViewGroup)(0 until v.childCount).flatMap { views(v.getChildAt(it)) } else emptyList())
  fun waitFor(test:()->Boolean) { val end=System.currentTimeMillis()+15000;while(!test() && System.currentTimeMillis()<end)Thread.sleep(100);assertTrue(test()) }
  fun texts():List<String> { var list=listOf<String>();inst.runOnMainSync { list=views(activity!!.window.decorView).filterIsInstance<TextView>().map { it.text.toString() } };return list }
  fun click(text:String) { inst.runOnMainSync { views(activity!!.window.decorView).filterIsInstance<Button>().first { it.text.toString()==text }.performClick() } }
  try {
   activity=inst.startActivitySync(Intent(context,WeatherActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
   waitFor { texts().any { it.contains("Налаштуйте населений") } }
   click("Оновити")
   waitFor { texts().any { it.startsWith("Генерація PV ≈") } }
   assertEquals(10,texts().count { it.startsWith("Генерація PV ≈") })
   assertTrue(texts().any { it.contains("ще без навчання") })
   inst.runOnMainSync { val view=activity!!.window.decorView;val bitmap=Bitmap.createBitmap(view.width,view.height,Bitmap.Config.ARGB_8888);view.draw(Canvas(bitmap));File(context.cacheDir,"weather-screen.png").outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG,100,it) };bitmap.recycle() }
   inst.runOnMainSync { activity!!.finish() }
   activity=inst.startActivitySync(Intent(context,WeatherActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
   waitFor { texts().count { it.startsWith("Генерація PV ≈") }==10 }
   fixture.callAttr("offline");click("Оновити")
   waitFor { texts().any { it.contains("Оновлення не виконано") } }
   assertEquals(10,texts().count { it.startsWith("Генерація PV ≈") })
   assertTrue(ClientBridge.weatherStatus().getJSONObject("result").getBoolean("from_cache"))
  } finally { inst.runOnMainSync { activity?.finish() };fixture.callAttr("restore") }
 }
}
