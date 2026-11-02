package ua.ducksolar.b2.client
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import android.os.PowerManager
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
@RunWith(AndroidJUnit4::class)
class ReliableAlertsTest {
 @Test fun boundedLeaseAndUserControlsInDoze() {
  val ins=InstrumentationRegistry.getInstrumentation();val context=ins.targetContext
  for(mask in 0 until 64) {
   val enabled=mask and 1!=0;val permitted=mask and 2!=0;val channel=mask and 4!=0
   val reliable=mask and 8!=0;val screen=mask and 16!=0;val network=mask and 32!=0
   assertEquals(enabled && permitted && channel && reliable && !screen && network,AlertWakeLease.needed(enabled,permitted,channel,reliable,screen,network))
  }
  fun shell(cmd:String) { ins.uiAutomation.executeShellCommand(cmd).use { fd -> java.io.FileInputStream(fd.fileDescriptor).use { it.readBytes() } } }
  val prefs=context.getSharedPreferences("alerts",0);val lease=AlertWakeLease(context)
  try {
   prefs.edit().clear().putBoolean("grid_lost",true).putBoolean("reliable_background",true).commit()
   shell("dumpsys deviceidle whitelist +ua.ducksolar.b2.client")
   shell("input keyevent 223");Thread.sleep(350)
   assertFalse(context.getSystemService(PowerManager::class.java).isInteractive)
   lease.update();assertTrue("Screen-off lease was not acquired",lease.held())
   shell("dumpsys deviceidle force-idle");Thread.sleep(500)
   assertTrue("Lease lost in Doze",lease.held())
   prefs.edit().putBoolean("reliable_background",false).commit();lease.update();assertFalse(lease.held())
   prefs.edit().putBoolean("reliable_background",true).commit();lease.update();assertTrue(lease.held())
   prefs.edit().putBoolean("grid_lost",false).putBoolean("grid_restored",false).putBoolean("server_battery",false).putBoolean("inverter_battery",false).commit()
   lease.update();assertFalse("All alerts disabled must release lease",lease.held())
  } finally {
   lease.release();prefs.edit().clear().commit();shell("dumpsys deviceidle unforce");shell("input keyevent 224")
  }
 }
}
