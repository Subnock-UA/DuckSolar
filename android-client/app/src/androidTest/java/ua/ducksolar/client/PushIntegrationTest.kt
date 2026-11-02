package ua.ducksolar.b2.client

import android.app.*
import android.content.Intent
import android.view.*
import android.widget.*
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class PushIntegrationTest {
 @Test fun realTlsPushSurvivesBackgroundAndAcknowledgesAllServerKinds() {
  assertEquals(33,android.os.Build.VERSION.SDK_INT)
  val inst=InstrumentationRegistry.getInstrumentation();val context=inst.targetContext
  val args=InstrumentationRegistry.getArguments()
  ClientBridge.initialize(context)
  val fixture=com.chaquo.python.Python.getInstance().getModule("push_client_fixture")
  val prefs=context.getSharedPreferences("alerts",0)
  val switches=(AlertMonitoring.legacy+AlertMonitoring.groups.keys).associateWith { if(prefs.contains(it))prefs.getBoolean(it,false) else null }
  val seen=prefs.getStringSet("seen",emptySet())!!.toSet();val threshold=prefs.getInt("server_battery_threshold",50)
  var activity:Activity?=null;var settings:Activity?=null
  val manager=context.getSystemService(NotificationManager::class.java)
  fun views(view:View):List<View> = listOf(view)+(if(view is ViewGroup)(0 until view.childCount).flatMap { views(view.getChildAt(it)) } else emptyList())
  try {
   fixture.callAttr("install",context.filesDir.absolutePath,args.getString("push_url"),args.getString("push_pin"),args.getString("push_token"))
   val edit=prefs.edit().putStringSet("seen",emptySet()).putInt("server_battery_threshold",55)
   (AlertMonitoring.legacy+AlertMonitoring.groups.keys).forEach { edit.putBoolean(it,true) };edit.commit()
   activity=inst.startActivitySync(Intent(context,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
   inst.runOnMainSync { AlertMonitoring.start(context) }
   val connectedDeadline=System.currentTimeMillis()+15000
   while(!ClientBridge.snapshot().optBoolean("connected") && System.currentTimeMillis()<connectedDeadline)Thread.sleep(100)
   inst.runOnMainSync { activity!!.moveTaskToBack(true) }
   val deadline=System.currentTimeMillis()+45000
   var alerts=manager.activeNotifications.filter { it.tag?.contains(':')==true }
   while(alerts.size<19 && System.currentTimeMillis()<deadline) { Thread.sleep(150);alerts=manager.activeNotifications.filter { it.tag?.contains(':')==true } }
   assertEquals(alerts.joinToString { it.notification.extras.toString() },19,alerts.size)
   val titles=alerts.map { it.notification.extras.getString(Notification.EXTRA_TITLE) }.toSet()
   assertTrue(alerts.all { it.notification.extras.getCharSequence(Notification.EXTRA_TEXT).toString().contains("Подія:") })
   for(title in listOf("Відсутня напруга в мережі","Напруга в мережі відновлена","Заряд батареї сервера не більше 55%","Заряд АКБ не більше 30%"))assertTrue(titles.toString(),title in titles)
   val posts=alerts.associate { it.tag to it.postTime }
   inst.runOnMainSync { activity!!.moveTaskToBack(true) }
   Thread.sleep(35000)
   assertTrue(NotificationService.running)
   val instanceField=NotificationService::class.java.getDeclaredField("instance").apply { isAccessible=true }
   val service=instanceField.get(null)
   val wakeField=NotificationService::class.java.getDeclaredField("wake").apply { isAccessible=true }
   assertFalse("CPU wake lock must be released while idle",(wakeField.get(service) as? android.os.PowerManager.WakeLock)?.isHeld==true)
   assertEquals(posts,manager.activeNotifications.filter { it.tag?.contains(':')==true }.associate { it.tag to it.postTime })
   assertTrue(manager.activeNotifications.any { it.id==4100 && it.notification.flags and Notification.FLAG_FOREGROUND_SERVICE!=0 })
   assertTrue(ClientBridge.snapshot().optBoolean("connected"))
   settings=inst.startActivitySync(Intent(context,NotificationSettingsActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
   Thread.sleep(500)
   inst.runOnMainSync {
    val all=views(settings!!.window.decorView)
    assertEquals(12,all.filterIsInstance<Switch>().size)
    assertEquals("55",all.filterIsInstance<EditText>().first().text.toString())
    assertTrue(all.filterIsInstance<Switch>().all { it.isChecked })
   }
   fixture.callAttr("check_routes",args.getString("push_url"),"https://127.0.0.1:28769")
   Thread.sleep(1000)
   val screenshot=inst.uiAutomation.takeScreenshot()
   java.io.File(context.cacheDir,"notification-settings-a1.6.15.png").outputStream().use {
    screenshot.compress(android.graphics.Bitmap.CompressFormat.PNG,100,it)
   }
   screenshot.recycle()
  } finally {
   context.stopService(Intent(context,NotificationService::class.java))
   Thread.sleep(700)
   fixture.callAttr("restore")
   val edit=prefs.edit().putStringSet("seen",seen).putInt("server_battery_threshold",threshold)
   switches.forEach { (key,value)->if(value==null)edit.remove(key) else edit.putBoolean(key,value) };edit.commit()
   manager.cancelAll();inst.runOnMainSync { settings?.finish();activity?.finish() }
  }
 }
}
