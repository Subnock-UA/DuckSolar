package ua.ducksolar.b2.server

import android.content.Context
import android.os.Debug
import android.os.Process
import android.os.SystemClock
import android.os.StatFs
import org.json.JSONObject
import java.io.File
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/** Small, bounded diagnostics with no equipment, account or network secrets. */
class ResourceJournal(context: Context) {
    private val app=context.applicationContext
    private val bridgeWorker=Executors.newSingleThreadExecutor()
    private val pending=java.util.concurrent.atomic.AtomicBoolean(false)
    private val activityManager=context.getSystemService(android.app.ActivityManager::class.java)
    private val root = File(context.filesDir, "DuckSolar/Logs/AndroidResources").apply { mkdirs() }
    private val timer = Executors.newSingleThreadScheduledExecutor()
    private var lastWall = SystemClock.elapsedRealtime()
    private var lastCpu = Process.getElapsedCpuTime()
    fun start() { timer.scheduleWithFixedDelay({ try { sample() } catch (_: Exception) {} }, 2, 15, TimeUnit.SECONDS) }
    private fun sample() {
        val now = SystemClock.elapsedRealtime()
        val cpu = Process.getElapsedCpuTime()
        val memory = Debug.MemoryInfo(); Debug.getMemoryInfo(memory)
        val systemMemory=android.app.ActivityManager.MemoryInfo();activityManager.getMemoryInfo(systemMemory)
        val power=app.getSystemService(android.os.PowerManager::class.java)
        val battery=app.registerReceiver(null,android.content.IntentFilter(android.content.Intent.ACTION_BATTERY_CHANGED))
        val charging=(battery?.getIntExtra(android.os.BatteryManager.EXTRA_PLUGGED,0) ?: 0)!=0
        val status = File("/proc/self/status").readLines()
        val threads = status.firstOrNull { it.startsWith("Threads:") }?.substringAfter(':')?.trim()?.toIntOrNull()
        val row = JSONObject().put("time_ms", System.currentTimeMillis()).put("pid", Process.myPid())
            .put("pss_kib", memory.totalPss).put("private_dirty_kib", memory.totalPrivateDirty)
            .put("available_memory_bytes",systemMemory.availMem).put("memory_threshold_bytes",systemMemory.threshold).put("low_memory",systemMemory.lowMemory)
            .put("cpu_percent_one_core", if (now > lastWall) 100.0 * (cpu-lastCpu)/(now-lastWall) else 0.0)
            .put("cpu_core_count", Runtime.getRuntime().availableProcessors().coerceAtLeast(1))
            .put("sample_ms", now-lastWall)
            .put("native_heartbeat_gap",now-lastWall>45000)
            .put("wifi_networks",JSONObject(ServerNetwork.snapshot()))
            .put("wifi_signal",ServerNetwork.signal(app))
            .put("battery_level",battery?.getIntExtra(android.os.BatteryManager.EXTRA_LEVEL,-1) ?: -1)
            .put("battery_scale",battery?.getIntExtra(android.os.BatteryManager.EXTRA_SCALE,100) ?: 100)
            .put("charging",charging).put("screen_on",power.isInteractive)
            .put("power_save",power.isPowerSaveMode).put("device_idle",power.isDeviceIdleMode)
            .put("battery_optimization_exempt",power.isIgnoringBatteryOptimizations(app.packageName))
            .put("cpu_lock_held",ServerService.cpuHeld).put("wifi_lock_held",ServerService.wifiHeld)
            .put("python_pending",pending.get()).put("foreground",ServerService.foreground)
            .put("cpu_percent_total", if (now-lastWall >= 1000) 100.0*(cpu-lastCpu)/(now-lastWall)/Runtime.getRuntime().availableProcessors().coerceAtLeast(1) else JSONObject.NULL)
            .put("threads", threads ?: JSONObject.NULL).put("open_fds", File("/proc/self/fd").list()?.size ?: -1)
            .put("storage_available_bytes", StatFs(root.absolutePath).availableBytes)
        lastWall = now; lastCpu = cpu
        val target = File(root, "resources.jsonl")
        if (target.length() >= 1024 * 1024) {
            File(root, "resources.3.jsonl").delete()
            for (i in 2 downTo 1) File(root,"resources.$i.jsonl").renameTo(File(root,"resources.${i+1}.jsonl"))
            target.renameTo(File(root,"resources.1.jsonl"))
        }
        target.appendText(row.toString() + "\n")
        // Write native heartbeat before Python; a blocked bridge cannot hide it.
        if(com.chaquo.python.Python.isStarted() && pending.compareAndSet(false,true))bridgeWorker.execute {
            val started=SystemClock.elapsedRealtime()
            try {
                val module=com.chaquo.python.Python.getInstance().getModule("android_bridge")
                module.callAttr("phone_state",battery?.getIntExtra(android.os.BatteryManager.EXTRA_LEVEL,-1) ?: -1,battery?.getIntExtra(android.os.BatteryManager.EXTRA_SCALE,100) ?: 100,charging,row.getJSONObject("wifi_signal").toString())
                module.callAttr("power_state",charging)
                module.callAttr("battery_state",battery?.getIntExtra(android.os.BatteryManager.EXTRA_LEVEL,-1) ?: -1,battery?.getIntExtra(android.os.BatteryManager.EXTRA_SCALE,100) ?: 100)
                module.callAttr("resource_state",systemMemory.availMem,systemMemory.threshold,systemMemory.totalMem,systemMemory.lowMemory)
            } finally {
                pending.set(false)
                android.util.Log.i("DuckSolar","Resource bridge completed in ${SystemClock.elapsedRealtime()-started} ms")
            }
        }
    }
    fun stop() { timer.shutdownNow();bridgeWorker.shutdownNow() }
}
