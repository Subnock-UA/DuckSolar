package ua.ducksolar.b2.server
import android.content.Context
import android.content.Intent
import android.app.ActivityManager
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import java.io.File
import org.json.JSONObject

@RunWith(AndroidJUnit4::class)
class ServerCompletionTest {
    private val context get()=InstrumentationRegistry.getInstrumentation().targetContext
    private fun await(check:()->Boolean) {
        val end=System.currentTimeMillis()+30000
        while(!check() && System.currentTimeMillis()<end)Thread.sleep(100)
        assertTrue(Bridge.state,check())
    }
    private fun stopped():Boolean {
        val manager=context.getSystemService(ActivityManager::class.java)
        return !Bridge.status().optBoolean("running") && manager.getRunningServices(50).none { it.service.className==ServerService::class.java.name }
    }
    @Test fun bootGateAndManualStopAndSavedSettings() {
        val instrumentation=InstrumentationRegistry.getInstrumentation()
        instrumentation.startActivitySync(Intent(context,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
        Bridge.initialize(context)
        val prefs=context.getSharedPreferences("MainActivity",Context.MODE_PRIVATE)
        val saved=prefs.all.filterKeys { it in listOf("auto_boot","server_enabled","offline") }
        try {
            prefs.edit().remove("auto_boot").putBoolean("server_enabled",true).putBoolean("offline",true).commit()
            BootReceiver().onReceive(context,Intent(Intent.ACTION_BOOT_COMPLETED));Thread.sleep(200)
            assertFalse("Autoboot must default OFF",Bridge.status().optBoolean("running"))
            prefs.edit().putBoolean("auto_boot",true).putBoolean("server_enabled",false).commit()
            BootReceiver().onReceive(context,Intent(Intent.ACTION_BOOT_COMPLETED));Thread.sleep(200)
            assertFalse("Manual stop must veto reboot start",Bridge.status().optBoolean("running"))
            prefs.edit().putBoolean("server_enabled",true).commit()
            BootReceiver().onReceive(context,Intent(Intent.ACTION_BOOT_COMPLETED))
            await { Bridge.status().optBoolean("running") }
            assertEquals("offline",Bridge.status().getString("mode"))
            val pin=Bridge.status().getString("fingerprint")
            context.stopService(Intent(context,ServerService::class.java));await { stopped() }
            // Null-intent restart must restore saved configuration, not invent new defaults.
            context.startForegroundService(Intent(context,ServerService::class.java));await { Bridge.status().optBoolean("running") }
            assertEquals(pin,Bridge.status().getString("fingerprint"))
            prefs.edit().putBoolean("server_enabled",false).commit()
            context.startService(Intent(context,ServerService::class.java).setAction("STOP"));await { stopped() }
            BootReceiver().onReceive(context,Intent(Intent.ACTION_BOOT_COMPLETED));Thread.sleep(200)
            assertFalse(Bridge.status().optBoolean("running"))
            File(context.filesDir,"SERVER_COMPLETION_RESULT.json").writeText(JSONObject()
                .put("boot_default_off",true).put("boot_opt_in",true).put("manual_stop_veto",true)
                .put("saved_settings_restart",true).put("identity_preserved",true).toString())
        } finally {
            context.stopService(Intent(context,ServerService::class.java));Bridge.stop()
            val edit=prefs.edit()
            for(key in listOf("auto_boot","server_enabled","offline")) {
                if(saved.containsKey(key))edit.putBoolean(key,saved[key] as Boolean) else edit.remove(key)
            };edit.commit()
        }
    }
    @Test fun boundedDiagnosticsAndResources() {
        val file=File(context.cacheDir,"diagnostic-fixture.log")
        try {
            file.bufferedWriter().use { out ->
                repeat(12000) { out.write("test-line-$it "+"x".repeat(128)+"\n") }
                out.write("Authorization: Bearer secret-test-token\n")
            }
            val text=DiagnosticView.tail(file,16384)
            assertTrue(text.length<=16384);assertTrue(text.lines().size<=40)
            assertFalse(text.contains("secret-test-token"));assertTrue(text.contains("REDACTED"))
            val empty=DiagnosticView.tail(File(context.cacheDir,"missing-diagnostic-fixture"),16384)
            assertEquals("",empty)
            val resources=ResourceJournal(context);resources.start()
            try {
                val end=System.currentTimeMillis()+5000
                while(!DiagnosticView.resources(context).contains("ОЗП") && System.currentTimeMillis()<end)Thread.sleep(50)
                assertTrue(DiagnosticView.resources(context).contains("ОЗП"))
                assertTrue(DiagnosticView.resources(context).contains("Вільне сховище"))
            } finally { resources.stop() }
        } finally { file.delete() }
    }
}
