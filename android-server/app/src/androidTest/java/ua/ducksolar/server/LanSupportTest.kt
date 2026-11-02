package ua.ducksolar.b2.server
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import ua.ducksolar.shared.*
import java.io.File
import java.io.RandomAccessFile
import java.net.URL
import org.json.JSONObject

@RunWith(AndroidJUnit4::class)
class LanSupportTest {
    private val context get()=InstrumentationRegistry.getInstrumentation().targetContext
    @Test fun publicHostnamesAndInternetHttpAreRejected() {
        for(url in listOf("http://8.8.8.8:28766","https://192.0.2.24:28766","http://example.com:28766","http://127.0.0.1:28766/other")) {
            try { LanSupportClient(context,url);fail("Invalid helper URL admitted: $url") } catch(_:IllegalArgumentException) { }
        }
    }
    @Test fun apkResumesAndInvalidHashAndDowngradeAreRejected() {
        val client=LanSupportClient(context,"http://127.0.0.1:18766")
        assertEquals(32,client.identity().length)
        val update=client.manifest("server")!!
        val folder=File(context.filesDir,"Updates").apply { mkdirs() }
        val partial=File(folder,"server-${update.sha256}.part")
        File(folder,"server-${update.sha256}.apk").delete()
        URL("http://127.0.0.1:18766/v1/apk/server").openStream().use { input ->
            val first=ByteArray(1024);var count=0;while(count<first.size)count+=input.read(first,count,first.size-count)
            partial.writeBytes(first)
        }
        val ready=client.download(update)
        assertEquals(update.bytes,ready.length());assertEquals(update.sha256,LanSupportClient.sha256(ready))
        try { UpdateInstaller.requireNewer(context,update);fail("Downgrade admitted") } catch(_:IllegalArgumentException) { }
        ready.renameTo(partial)
        RandomAccessFile(partial,"rw").use { it.seek(0);it.writeByte(0) }
        try { client.download(update);fail("Corrupted APK admitted") } catch(_:IllegalArgumentException) { }
        assertFalse(partial.exists())
        File(context.filesDir,"LAN_APK_RESULT.json").writeText(JSONObject().put("resume",true).put("hash_rejected",true).put("downgrade_rejected",true).toString())
    }
    @Test fun backupChunksOriginalAndIdempotentRetry() {
        val client=LanSupportClient(context,"http://127.0.0.1:18766")
        val original=File(context.cacheDir,"fixture-original.csv")
        try {
            val bytes=ByteArray(256*1024+33) { (it%251).toByte() };original.writeBytes(bytes)
            val hash=LanSupportClient.sha256(original)
            assertTrue(client.upload(original,"2".repeat(32),"inverter","fixture-original.csv"))
            assertTrue(client.upload(original,"2".repeat(32),"inverter","fixture-original.csv"))
            assertTrue(original.exists());assertEquals(hash,LanSupportClient.sha256(original))
            original.appendText("new revision")
            assertTrue(client.upload(original,"2".repeat(32),"inverter","fixture-original.csv"))
            File(context.filesDir,"LAN_BACKUP_RESULT.json").writeText(JSONObject().put("chunks",true).put("retry",true).put("original_preserved",true).put("new_revision",true).toString())
        } finally { original.delete() }
    }
    @Test fun diagnosticRedactionPreservesJsonAndRemovesBearer() {
        val input=JSONObject().put("password","secret-value").put("authorization","Bearer private-token").put("number",12).toString()
        val clean=ServerMaintenance.redact(input);val parsed=JSONObject(clean)
        assertEquals("[REDACTED]",parsed.getString("password"));assertEquals(12,parsed.getInt("number"))
        assertFalse(clean.contains("secret-value"));assertFalse(clean.contains("private-token"))
        assertFalse(ServerMaintenance.redact("Authorization: Bearer private-token").contains("private-token"))
    }
    @Test fun differentSigningKeyIsRejected() {
        val client=LanSupportClient(context,"http://127.0.0.1:18766")
        try { client.download(client.manifest("server")!!);fail("APK with another signer admitted") }
        catch(error:IllegalArgumentException) { assertTrue(error.message ?: "",error.message?.contains("підпису")==true) }
    }
}
