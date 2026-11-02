package ua.ducksolar.b2.client

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import android.content.Intent
import android.app.Activity
import android.view.View
import android.view.ViewGroup
import android.widget.*
import android.graphics.Bitmap
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class FeatureUiReviewTest {
 @Test fun eventsHistoryFinanceParametersAndBlankMeterEntry() {
  val inst=InstrumentationRegistry.getInstrumentation();val context=inst.targetContext;val args=InstrumentationRegistry.getArguments()
  ClientBridge.initialize(context)
  ClientBridge.connect("https://127.0.0.1:28766","","review_"+UUID.randomUUID().toString().replace("-","").take(12),"fixture-pass-"+UUID.randomUUID(),args.getString("serial")!!,args.getString("pair_code")!!,true)
  fun views(v:View):List<View> = listOf(v)+(if(v is ViewGroup)(0 until v.childCount).flatMap { views(v.getChildAt(it)) } else emptyList())
  fun button(a:Activity,title:String) { inst.runOnMainSync { views(a.window.decorView).filterIsInstance<Button>().first { it.text.toString()==title }.performClick() } }
  fun shot(name:String) { val image=inst.uiAutomation.takeScreenshot();File(context.filesDir,name).outputStream().use { image.compress(Bitmap.CompressFormat.PNG,100,it) };image.recycle() }
  val records=inst.startActivitySync(Intent(context,RecordsActivity::class.java).putExtra("page","finance").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
  try {
   inst.runOnMainSync { views(records.window.decorView).filterIsInstance<EditText>().first().setText("2026-09") }
   button(records,"Отримати фінанси");Thread.sleep(1000)
   inst.runOnMainSync { assertTrue(views(records.window.decorView).filterIsInstance<TextView>().any { it.text.toString().contains("Нарахування після податків: —") }) }
   shot("FINANCE_REVIEW.png")
   button(records,"Події");button(records,"Оновити події");Thread.sleep(700)
   inst.runOnMainSync { assertTrue(views(records.window.decorView).filterIsInstance<TextView>().any { it.text.toString().contains("НП") && it.text.toString().contains("warnings.fixture") }) };shot("EVENTS_REVIEW.png")
   button(records,"Історія");button(records,"Перевірити історію");Thread.sleep(700)
   assertEquals(0,ClientBridge.historyDates().optInt("count"));shot("HISTORY_REVIEW.png")
  } finally { inst.runOnMainSync { records.finish() } }
  val params=inst.startActivitySync(Intent(context,ParameterActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
  try { Thread.sleep(1000);shot("PARAMETERS_REVIEW.png") } finally { inst.runOnMainSync { params.finish() } }
  val main=inst.startActivitySync(Intent(context,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
  try { Thread.sleep(1000);inst.runOnMainSync { MeterEntry.show(main) };Thread.sleep(300);shot("METER_ENTRY_REVIEW.png") } finally { inst.runOnMainSync { main.finish() } }
 }
}
