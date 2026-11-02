package ua.ducksolar.b2.client
import android.content.Intent
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.runner.RunWith

/** Keeps unrelated offline UI fixtures from starting a real connection service. */
@RunWith(AndroidJUnit4::class)
class PushFixtureSetupTest {
 @Test fun disableOnlyInEmulatorFixture() {
  check(android.os.Build.VERSION.SDK_INT==33)
  val context=InstrumentationRegistry.getInstrumentation().targetContext
  context.stopService(Intent(context,NotificationService::class.java))
  val edit=context.getSharedPreferences("alerts",0).edit()
  AlertMonitoring.kinds.forEach { edit.putBoolean(it,false) };edit.commit()
 }
}
