package ua.ducksolar.b2.server

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import ua.ducksolar.shared.*
import java.io.File

@RunWith(AndroidJUnit4::class)
class UpdateWorkflowPatchTest {
 private val update=UpdateInfo("client","b1.0.18",10645,"ua.ducksolar.b2.client","a".repeat(64),3*1024L*1024,listOf("x86_64"),"/v1/apk/client")
 @Test fun checkOnlyReadsMetadataWhileInstallDownloadsReportsBytesThenInstalls() {
  val events=mutableListOf<String>();val totals=mutableListOf<String>()
  val file=File(InstrumentationRegistry.getInstrumentation().targetContext.cacheDir,"verified-fixture.apk")
  val flow=UpdateWorkflow("ua.ducksolar.b2.client","b2.0.0",10644,{events.add("manifest");update},{_,progress->events.add("download");progress(1024,update.bytes);progress(update.bytes,update.bytes);file})
  assertTrue(flow.check().contains("Доступне"));assertEquals(listOf("manifest"),events)
  events.clear()
  assertEquals("installer started",flow.install({done,total->totals.add(DownloadProgress.text(done,total))}) { received,info ->assertEquals(file,received);assertEquals(update,info);events.add("install");"installer started" })
  assertEquals(listOf("manifest","download","install"),events)
  assertTrue(totals.first().contains("1 КБ"));assertTrue(totals.last().contains("МБ"));assertFalse(totals.any { it.contains('%') })
 }
 @Test fun failedDownloadDoesNotStopCollectionOrInvokeInstaller() {
  var installs=0
  val flow=UpdateWorkflow("ua.ducksolar.b2.client","b2.0.0",10644,{update},{_,_->throw java.io.IOException("fixture transfer interrupted")})
  try { flow.install({_,_->}) {_,_->installs++;"must not run" };fail("Failure hidden") } catch(_:java.io.IOException) {}
  assertEquals(0,installs)
 }
 @Test fun noUpdateAndWrongPackageNeverDownloadOrInstall() {
  var downloads=0;var installs=0
  for(offered in listOf<UpdateInfo?>(null,update.copy(versionCode=10644),update.copy(versionCode=1))) {
   val flow=UpdateWorkflow("ua.ducksolar.b2.client","b2.0.0",10644,{offered},{_,_->downloads++;File("unused")})
   assertTrue(flow.check().isNotBlank());flow.install({_,_->}) {_,_->installs++;"must not run"}
  }
  val wrong=UpdateWorkflow("ua.ducksolar.b2.client","b2.0.0",10644,{update.copy(packageName="other")},{_,_->downloads++;File("unused")})
  try { wrong.check();fail("Wrong package accepted") } catch(_:IllegalArgumentException) {}
  assertEquals(0,downloads);assertEquals(0,installs)
 }
}
