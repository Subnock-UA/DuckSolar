package ua.ducksolar.b2.server

import android.content.Intent
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import java.io.File
import android.app.ActivityManager
import android.os.Debug
import org.json.JSONArray

@RunWith(AndroidJUnit4::class)
class ServerSmokeTest {
    @Test fun telemetryReconnectAndHistoryFixtures() {
        val context=InstrumentationRegistry.getInstrumentation().targetContext
        Bridge.initialize(context)
        val result=com.chaquo.python.Python.getInstance().getModule("android_fixture_checks")
            .callAttr("run",context.cacheDir.absolutePath).toString()
        val checks=org.json.JSONObject(result)
        assertTrue(checks.getBoolean("fragmented_frames_telemetry_history_reconnect"))
        assertEquals(70,checks.getInt("overflow_spooled_and_replayed"))
        File(context.filesDir,"TELEMETRY_FIXTURE_RESULT.json").writeText(result)
    }
    @Test fun compactMonthAccountingResourceBudget() {
        val context=InstrumentationRegistry.getInstrumentation().targetContext
        Bridge.initialize(context)
        val before=Debug.MemoryInfo();Debug.getMemoryInfo(before)
        val sampling=java.util.concurrent.atomic.AtomicBoolean(true)
        val pss=java.util.Collections.synchronizedList(mutableListOf<Int>())
        val sampler=Thread {
            while(sampling.get()) {
                val sample=Debug.MemoryInfo();Debug.getMemoryInfo(sample);pss.add(sample.totalPss)
                Thread.sleep(250)
            }
        };sampler.start()
        try {
            val result=com.chaquo.python.Python.getInstance().getModule("android_balance_checks")
                .callAttr("run",context.cacheDir.absolutePath,48000,false).toString()
            val checks=org.json.JSONObject(result)
            assertTrue(checks.getBoolean("legacy_totals_match_without_daily_calculation"))
            assertTrue(checks.getLong("response_bytes")<60000)
            sampling.set(false);sampler.join(2000)
            val after=Debug.MemoryInfo();Debug.getMemoryInfo(after)
            checks.put("pss_before_kib",before.totalPss).put("pss_after_kib",after.totalPss)
                .put("pss_peak_kib",pss.maxOrNull() ?: after.totalPss)
            assertTrue(checks.getInt("pss_peak_kib")>0)
            File(context.filesDir,"BALANCE_RESOURCE_RESULT.json").writeText(checks.toString())
        } finally { sampling.set(false);sampler.join(2000) }
    }
    @Test fun compactCacheAndAuditFinalCheck() {
        val context=InstrumentationRegistry.getInstrumentation().targetContext
        Bridge.initialize(context)
        val result=com.chaquo.python.Python.getInstance().getModule("android_balance_checks")
            .callAttr("run",context.cacheDir.absolutePath,120,false).toString()
        File(context.filesDir,"BALANCE_FINAL_CACHE_RESULT.json").writeText(result)
        assertTrue(org.json.JSONObject(result).getBoolean("cache_source_and_config_invalidation"))
    }
    @Test fun repeatedServiceLifecycleKeepsMemoryBounded() {
        val instrumentation=InstrumentationRegistry.getInstrumentation()
        val context=instrumentation.targetContext
        Bridge.initialize(context)
        val samples=JSONArray()
        var pin=""
        instrumentation.startActivitySync(Intent(context,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
        repeat(6) {
            context.startForegroundService(Intent(context,ServerService::class.java).putExtra("offline",true))
            val deadline=System.currentTimeMillis()+30000
            while (!Bridge.status().getBoolean("running") && System.currentTimeMillis()<deadline) Thread.sleep(100)
            assertTrue(Bridge.state,Bridge.status().getBoolean("running"))
            val current=Bridge.status().getString("fingerprint")
            if (pin.isEmpty()) pin=current else assertEquals(pin,current)
            val memory=Debug.MemoryInfo(); Debug.getMemoryInfo(memory)
            samples.put(memory.totalPss)
            context.startService(Intent(context,ServerService::class.java).setAction("STOP"))
            val stopDeadline=System.currentTimeMillis()+15000
            val manager=context.getSystemService(ActivityManager::class.java)
            while (System.currentTimeMillis()<stopDeadline &&
                (Bridge.status().getBoolean("running") || manager.getRunningServices(50).any { it.service.className==ServerService::class.java.name })) Thread.sleep(100)
            assertFalse(Bridge.status().getBoolean("running"))
            assertFalse(manager.getRunningServices(50).any { it.service.className==ServerService::class.java.name })
            var closed=false
            try { java.net.Socket().use { it.connect(java.net.InetSocketAddress("127.0.0.1",28766),1000) } }
            catch (_:java.io.IOException) { closed=true }
            assertTrue("API port must close after stop",closed)
        }
        assertTrue("Unexpected PSS growth across restarts",samples.getInt(5)-samples.getInt(1)<32*1024)
        File(context.filesDir,"LIFECYCLE_PSS_KIB.json").writeText(samples.toString())
    }
    @Test fun pythonTlsSqliteAndServiceLifecycle() {
        val instrumentation=InstrumentationRegistry.getInstrumentation()
        val context=instrumentation.targetContext
        Bridge.initialize(context)
        val checks=Bridge.selfTest()
        assertTrue(checks.getBoolean("tls13"))
        assertEquals("ok", checks.getString("sqlite_integrity"))
        assertEquals(0, checks.getJSONArray("desktop_modules_loaded").length())
        instrumentation.startActivitySync(Intent(context,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
        context.startForegroundService(Intent(context,ServerService::class.java).putExtra("offline",true))
        val deadline=System.currentTimeMillis()+60000
        while (!Bridge.status().getBoolean("running") && System.currentTimeMillis()<deadline) Thread.sleep(500)
        assertTrue(Bridge.state,Bridge.status().getBoolean("running"))
        val fingerprint=Bridge.status().getString("fingerprint")
        assertEquals(64,fingerprint.length)
        assertEquals(8,Bridge.pairingCode().length)
        context.startService(Intent(context,ServerService::class.java).setAction("STOP"))
        val stopDeadline=System.currentTimeMillis()+30000
        while (Bridge.status().getBoolean("running") && System.currentTimeMillis()<stopDeadline) Thread.sleep(200)
        assertFalse(Bridge.status().getBoolean("running"))
        Thread.sleep(1500)
        Bridge.start("","",true)
        assertEquals(fingerprint,Bridge.status().getString("fingerprint"))
        assertTrue(Bridge.status().getBoolean("month_balance_available"))
        File(context.filesDir,"INSTRUMENTATION_RESULT.json").writeText(checks.toString(2))
        Bridge.stop()
    }
}
