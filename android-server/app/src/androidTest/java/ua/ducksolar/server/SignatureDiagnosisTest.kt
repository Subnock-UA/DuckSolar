package ua.ducksolar.b2.server
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.runner.RunWith
import ua.ducksolar.shared.*
import android.content.pm.PackageManager
import android.os.Build
import java.io.File
import org.json.JSONObject

@RunWith(AndroidJUnit4::class)
class SignatureDiagnosisTest {
 @Suppress("DEPRECATION")
 @Test fun archiveAndInstalledSignerDetails() {
  val context=InstrumentationRegistry.getInstrumentation().targetContext
  val client=LanSupportClient(context,"http://127.0.0.1:28765")
  val update=client.manifest("server")!!
  val result=JSONObject().put("sdk",Build.VERSION.SDK_INT)
  try { client.download(update);result.put("download_verified",true) }
  catch(error:Exception) { result.put("download_error",error.message) }
  // Probe .apk and .part with the platform directly without bypassing verification.
  val sample=File(context.cacheDir,"signature-probe.apk")
  java.net.URL("http://127.0.0.1:28765/v1/apk/server").openStream().use { input -> sample.outputStream().use { input.copyTo(it) } }
  fun describe(file:File):JSONObject {
   val flags=if(Build.VERSION.SDK_INT>=28)PackageManager.GET_SIGNING_CERTIFICATES else PackageManager.GET_SIGNATURES
   val info=context.packageManager.getPackageArchiveInfo(file.absolutePath,flags)
   val legacy=context.packageManager.getPackageArchiveInfo(file.absolutePath,PackageManager.GET_SIGNATURES)
   return JSONObject().put("parsed",info!=null).put("modern_count",if(Build.VERSION.SDK_INT>=28)info?.signingInfo?.apkContentsSigners?.size ?: -1 else -2).put("legacy_count",legacy?.signatures?.size ?: -1)
  }
  result.put("apk",describe(sample))
  val partial=File(context.cacheDir,"signature-probe.part");sample.copyTo(partial,true)
  result.put("part",describe(partial))
  val flags=if(Build.VERSION.SDK_INT>=28)PackageManager.GET_SIGNING_CERTIFICATES else PackageManager.GET_SIGNATURES
  val installed=context.packageManager.getPackageInfo(context.packageName,flags)
  result.put("installed_modern",if(Build.VERSION.SDK_INT>=28)installed.signingInfo?.apkContentsSigners?.size ?: -1 else -2)
  File(context.filesDir,"SIGNATURE_DIAGNOSIS.json").writeText(result.toString())
  sample.delete();partial.delete()
 }
}
