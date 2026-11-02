package ua.ducksolar.b2.server
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.json.JSONObject
@RunWith(AndroidJUnit4::class)
class CachePatchTest {
 @Test fun cacheReuseNativeAndBackgroundJob() {
  assertEquals(30,android.os.Build.VERSION.SDK_INT)
  val context=InstrumentationRegistry.getInstrumentation().targetContext
  if(!Python.isStarted())Python.start(AndroidPlatform(context))
  val result=JSONObject(Python.getInstance().getModule("cache_patch_checks").callAttr("run",context.cacheDir.absolutePath).toString())
  assertTrue(result.getBoolean("passed"));assertEquals(12,result.getInt("checks"))
 }
 @Test fun closingCacheScreenKeepsServerTaskAlive() {
  val ins=InstrumentationRegistry.getInstrumentation();val context=ins.targetContext
  if(!Python.isStarted())Python.start(AndroidPlatform(context))
  val module=Python.getInstance().getModule("cache_patch_checks")
  module.callAttr("ui_setup",context.cacheDir.absolutePath)
  var activity:android.app.Activity?=null
  try {
   activity=ins.startActivitySync(android.content.Intent(context,CacheActivity::class.java).addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK))
   ins.waitForIdleSync()
   fun button(view:android.view.View):android.widget.Button? {
    if(view is android.widget.Button && view.text.toString().startsWith("Підготувати"))return view
    if(view is android.view.ViewGroup)for(i in 0 until view.childCount) { val found=button(view.getChildAt(i));if(found!=null)return found }
    return null
   }
   // Wait for the initial status request to release this screen's UI executor.
   Thread.sleep(300)
   ins.runOnMainSync { button(activity!!.findViewById(android.R.id.content))!!.performClick() }
   val before=JSONObject(module.callAttr("ui_started").toString())
   ins.runOnMainSync { activity!!.finish() };ins.waitForIdleSync()
   val after=JSONObject(module.callAttr("ui_after_close").toString())
   assertEquals(before.getString("run_id"),after.getString("run_id"));assertEquals("completed",after.getString("state"))
  } finally {
   activity?.let { if(!it.isFinishing)ins.runOnMainSync { it.finish() } }
   module.callAttr("ui_cleanup")
  }
 }
}
