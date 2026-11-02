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
class ArchiveSyncTest {
 @Test fun savedEndpointRecoveryHasNoHardwareSideEffects() {
  val context=InstrumentationRegistry.getInstrumentation().targetContext;Bridge.initialize(context);Bridge.stop()
  val result=com.chaquo.python.Python.getInstance().getModule("sync_checks").callAttr("recovery_fixture").toString()
  assertFalse(JSONObject(result).getBoolean("hardware_changed"));File(context.filesDir,"ENDPOINT_RECOVERY_FIXTURE.json").writeText(result)
 }
 @Test fun readonlyEssDownloadFixtureAndMissingValues() {
  val context=InstrumentationRegistry.getInstrumentation().targetContext;Bridge.initialize(context)
  val result=com.chaquo.python.Python.getInstance().getModule("sync_checks").callAttr("ess_download_fixture",context.cacheDir.absolutePath).toString()
  assertTrue(JSONObject(result).getBoolean("missing_not_zero"));File(context.filesDir,"ESS_HISTORY_FIXTURE.json").writeText(result)
 }
 @Test fun resumeVerifyImportDeduplicateAndBalanceEss() {
  val context=InstrumentationRegistry.getInstrumentation().targetContext
  assertEquals(30,android.os.Build.VERSION.SDK_INT)
  Bridge.initialize(context);Bridge.start("127.0.0.1","SYNC-FIXTURE",true)
  try {
   val client=LanSupportClient(context,"http://127.0.0.1:18766")
   assertTrue(client.archiveSources().length()>0)
   val catalog=client.archiveCatalog("pc",0);assertEquals(2,catalog.getJSONArray("items").length())
   val rows=catalog.getJSONArray("items")
   val row=(0 until rows.length()).map { rows.getJSONObject(it) }.first { it.getLong("bytes")>256*1024 }.put("source_id","pc")
   val staging=File(context.filesDir,"DuckSolar/Data/ArchiveDownloads").apply { mkdirs() }
   val partial=File(staging,row.getString("sha256")+".part")
   // Seed a verified prefix, then exercise real HTTP range continuation.
   val full=client.archiveDownload(row,staging);val bytes=full.readBytes();partial.writeBytes(bytes.copyOf(256*1024))
   val resumed=client.archiveDownload(row,staging)
   assertEquals(row.getString("sha256"),LanSupportClient.sha256(resumed));resumed.delete()
   val first=ArchiveRestore.restore(context,"http://127.0.0.1:18766","pc") {}
   assertTrue(first.contains("Історія синхронізована"))
   val second=ArchiveRestore.restore(context,"http://127.0.0.1:18766","pc") {}
   assertTrue(second.contains("без змін 2"))
   val check=com.chaquo.python.Python.getInstance().getModule("sync_checks").callAttr("verify",File(context.filesDir,"DuckSolar").absolutePath).toString()
   File(context.filesDir,"ARCHIVE_SYNC_RESULT.json").writeText(check)
   assertTrue(JSONObject(check).getBoolean("dedup"))
   assertTrue(com.chaquo.python.Python.getInstance().getModule("sync_checks").callAttr("bridge_history_validation").toBoolean())
  } finally { Bridge.stop() }
 }
}
