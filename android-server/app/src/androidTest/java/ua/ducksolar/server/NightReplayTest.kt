package ua.ducksolar.b2.server
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import android.os.Debug
import java.io.File
import org.json.JSONObject
@RunWith(AndroidJUnit4::class)
class NightReplayTest {
 @Test fun realSizeHistoryUsesDiskAndAppendsOnlyNewRows() {
  val context=InstrumentationRegistry.getInstrumentation().targetContext
  Bridge.initialize(context)
  val before=Debug.MemoryInfo();Debug.getMemoryInfo(before)
  val active=java.util.concurrent.atomic.AtomicBoolean(true)
  val peak=java.util.concurrent.atomic.AtomicInteger(before.totalPss)
  val sampler=Thread { while(active.get()) { val value=Debug.MemoryInfo();Debug.getMemoryInfo(value);peak.updateAndGet { maxOf(it,value.totalPss) };Thread.sleep(250) } }
  sampler.start()
  try {
   val report=JSONObject(com.chaquo.python.Python.getInstance().getModule("android_performance_checks")
     .callAttr("run",context.cacheDir.absolutePath,"/data/local/tmp/ds-night.csv").toString())
   report.put("before_kib",before.totalPss).put("peak_kib",peak.get())
   assertTrue(report.getInt("rows")>7000)
   assertEquals(1,report.getInt("appended_rows_parsed"))
   assertTrue("History replay exceeds 64MiB additional PSS",peak.get()-before.totalPss<65536)
   File(context.filesDir,"NIGHT_REPLAY_RESULT.json").writeText(report.toString())
  } finally { active.set(false);sampler.join(2000) }
 }
}
