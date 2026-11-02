package ua.ducksolar.b2.client
import android.app.Activity
import android.content.Intent
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import android.widget.Button
import android.widget.Switch
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.chaquo.python.Python
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class PlanningPatchTest {
 private fun views(view:View):List<View> = listOf(view)+(if(view is ViewGroup)(0 until view.childCount).flatMap { views(view.getChildAt(it)) } else emptyList())
 @Test fun newScreensAndAdaptiveDefaults() {
  val inst=InstrumentationRegistry.getInstrumentation();val context=inst.targetContext
  ClientBridge.initialize(context)
  val fixture=inst.context.assets.open("analytics_fixtures.json").bufferedReader().use { it.readText() }
  val module=Python.getInstance().getModule("android_client")
  val script="""
import json
_ui_fixtures=json.loads(${JSONObject.quote(fixture)})
_ui_current={}
def _ui_start(kind,*args):
 global _ui_current
 _ui_current=_ui_fixtures[kind]
 return json.dumps({'state':'running'})
def _ui_status():return json.dumps({'state':'complete','result':_ui_current})
def _ui_call(method,args='[]'):
 if method=='night_charge':return json.dumps({'enabled':False,'adaptive_enabled':False,'night_battery_share_pct':100,'day_a':10,'night_a':60,'status':'disabled','error':''})
 if method=='battery_config':return json.dumps({'usable_kwh':10.0,'reserve_pct':20,'charge_efficiency':.95})
 if method=='battery':return json.dumps({'values':{'soc':60},'estimate':{'remaining_kwh':8.6,'available_kwh':5.7,'current_hours':5,'average_hours':6,'curve_hours':7,'gap_s':0,'anchor_at':1792932000,'anchor_source':'automatic_full_charge','charged_kwh':3,'discharged_kwh':2,'confidence':'estimated','note':'Оцінка'}})
 return '{}'
feature_start=_ui_start
feature_status=_ui_status
feature_call=_ui_call
resume=lambda *args: '{}'
""".trimIndent()
  Python.getInstance().getModule("builtins").callAttr("exec",script,module.callAttr("__getattribute__","__dict__"))
  for((page,button,expected) in listOf(Triple("forecast_live","Оновити дані","Оперативний підсумок"),Triple("forecast_stats","Оновити дані","Систематичне відхилення"),Triple("charge_plan","Оновити дані","Рекомендований ліміт"),Triple("battery_history","Отримати дані","Між наявними точками"))) {
   val activity=inst.startActivitySync(Intent(context,InsightsActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK).putExtra("page",page))
   try {
    inst.runOnMainSync { (views(activity.window.decorView).filterIsInstance<Button>().first { it.text.toString()==button }).performClick() }
    val deadline=System.currentTimeMillis()+6000;var found=false
    while(!found && System.currentTimeMillis()<deadline) { Thread.sleep(100);inst.runOnMainSync { found=views(activity.window.decorView).filterIsInstance<TextView>().any { it.text.toString().contains(expected) } } }
    assertTrue("Page $page did not render $expected",found)
   } finally { inst.runOnMainSync { activity.finish() } }
  }
  val night=inst.startActivitySync(Intent(context,InsightsActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK).putExtra("page","night"))
  try { inst.runOnMainSync { val adaptive=views(night.window.decorView).filterIsInstance<Switch>().first { it.text.toString().contains("Адаптивний") };assertFalse(adaptive.isChecked) } }
  finally { inst.runOnMainSync { night.finish() } }
 }
}
