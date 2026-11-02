package ua.ducksolar.b2.server
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.chaquo.python.Python
import android.os.Debug
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

@RunWith(AndroidJUnit4::class)
class RecordedBalanceTest {
 @Test fun realArchiveTiming() {
  val instrumentation=InstrumentationRegistry.getInstrumentation()
  val context=instrumentation.targetContext
  Bridge.initialize(context)
  val before=Debug.MemoryInfo();Debug.getMemoryInfo(before)
  val tracking=java.util.concurrent.atomic.AtomicBoolean(true)
  val peak=java.util.concurrent.atomic.AtomicInteger(before.totalPss)
  val sampler=Thread { while(tracking.get()) { val mem=Debug.MemoryInfo();Debug.getMemoryInfo(mem);peak.updateAndGet { maxOf(it,mem.totalPss) };Thread.sleep(200) } };sampler.start()
  try {
   val source=instrumentation.context.assets.open("recorded_balance_performance.py").bufferedReader().readText()
   val py=Python.getInstance();val scope=py.getModule("builtins").callAttr("dict")
   scope.callAttr("__setitem__","performance_root",context.cacheDir.absolutePath)
   py.getModule("builtins").callAttr("exec",source,scope)
   val result=JSONObject(py.getModule("json").callAttr("dumps",scope.callAttr("__getitem__","performance_result")).toString())
   result.put("pss_before_kib",before.totalPss).put("pss_peak_kib",peak.get())
   assertTrue(result.getInt("first_count")>20000)
   assertTrue("Real archive exceeds 64MiB memory budget",peak.get()-before.totalPss<65536)
   File(context.filesDir,"RECORDED_BALANCE_PERFORMANCE.json").writeText(result.toString())
  } finally { tracking.set(false);sampler.join(2000) }
 }
 @Test fun allPcMeterReadingsPersist() {
  val context=InstrumentationRegistry.getInstrumentation().targetContext
  Bridge.initialize(context)
  val source="""
from pathlib import Path
from ducksolar.config import AppConfig
from ducksolar.storage import Storage
from ducksolar.meter_bootstrap import import_snapshot
import json
root=Path(meter_root)/'DuckSolar'
storage=Storage(AppConfig(root_dir=str(root)))
before=storage.list_meter_readings(limit=10000)
assert len(before)==5 and before[0]['reading_date']=='2026-10-08 15:42:00'
assert before[0]['import_day']==2352.08 and before[0]['export_day']==3263.27
assert import_snapshot(root)['already_imported']
assert storage.list_meter_readings(limit=10000)==before
""".trimIndent()
  val py=Python.getInstance();val scope=py.getModule("builtins").callAttr("dict")
  scope.callAttr("__setitem__","meter_root",context.filesDir.absolutePath)
  py.getModule("builtins").callAttr("exec",source,scope)
 }
}
