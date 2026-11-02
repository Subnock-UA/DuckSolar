package ua.ducksolar.b2.client

import android.content.Intent
import android.graphics.Bitmap
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

@RunWith(AndroidJUnit4::class)
class DashboardStyleTest {
 @Test fun syntheticDataLayoutAndCopy() {
  val instrumentation=InstrumentationRegistry.getInstrumentation()
  val context=instrumentation.targetContext
  val a=instrumentation.startActivitySync(Intent(context,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)) as MainActivity
  Thread.sleep(1500)
  val recorded=JSONObject(instrumentation.context.assets.open("dashboard-synthetic-example.json").bufferedReader().readText())
  fun buttons(v:View):List<Button> = if(v is Button)listOf(v) else if(v is ViewGroup)(0 until v.childCount).flatMap { buttons(v.getChildAt(it)) } else emptyList()
  instrumentation.runOnMainSync {
   // Stop live refresh only in this screenshot fixture; never replace live data.
   MainActivity::class.java.getDeclaredField("visible").apply { isAccessible=true }.setBoolean(a,false)
   buttons(a.window.decorView).first { it.text.toString()=="Головна" }.performClick()
   MainActivity::class.java.getDeclaredMethod("render",JSONObject::class.java).apply { isAccessible=true }.invoke(a,recorded)
   val flow=MainActivity::class.java.getDeclaredField("flow").apply { isAccessible=true }.get(a) as FlowDiagram
   assertTrue(flow.contentDescription.toString().contains("Daxtromn"))
   assertTrue(flow.performLongClick())
   assertTrue(a.applicationInfo.icon!=0)
   assertEquals(android.content.pm.ActivityInfo.SCREEN_ORIENTATION_PORTRAIT,a.requestedOrientation)
  }
  Thread.sleep(3000)
  instrumentation.uiAutomation.takeScreenshot().useBitmap { bitmap ->
   File(context.filesDir,"DASHBOARD_SYNTHETIC_EXAMPLE.png").outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG,100,it) }
  }
  instrumentation.runOnMainSync { a.finish() }
 }
 private fun Bitmap.useBitmap(block:(Bitmap)->Unit) { try { block(this) } finally { recycle() } }
}
