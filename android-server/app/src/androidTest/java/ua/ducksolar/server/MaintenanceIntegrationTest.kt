package ua.ducksolar.b2.server
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import java.io.File
import org.json.JSONObject
import ua.ducksolar.shared.LanSupportClient

@RunWith(AndroidJUnit4::class)
class MaintenanceIntegrationTest {
    @Test fun resourceDiagnosticsReceiveAckAndKeepOriginal() {
        val context=InstrumentationRegistry.getInstrumentation().targetContext
        Bridge.initialize(context)
        val resource=File(context.filesDir,"DuckSolar/Logs/AndroidResources/resources.jsonl")
        assertTrue(resource.exists())
        val original=LanSupportClient.sha256(resource)
        ServerMaintenance.sync(context,"http://127.0.0.1:18766")
        val state=JSONObject(File(context.filesDir,"BackupState.json").readText())
        assertTrue(state.has("diagnostic/AndroidResources_resources.jsonl"))
        assertEquals(original,LanSupportClient.sha256(resource))
        ServerMaintenance.sync(context,"http://127.0.0.1:18766")
        assertEquals(original,LanSupportClient.sha256(resource))
        File(context.filesDir,"RESOURCE_BACKUP_RESULT.json").writeText(JSONObject()
            .put("resource_ack",true).put("original_preserved",true).put("repeat_ack",true).toString())
    }
}
