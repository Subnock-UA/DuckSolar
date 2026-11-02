package ua.ducksolar.b2.client
import android.content.Intent
import android.app.Activity
import android.view.View
import android.view.ViewGroup
import android.widget.*
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.json.JSONObject
import java.io.File
@RunWith(AndroidJUnit4::class)
class BetaReleaseUiTest {
 private fun buttons(v:View):List<Button> = if(v is Button)listOf(v) else if(v is ViewGroup)(0 until v.childCount).flatMap { buttons(v.getChildAt(it)) } else emptyList()
 @Test fun submenuNavigationHasNoObsoleteSiblingButtons() {
  val inst=InstrumentationRegistry.getInstrumentation();val context=inst.targetContext
  assertEquals("b1.0.0",context.packageManager.getPackageInfo(context.packageName,0).versionName)
  for(page in listOf("finance","events","history","tariff")) {
   val activity=inst.startActivitySync(Intent(context,RecordsActivity::class.java).putExtra("page",page).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
   try {
    inst.runOnMainSync {
     val titles=buttons(activity.window.decorView).map { it.text.toString() }
     assertEquals(1,titles.count { it=="‹ Додатково" })
     assertFalse(titles.any { it in setOf("Події","Фінанси","Історія") })
    }
    if(page=="finance")inst.runOnMainSync {
     val view=activity.window.decorView
     val image=android.graphics.Bitmap.createBitmap(view.width,view.height,android.graphics.Bitmap.Config.ARGB_8888)
     view.draw(android.graphics.Canvas(image))
     File(context.filesDir,"BETA_FINANCE.png").outputStream().use { image.compress(android.graphics.Bitmap.CompressFormat.PNG,100,it) };image.recycle()
    }
   } finally { inst.runOnMainSync { activity.finish() } }
  }
 }
 @Test fun namedSettingChoiceRequiresSeparateConfirmation() {
  val inst=InstrumentationRegistry.getInstrumentation();val context=inst.targetContext
  val activity=inst.startActivitySync(Intent(context,ParameterActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
  try {
   val row=JSONObject("""{"canonical_id":"grid.input_range","present":true,"raw_value":"1","display_value":"UPS","write_rule":{"enum":{"0":"Appliance","1":"UPS"}}}""")
   inst.runOnMainSync {
    val method=ParameterActivity::class.java.getDeclaredMethod("confirm",JSONObject::class.java,String::class.java,String::class.java,String::class.java)
    method.isAccessible=true
    val dialog=method.invoke(activity,row,"Діапазон мережі","fixture","fixture") as android.app.AlertDialog
    val adapter=dialog.listView.adapter
    assertEquals(listOf("Appliance","UPS"),(0 until adapter.count).map { adapter.getItem(it).toString() })
    assertFalse(dialog.getButton(android.app.AlertDialog.BUTTON_POSITIVE)?.isShown ?: false)
    dialog.dismiss()
   }
  } finally { inst.runOnMainSync { activity.finish() } }
 }
}
