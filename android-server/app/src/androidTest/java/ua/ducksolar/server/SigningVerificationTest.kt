package ua.ducksolar.b2.server
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import ua.ducksolar.shared.*
import java.io.File
import org.json.JSONObject
@RunWith(AndroidJUnit4::class)
class SigningVerificationTest {
 @Test fun validSignerAcceptedDifferentSignerAndBadApkRejected() {
  val context=InstrumentationRegistry.getInstrumentation().targetContext
  val client=LanSupportClient(context,"http://127.0.0.1:28765")
  val info=client.manifest("server")!!
  val good=client.download(info);client.verifyApk(good,info)
  val other=File("/data/local/tmp/ds-wrong-signer.apk")
  assertTrue(other.exists())
  @Suppress("DEPRECATION") val otherInfo=context.packageManager.getPackageArchiveInfo(other.absolutePath,0)!!
  val otherVersion=if(android.os.Build.VERSION.SDK_INT>=28)otherInfo.longVersionCode else otherInfo.versionCode.toLong()
  try { client.verifyApk(other,info.copy(versionCode=otherVersion));fail("Different signing key accepted") }
  catch(error:IllegalArgumentException) { assertTrue(error.message.orEmpty().contains("Ключ підпису")) }
  val bad=File(context.cacheDir,"bad-test.apk")
  try {
   bad.writeText("not an APK")
   try { client.verifyApk(bad,info);fail("Malformed APK accepted") } catch(_:IllegalArgumentException) { }
   try { client.verifyApk(good,info.copy(packageName="other.package"));fail("Wrong package accepted") } catch(_:IllegalArgumentException) { }
  } finally { bad.delete() }
  File(context.filesDir,"SIGNATURE_SECURITY_RESULT.json").writeText(JSONObject().put("correct_signer",true).put("different_signer_rejected",true).put("malformed_apk_rejected",true).put("wrong_package_rejected",true).toString())
 }
}
