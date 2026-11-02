package ua.ducksolar.b2.server
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.json.JSONObject
import java.io.File
import ua.ducksolar.shared.LanSupportClient

@RunWith(AndroidJUnit4::class)
class UpdateCheckpointTest {
    @Test fun stoppedCheckpointPreservesIdentityAndRejectsRunningServer() {
        val context=InstrumentationRegistry.getInstrumentation().targetContext
        Bridge.initialize(context);Bridge.start("","",true)
        try {
            var rejected=false
            try { Bridge.updateCheckpoint("test-only") } catch(_:Exception) { rejected=true }
            assertTrue(rejected)
        } finally { Bridge.stop() }
        val root=File(context.filesDir,"DuckSolar")
        val identity=File(root,"Data/DS_Security/server.pem")
        val before=LanSupportClient.sha256(identity)
        val result=Bridge.updateCheckpoint("test-only")
        val folder=File(root,"UpdateCheckpoints/${result.getString("checkpoint")}")
        val manifest=JSONObject(File(folder,"manifest.json").readText())
        val entries=manifest.getJSONArray("files")
        for(i in 0 until entries.length()) {
            val row=entries.getJSONObject(i)
            assertEquals(row.getString("sha256"),LanSupportClient.sha256(File(folder,row.getString("path"))))
        }
        assertEquals(before,LanSupportClient.sha256(identity))
        assertEquals("ok",Bridge.verifyAfterUpdate().getString("integrity"))
        assertFalse(File(folder,"Logs").exists())
        File(context.filesDir,"UPDATE_CHECKPOINT_RESULT.json").writeText(JSONObject()
            .put("running_rejected",true).put("identity_preserved",true).put("sqlite_integrity","ok")
            .put("files",entries.length()).put("logs_not_duplicated",true).toString())
    }
}
