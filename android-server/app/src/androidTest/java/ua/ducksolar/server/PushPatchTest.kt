package ua.ducksolar.b2.server
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.json.JSONObject

@RunWith(AndroidJUnit4::class)
class PushPatchTest {
 @Test fun durableAlertsTlsIsolationAndFullResolutionSummaries() {
  assertEquals(30,android.os.Build.VERSION.SDK_INT)
  val context=InstrumentationRegistry.getInstrumentation().targetContext
  Bridge.initialize(context)
  val result=JSONObject(com.chaquo.python.Python.getInstance().getModule("push_patch_checks").callAttr("run",context.cacheDir.absolutePath).toString())
  assertTrue(result.getBoolean("passed"));assertEquals(25,result.getInt("tests"))
  val checks=com.chaquo.python.Python.getInstance().getModule("push_patch_checks")
  checks.callAttr("prepare_battery",context.cacheDir.absolutePath)
  try {
   com.chaquo.python.Python.getInstance().getModule("android_bridge").callAttr("battery_state",49,100)
   assertTrue(checks.callAttr("verify_battery").toBoolean())
  } finally { checks.callAttr("restore_battery") }
 }
}
