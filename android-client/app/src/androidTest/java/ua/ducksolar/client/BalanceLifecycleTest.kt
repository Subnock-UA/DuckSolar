package ua.ducksolar.b2.client

import android.app.Activity
import android.app.Application
import android.os.Bundle
import android.content.Intent
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.TextView
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.util.concurrent.atomic.AtomicReference
import java.io.File
import android.graphics.Bitmap

@RunWith(AndroidJUnit4::class)
class BalanceLifecycleTest {
 @Test fun recreationKeepsSingleJobAndCancelIsExplicit() {
  val inst=InstrumentationRegistry.getInstrumentation();val context=inst.targetContext
  ClientBridge.initialize(context)
  val fixture=com.chaquo.python.Python.getInstance().getModule("client_feature_fixture")
  fixture.callAttr("install",4)
  val current=AtomicReference<Activity?>()
  val app=context.applicationContext as Application
  val observer=object:Application.ActivityLifecycleCallbacks {
   override fun onActivityResumed(a:Activity) { if(a is BalanceActivity)current.set(a) }
   override fun onActivityCreated(a:Activity,b:Bundle?) {}
   override fun onActivityStarted(a:Activity) {}
   override fun onActivityPaused(a:Activity) {}
   override fun onActivityStopped(a:Activity) {}
   override fun onActivitySaveInstanceState(a:Activity,b:Bundle) {}
   override fun onActivityDestroyed(a:Activity) {}
  }
  fun views(v:View):List<View> = listOf(v)+(if(v is ViewGroup)(0 until v.childCount).flatMap { views(v.getChildAt(it)) } else emptyList())
  fun click(title:String) { inst.runOnMainSync { views(current.get()!!.window.decorView).filterIsInstance<Button>().first { it.text.toString()==title }.performClick() } }
  app.registerActivityLifecycleCallbacks(observer)
  try {
   current.set(inst.startActivitySync(Intent(context,BalanceActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)))
   Thread.sleep(1000);click("Оновити баланс");Thread.sleep(400)
   val query=ClientBridge.balanceStatus().getString("query_id")
   val old=current.get()!!;inst.runOnMainSync { old.recreate() }
   var end=System.currentTimeMillis()+5000
   while(current.get()===old && System.currentTimeMillis()<end)Thread.sleep(50)
   assertNotSame(old,current.get());assertEquals(query,ClientBridge.balanceStatus().getString("query_id"))
   end=System.currentTimeMillis()+6000
   while(ClientBridge.balanceStatus().optString("state")=="running" && System.currentTimeMillis()<end)Thread.sleep(50)
   assertEquals("complete",ClientBridge.balanceStatus().optString("state"));assertEquals(1,fixture.callAttr("calls").toInt())
   Thread.sleep(1500)
   inst.runOnMainSync { assertTrue(views(current.get()!!.window.decorView).filterIsInstance<TextView>().any { it.text.toString().contains("сервер не знайшов файлів") }) }
   val bitmap=inst.uiAutomation.takeScreenshot();File(context.filesDir,"BALANCE_SCREEN.png").outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG,100,it) };bitmap.recycle()
   fixture.callAttr("install",10);click("Оновити баланс");Thread.sleep(300);click("Скасувати розрахунок")
   end=System.currentTimeMillis()+5000
   while(ClientBridge.balanceStatus().optString("state") in listOf("running","cancelling") && System.currentTimeMillis()<end)Thread.sleep(50)
   assertEquals("cancelled",ClientBridge.balanceStatus().optString("state"));assertEquals(1,fixture.callAttr("calls").toInt())
  } finally {
   inst.runOnMainSync { current.get()?.finish() };app.unregisterActivityLifecycleCallbacks(observer);fixture.callAttr("restore")
  }
 }
}
