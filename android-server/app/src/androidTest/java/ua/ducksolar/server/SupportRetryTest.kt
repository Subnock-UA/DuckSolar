package ua.ducksolar.b2.server
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import ua.ducksolar.shared.LanSupportClient
@RunWith(AndroidJUnit4::class)
class SupportRetryTest {
 @Test fun retriesLostReplyAndResumesApk() {
  val context=InstrumentationRegistry.getInstrumentation().targetContext
  val client=LanSupportClient(context,"http://127.0.0.1:19008");assertTrue(client.identity().length==32)
  val file=java.io.File(context.cacheDir,"retry-fixture.log");file.writeBytes(ByteArray(700000) { (it%251).toByte() })
  try { assertTrue(client.upload(file,"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","diagnostic"));val update=client.manifest("server")!!;assertEquals(10434L,update.versionCode);val apk=client.download(update);assertEquals(update.sha256,LanSupportClient.sha256(apk)) } finally { file.delete() }
 }
}
