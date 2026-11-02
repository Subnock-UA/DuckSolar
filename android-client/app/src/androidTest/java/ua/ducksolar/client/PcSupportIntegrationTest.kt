package ua.ducksolar.b2.client
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import java.io.File
import org.json.JSONObject
import ua.ducksolar.shared.*

@RunWith(AndroidJUnit4::class)
class PcSupportIntegrationTest {
 @Test fun signedApkAndLogCopyThroughExecutable() {
  val context=InstrumentationRegistry.getInstrumentation().targetContext
  val client=LanSupportClient(context,"http://127.0.0.1:28765")
  val update=client.manifest("client")!!
  assertEquals(context.packageName,update.packageName);assertTrue(update.versionCode>0)
  val apk=client.download(update);assertEquals(update.sha256,LanSupportClient.sha256(apk))
  try { UpdateInstaller.requireNewer(context,update);fail("Current version must not reinstall as newer") } catch(_:IllegalArgumentException) { }
  val fixture=File(context.cacheDir,"client-log-contract.jsonl")
  try {
   fixture.writeText("{\"test\":true,\"no_credentials\":true}\n")
   val sha=LanSupportClient.sha256(fixture)
   assertTrue(client.upload(fixture,"c".repeat(32),"diagnostic"))
   assertTrue(client.upload(fixture,"c".repeat(32),"diagnostic"))
   assertEquals(sha,LanSupportClient.sha256(fixture))
   File(context.filesDir,"PC_SUPPORT_RESULT.json").writeText(JSONObject().put("signed_apk",true).put("current_version_rejected",true).put("log_ack",true).put("repeat_ack",true).put("original_preserved",true).toString())
  } finally { fixture.delete() }
 }
}

