package ua.ducksolar.b2.server
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.json.JSONObject
@RunWith(AndroidJUnit4::class)
class CompactMigrationTest {
 @Test fun compactWriterRecoveryReadersAndMaintenance() {
  assertEquals(30,android.os.Build.VERSION.SDK_INT)
  val context=InstrumentationRegistry.getInstrumentation().targetContext;Bridge.initialize(context)
  val result=JSONObject(com.chaquo.python.Python.getInstance().getModule("compact_patch_checks").callAttr("run",context.cacheDir.absolutePath).toString())
  assertTrue(result.getBoolean("passed"));assertEquals(5,result.getInt("tests"))
 }
}
