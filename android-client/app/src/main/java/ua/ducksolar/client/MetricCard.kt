package ua.ducksolar.b2.client
import android.content.Context
import android.graphics.Typeface
import android.view.Gravity
import android.widget.*
import org.json.JSONObject

class MetricCard(context:Context,title:String,icon:String,private val showProvenance:Boolean=false):LinearLayout(context) {
 private val values=mutableMapOf<String,TextView>()
 private fun dp(n:Int)=(n*resources.displayMetrics.density).toInt()
 init {
  orientation=VERTICAL;setPadding(dp(16),dp(12),dp(16),dp(12));background=AppStyle.shape(context,android.graphics.Color.WHITE,20)
  addView(TextView(context).apply {
   text=title;textSize=18f;setTextColor(AppStyle.ink);typeface=Typeface.create("sans-serif-medium",Typeface.NORMAL);setPadding(0,dp(4),0,dp(12))
   val image=AppIcon(icon).apply { setBounds(0,0,dp(22),dp(22)) };setCompoundDrawables(image,null,null,null);compoundDrawablePadding=dp(10)
  })
 }
 fun update(rows:List<Pair<String,JSONObject?>>,stale:Boolean) {
  for((title,metric) in rows) {
   val value=values.getOrPut(title) {
    val row=LinearLayout(context).apply { gravity=Gravity.CENTER_VERTICAL;setPadding(0,dp(7),0,dp(7));minimumHeight=dp(40);this@MetricCard.addView(this) }
    row.addView(TextView(context).apply { text=title;textSize=13f;setTextColor(AppStyle.muted) },LayoutParams(0,-2,1.2f))
    TextView(context).apply { textSize=16f;gravity=Gravity.END;setTextColor(AppStyle.ink);typeface=Typeface.create("sans-serif-medium",Typeface.NORMAL);setTextIsSelectable(true);row.addView(this,LayoutParams(0,-2,1f)) }
   }
   value.text=(if(showProvenance)MetricText.value(metric,stale) else HomeMetrics.text(metric,stale)).removeSuffix(" • застаріле").let { if(it.startsWith("—"))"—" else it }
   value.alpha=if(stale || metric?.optBoolean("stale")==true).55f else 1f
   if(showProvenance)value.setOnClickListener {
    val stamp=metric?.optString("timestamp")?.takeIf { it.isNotBlank() } ?: "—"
    val age=metric?.optDouble("age_s",Double.NaN)?.takeIf { it.isFinite() }?.let { DurationText.seconds(it) } ?: "—"
    val reason=metric?.optString("unavailable_reason")?.takeIf { it.isNotBlank() } ?: if(stale)"Немає актуального зв’язку" else if(metric==null || metric.isNull("value"))"Значення не отримане" else "Дані доступні"
    val kind=if(metric?.optString("measurement_kind")=="estimated" || metric?.optString("confidence")=="estimated")"Розрахунок" else "Показник інвертора"
    ua.ducksolar.shared.LocalizedDialog.Builder(context).setTitle(title).setMessage("${MetricText.value(metric,stale)}\n$kind\nДжерело: ${metric?.optString("source") ?: "—"}\nЧас виміру: $stamp\nВік: $age\n$reason").setPositiveButton("Закрити",null).show()
   }
   value.contentDescription=title+": "+MetricText.value(metric,stale)+(metric?.optString("calculation")?.takeIf { it.isNotBlank() }?.let { "; $it" } ?: "")
  }
 }
}
