package ua.ducksolar.b2.client
import android.app.*
import android.os.Bundle
import android.os.SystemClock
import android.content.Intent
import android.content.res.Configuration
import android.graphics.Bitmap
import android.graphics.Canvas
import android.view.*
import android.widget.*
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import java.io.File
import java.util.concurrent.atomic.AtomicReference
@RunWith(AndroidJUnit4::class)
class GraphPresentationTest {
 @Test fun chartDominatesScreenGesturesAndLandscapeViewerWork() {
  assertEquals(33,android.os.Build.VERSION.SDK_INT)
  val inst=InstrumentationRegistry.getInstrumentation();val context=inst.targetContext;ClientBridge.initialize(context)
  val fixture=com.chaquo.python.Python.getInstance().getModule("navigation_fixture");fixture.callAttr("install")
  val current=AtomicReference<Activity?>();val app=context.applicationContext as Application
  val observer=object:Application.ActivityLifecycleCallbacks {
   override fun onActivityResumed(a:Activity) { current.set(a) }
   override fun onActivityCreated(a:Activity,b:Bundle?) {} override fun onActivityStarted(a:Activity) {} override fun onActivityPaused(a:Activity) {} override fun onActivityStopped(a:Activity) {} override fun onActivitySaveInstanceState(a:Activity,b:Bundle) {} override fun onActivityDestroyed(a:Activity) {}
  }
  fun views(v:View):List<View> = listOf(v)+(if(v is ViewGroup)(0 until v.childCount).flatMap { views(v.getChildAt(it)) } else emptyList())
  fun click(title:String) { inst.runOnMainSync { views(current.get()!!.window.decorView).filterIsInstance<Button>().first { it.isShown && it.text.toString()==title }.performClick() } }
  fun screenshot(name:String) { inst.runOnMainSync { val view=current.get()!!.window.decorView;val bitmap=Bitmap.createBitmap(view.width,view.height,Bitmap.Config.ARGB_8888);view.draw(Canvas(bitmap));File(context.cacheDir,name).outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG,100,it) };bitmap.recycle() } }
  app.registerActivityLifecycleCallbacks(observer)
  try {
   context.getSharedPreferences("Graphs",Activity.MODE_PRIVATE).edit().putInt("period",0).putInt("mode",0).putInt("group",0).putBoolean("automatic",false).commit()
   current.set(inst.startActivitySync(Intent(context,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)))
   Thread.sleep(700);click("Графіки");Thread.sleep(300);click("Побудувати")
   val end=System.currentTimeMillis()+8000;while(ClientBridge.graphStatus().optString("state")!="complete" && System.currentTimeMillis()<end)Thread.sleep(100)
   assertEquals("complete",ClientBridge.graphStatus().optString("state"))
   // Cold ART startup may defer the plot's adaptive layout beyond a fixed sleep.
   // Wait for the actual viewport geometry; keep the same final assertions.
   var geometryReady=false;val geometryDeadline=System.currentTimeMillis()+8000
   while(!geometryReady && System.currentTimeMillis()<geometryDeadline) {
    inst.runOnMainSync {
     val candidate=views(current.get()!!.window.decorView).filterIsInstance<HistoryChart>().firstOrNull { it.isShown }
     if(candidate!=null) {
      var ancestor=candidate.parent;while(ancestor !is ScrollView && ancestor is View)ancestor=ancestor.parent
      if(ancestor is ScrollView) {
       val top=IntArray(2);val boundary=IntArray(2);candidate.getLocationOnScreen(top);ancestor.getLocationOnScreen(boundary)
       geometryReady=candidate.height>180*context.resources.displayMetrics.density && top[1]+candidate.height<=boundary[1]+ancestor.height
      }
     }
    }
    if(!geometryReady)Thread.sleep(100)
   }
   inst.runOnMainSync {
    val all=views(current.get()!!.window.decorView);val chart=all.filterIsInstance<HistoryChart>().first { it.isShown }
    assertTrue(chart.height>180*context.resources.displayMetrics.density)
    var container=chart.parent;while(container !is ScrollView && container is View)container=container.parent
    val position=IntArray(2);val boundary=IntArray(2);chart.getLocationOnScreen(position);(container as ScrollView).getLocationOnScreen(boundary)
    val decor=current.get()!!.window.decorView
    val diagnostic=Bitmap.createBitmap(decor.width,decor.height,Bitmap.Config.ARGB_8888);decor.draw(Canvas(diagnostic))
    File(context.cacheDir,"graph-geometry-a1.6.15.png").outputStream().use { diagnostic.compress(Bitmap.CompressFormat.PNG,100,it) };diagnostic.recycle()
    assertTrue("chartTop=${position[1]} chartHeight=${chart.height} viewportTop=${boundary[1]} viewportHeight=${container.height}",position[1]+chart.height<=boundary[1]+container.height)
    assertFalse(all.filterIsInstance<CheckBox>().any { it.isShown && it.text.toString().contains("Автооновлення") })
    val start=SystemClock.uptimeMillis();val center=chart.width/2f;val y=chart.height/2f
    fun event(time:Long,action:Int,xs:List<Float>) {
     val props=xs.indices.map { MotionEvent.PointerProperties().apply { id=it;toolType=MotionEvent.TOOL_TYPE_FINGER } }.toTypedArray()
     val coords=xs.map { MotionEvent.PointerCoords().apply { x=it;this.y=y;pressure=1f;size=1f } }.toTypedArray()
     val e=MotionEvent.obtain(start,time,action,xs.size,props,coords,0,0,1f,1f,0,0,InputDevice.SOURCE_TOUCHSCREEN,0);chart.dispatchTouchEvent(e);e.recycle()
    }
    event(start,MotionEvent.ACTION_DOWN,listOf(center-80))
    event(start+30,MotionEvent.ACTION_POINTER_DOWN or (1 shl MotionEvent.ACTION_POINTER_INDEX_SHIFT),listOf(center-80,center+80))
    event(start+70,MotionEvent.ACTION_MOVE,listOf(center-180,center+180))
    event(start+90,MotionEvent.ACTION_MOVE,listOf(center-240,center+240))
    event(start+120,MotionEvent.ACTION_POINTER_UP or (1 shl MotionEvent.ACTION_POINTER_INDEX_SHIFT),listOf(center-240,center+240))
    event(start+150,MotionEvent.ACTION_UP,listOf(center-240))
    val zoom=HistoryChart::class.java.getDeclaredField("zoom").apply { isAccessible=true }
    assertTrue(zoom.getDouble(chart)>1)
    for(t in listOf(start+1000,start+1100)) { event(t,MotionEvent.ACTION_DOWN,listOf(center));event(t+30,MotionEvent.ACTION_UP,listOf(center)) }
    assertEquals(1.0,zoom.getDouble(chart),1e-9)
   }
   screenshot("graph-main-a1.6.14.png");click("⛶")
   val landscape=System.currentTimeMillis()+5000;while(current.get() !is GraphFullscreenActivity && System.currentTimeMillis()<landscape)Thread.sleep(100)
   assertTrue(current.get() is GraphFullscreenActivity);Thread.sleep(800)
   assertEquals(Configuration.ORIENTATION_LANDSCAPE,current.get()!!.resources.configuration.orientation)
   screenshot("graph-fullscreen-a1.6.14.png")
  } finally { inst.runOnMainSync { current.get()?.finish() };app.unregisterActivityLifecycleCallbacks(observer);fixture.callAttr("restore") }
 }
}
