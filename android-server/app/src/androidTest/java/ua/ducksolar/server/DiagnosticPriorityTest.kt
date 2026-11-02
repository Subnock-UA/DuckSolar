package ua.ducksolar.b2.server

import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import java.io.File
import java.io.RandomAccessFile
import org.json.JSONObject

@RunWith(AndroidJUnit4::class)
class DiagnosticPriorityTest {
    @Test fun manualDiagnosticsExcludeLargeArchiveAndPreserveImportedHistory() {
        val context=InstrumentationRegistry.getInstrumentation().targetContext
        Bridge.initialize(context)
        val root=File(context.filesDir,"DuckSolar")
        val config=File(root,"Server/DS_Server_Beta_2/config.json")
        val previous=if(config.exists())config.readBytes() else null
        val csv=File(root,"Logs/Inverter/2040-01-01.csv")
        val diag=File(root,"Logs/DS_Server_Beta_2/System/priority-test.log")
        val marker=File(root,"ARCHIVE_IMPORT.json")
        val previousMarker=if(marker.exists())marker.readBytes() else null
        try {
            config.parentFile?.mkdirs()
            config.writeText(JSONObject().put("installation_id","d".repeat(32)).toString())
            csv.parentFile?.mkdirs();RandomAccessFile(csv,"rw").use { it.setLength(50L*1024*1024) }
            diag.parentFile?.mkdirs();diag.writeText("diagnostic priority test\n")
            marker.writeText("{\"status\":\"complete\",\"sentinel\":147}")
            val expected=marker.readText()
            Bridge.initialize(context)
            assertEquals(expected,marker.readText())
            val begin=System.currentTimeMillis()
            val result=ServerMaintenance.sync(context,"http://127.0.0.1:18766")
            val state=JSONObject(File(context.filesDir,"BackupState.json").readText())
            assertTrue(state.has("diagnostic/DS_Server_Beta_2_System_priority-test.log"))
            assertFalse(state.has("inverter/2040-01-01.csv"))
            assertFalse(File(context.cacheDir,"InverterBackup/2040-01-01.csv.snapshot").exists())
            assertEquals(50L*1024*1024,csv.length());assertEquals(expected,marker.readText())
            assertTrue(result.contains("діагностику"))
            File(context.filesDir,"DIAGNOSTIC_PRIORITY_RESULT.json").writeText(JSONObject()
                .put("diagnostics_only",true).put("archive_preserved",true)
                .put("large_csv_excluded",true).put("elapsed_ms",System.currentTimeMillis()-begin).toString())
        } finally {
            csv.delete();diag.delete()
            if(previous==null)config.delete() else config.writeBytes(previous)
            if(previousMarker==null)marker.delete() else marker.writeBytes(previousMarker)
        }
    }
}
