package ua.ducksolar.b2.client
import android.app.AlertDialog
import android.content.Context
import android.widget.*
import org.json.JSONObject
object SnapshotView {
 fun show(context:Context,saved:JSONObject) {
  val state=saved.optJSONObject("state") ?: JSONObject()
  val body=LinearLayout(context).apply { orientation=LinearLayout.VERTICAL;setPadding(24,16,24,16) }
  body.addView(TextView(context).apply { text="Збережений стан, а не поточні дані.\nЧас вимірювання: "+state.optString("updated","—");textSize=16f })
  val metrics=state.optJSONObject("normalized")?.optJSONObject("metrics") ?: JSONObject()
  val definitions=state.optJSONObject("descriptor")?.optJSONArray("metric_definitions")
  for(i in 0 until (definitions?.length() ?: 0)) {
   val d=definitions!!.getJSONObject(i);val item=metrics.optJSONObject(d.optString("canonical_id")) ?: continue
   body.addView(TextView(context).apply { text=d.optString("ui_name")+": "+MetricText.value(item,false);setPadding(0,8,0,8) })
  }
  ua.ducksolar.shared.LocalizedDialog.Builder(context).setTitle("Останній знімок інвертора").setView(ScrollView(context).apply { addView(body) }).setPositiveButton("Закрити",null).show()
 }
}
