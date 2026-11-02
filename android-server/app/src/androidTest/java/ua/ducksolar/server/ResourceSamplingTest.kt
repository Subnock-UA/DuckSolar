package ua.ducksolar.b2.server
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import java.io.File
import org.json.JSONObject

@RunWith(AndroidJUnit4::class)
class ResourceSamplingTest {
 @Test fun cpuWindowAndTotalCapacity() {
  val context=InstrumentationRegistry.getInstrumentation().targetContext
  val started=System.currentTimeMillis();val journal=ResourceJournal(context)
  try {
   journal.start();val file=File(context.filesDir,"DuckSolar/Logs/AndroidResources/resources.jsonl")
   val end=System.currentTimeMillis()+15000;var row=JSONObject()
   while(System.currentTimeMillis()<end) {
    row=try { JSONObject(DiagnosticView.tail(file,4096).lineSequence().last { it.isNotBlank() }) } catch(_:Exception) { JSONObject() }
    if(row.optLong("time_ms")>=started && row.optLong("sample_ms")>=1000)break
    Thread.sleep(100)
   }
   assertTrue(row.optLong("time_ms")>=started);assertTrue(row.getLong("sample_ms")>=1000)
   val cores=row.getInt("cpu_core_count");assertTrue(cores>=1)
   assertEquals(row.getDouble("cpu_percent_one_core")/cores,row.getDouble("cpu_percent_total"),0.001)
   File(context.filesDir,"CPU_SAMPLE_RESULT.json").writeText(row.toString())
  } finally { journal.stop() }
 }
}
