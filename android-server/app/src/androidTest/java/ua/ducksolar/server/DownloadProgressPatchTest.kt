package ua.ducksolar.b2.server

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import ua.ducksolar.shared.*
import java.io.File

@RunWith(AndroidJUnit4::class)
class DownloadProgressPatchTest {
 @Test fun verifiedApkReportsActualTransferredBytesAndCachedCompletion() {
  val context=InstrumentationRegistry.getInstrumentation().targetContext
  val component=context.packageName.substringAfterLast('.')
  val client=LanSupportClient(context,"http://127.0.0.1:18766")
  val update=client.manifest(component)!!
  val folder=File(context.filesDir,"Updates")
  val ready=File(folder,"$component-${update.sha256}.apk");val partial=File(folder,"$component-${update.sha256}.part")
  // Only this isolated fixture's derived APK, never a user original.
  ready.delete();partial.delete()
  try {
   val received=mutableListOf<Long>()
   val file=client.download(update) { done,total ->assertEquals(update.bytes,total);received.add(done) }
   assertEquals(0L,received.first());assertEquals(update.bytes,received.last());assertTrue(received.size>2)
   assertTrue(received.zipWithNext().all { it.first<=it.second })
   assertEquals(update.bytes,file.length());assertEquals(update.sha256,LanSupportClient.sha256(file))
   val cached=mutableListOf<Long>();client.download(update) {done,_->cached.add(done)}
   assertEquals(listOf(update.bytes),cached)
  } finally { ready.delete();partial.delete() }
 }
}
