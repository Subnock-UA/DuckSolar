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
class InverterAppendTest {
    @Test fun appendedDataResumeWithoutFullSnapshotAndPreserveSource() {
        val context=InstrumentationRegistry.getInstrumentation().targetContext
        val client=LanSupportClient(context,"http://127.0.0.1:18766")
        client.identity();assertTrue(client.supportsInverterAppend)
        val name="append-test-${System.currentTimeMillis()}.csv"
        val source=File(context.cacheDir,name)
        try {
            val bytes=ByteArray(256*1024+33) { (it%251).toByte() };source.writeBytes(bytes)
            assertFalse(client.appendInverter(source,"e".repeat(32),name,0))
            assertTrue(client.appendInverter(source,"e".repeat(32),name))
            val before=LanSupportClient.sha256(source)
            assertTrue(client.appendInverter(source,"e".repeat(32),name))
            assertEquals(before,LanSupportClient.sha256(source))
            client.verifyInverter(source,"e".repeat(32),name,source.length())
            source.appendText("new measurements\n")
            assertTrue(client.appendInverter(source,"e".repeat(32),name))
            File(context.filesDir,"INVERTER_APPEND_RESULT.json").writeText(JSONObject()
                .put("source_preserved",true).put("resume",true).put("appended_only",true).put("bytes",source.length()).toString())
        } finally { source.delete() }
    }
}
