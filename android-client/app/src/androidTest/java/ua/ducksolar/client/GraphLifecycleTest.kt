package ua.ducksolar.b2.client
import android.app.*
import android.os.Bundle
import android.content.Intent
import android.view.*
import android.widget.*
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import java.util.concurrent.atomic.AtomicReference
@RunWith(AndroidJUnit4::class)
class GraphLifecycleTest {
 @Test fun fourPeriodsRecreationAndCancellationKeepGraphsIndependent() {
  val inst=InstrumentationRegistry.getInstrumentation();val context=inst.targetContext;ClientBridge.initialize(context)
  val fixture=com.chaquo.python.Python.getInstance().getModule("navigation_fixture");fixture.callAttr("install")
  val current=AtomicReference<Activity?>();val app=context.applicationContext as Application
  val observer=object:Application.ActivityLifecycleCallbacks {
   override fun onActivityResumed(a:Activity) { if(a is MainActivity)current.set(a) }
   override fun onActivityCreated(a:Activity,b:Bundle?) {} override fun onActivityStarted(a:Activity) {} override fun onActivityPaused(a:Activity) {} override fun onActivityStopped(a:Activity) {} override fun onActivitySaveInstanceState(a:Activity,b:Bundle) {} override fun onActivityDestroyed(a:Activity) {}
  }
  fun views(v:View):List<View> = listOf(v)+(if(v is ViewGroup)(0 until v.childCount).flatMap { views(v.getChildAt(it)) } else emptyList())
  fun click(title:String) { inst.runOnMainSync { views(current.get()!!.window.decorView).filterIsInstance<Button>().first { it.isShown && it.text.toString()==title }.performClick() } }
  fun waitDone(previous:String="") { val end=System.currentTimeMillis()+8000;while(System.currentTimeMillis()<end) { val state=ClientBridge.graphStatus();if(state.optString("query_id")!=previous && state.optString("state") in listOf("complete","error","cancelled"))return;Thread.sleep(60) } }
  app.registerActivityLifecycleCallbacks(observer)
  try {
   current.set(inst.startActivitySync(Intent(context,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)))
   Thread.sleep(700);click("Графіки")
   for(i in 0..3) {
    inst.runOnMainSync { views(current.get()!!.window.decorView).filterIsInstance<Spinner>().first { it.isShown }.setSelection(i) }
    Thread.sleep(1100)
    inst.runOnMainSync { assertEquals(i,views(current.get()!!.window.decorView).filterIsInstance<Spinner>().first { it.isShown }.selectedItemPosition) }
    val previous=ClientBridge.graphStatus().optString("query_id");click("Побудувати");waitDone(previous);assertEquals("complete",ClientBridge.graphStatus().getString("state"));Thread.sleep(1100)
    assertEquals(listOf("day","month","year","all")[i],ClientBridge.graphStatus().getString("period"))
   }
   fixture.callAttr("delay",3);val before=fixture.callAttr("calls").toInt();click("Побудувати");Thread.sleep(300)
   val query=ClientBridge.graphStatus().getString("query_id");val old=current.get()!!;inst.runOnMainSync { old.recreate() }
   val end=System.currentTimeMillis()+5000;while(current.get()===old && System.currentTimeMillis()<end)Thread.sleep(50)
   assertNotSame(old,current.get());assertEquals(query,ClientBridge.graphStatus().getString("query_id"));waitDone();assertEquals(before+1,fixture.callAttr("calls").toInt())
   Thread.sleep(1200);fixture.callAttr("delay",10);click("Побудувати");Thread.sleep(350);click("Скасувати");waitDone();assertEquals("cancelled",ClientBridge.graphStatus().getString("state"))
  } finally { inst.runOnMainSync { current.get()?.finish() };app.unregisterActivityLifecycleCallbacks(observer);fixture.callAttr("restore") }
 }
}
