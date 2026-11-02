package ua.ducksolar.b2.server
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import android.content.Intent
import android.os.Build
import android.view.View
import android.view.ViewGroup
import android.widget.ScrollView
@RunWith(AndroidJUnit4::class)
class InsetsTest {
 @Test fun systemBarsLeaveServerControlsAccessible() {
  val inst=InstrumentationRegistry.getInstrumentation();val context=inst.targetContext
  val activity=inst.startActivitySync(Intent(context,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
  Thread.sleep(300)
  fun find(view:View):ScrollView? = if(view is ScrollView)view else if(view is ViewGroup)(0 until view.childCount).firstNotNullOfOrNull { find(view.getChildAt(it)) } else null
  inst.runOnMainSync {
   val scroll=find(activity.window.decorView)!!
   if(Build.VERSION.SDK_INT>=35) {
    val insets=activity.window.decorView.rootWindowInsets!!
    assertTrue(scroll.paddingTop>=insets.systemWindowInsetTop)
    assertTrue(scroll.paddingBottom>=insets.systemWindowInsetBottom)
   }
  }
 }
}
