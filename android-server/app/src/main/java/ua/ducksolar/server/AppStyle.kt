package ua.ducksolar.b2.server

import android.content.Context
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.view.View
import android.view.ViewGroup
import android.widget.*

object AppStyle {
 val ink=Color.rgb(29,48,61);val accent=Color.rgb(12,126,96);val canvas=Color.rgb(242,246,248)
 fun shape(context:Context,color:Int,radius:Int=14)=GradientDrawable().apply { setColor(color);cornerRadius=radius*context.resources.displayMetrics.density }
 fun apply(view:View) {
  val d=view.resources.displayMetrics.density
  if(view is Switch) {
   view.textSize=15f;view.minHeight=(52*d).toInt();view.setTextColor(ink)
   view.thumbTintList=android.content.res.ColorStateList(arrayOf(intArrayOf(android.R.attr.state_checked),intArrayOf()),intArrayOf(accent,Color.WHITE))
   view.trackTintList=android.content.res.ColorStateList(arrayOf(intArrayOf(android.R.attr.state_checked),intArrayOf()),intArrayOf(Color.rgb(165,215,203),Color.rgb(206,219,226)))
  } else if(view is Button) {
   val primary=ua.ducksolar.shared.UiLanguage.sourceText(view).startsWith("Запустити сервер") || ua.ducksolar.shared.UiLanguage.sourceText(view).startsWith("Встановити оновлення")
   val danger=ua.ducksolar.shared.UiLanguage.sourceText(view).startsWith("Зупинити")
   view.isAllCaps=false;view.textSize=14f;view.minHeight=(52*d).toInt();view.minimumWidth=0;view.minWidth=0
   view.setTextColor(if(primary)Color.WHITE else if(danger)Color.rgb(172,64,62) else accent)
   view.backgroundTintList=null
   val base=shape(view.context,if(primary)accent else Color.WHITE,14).apply { if(!primary)setStroke((d).toInt().coerceAtLeast(1),Color.rgb(217,231,233)) }
   view.background=android.graphics.drawable.RippleDrawable(android.content.res.ColorStateList.valueOf(Color.rgb(193,225,219)),base,null)
   view.elevation=0f;view.stateListAnimator=null;view.setPadding((12*d).toInt(),(8*d).toInt(),(12*d).toInt(),(8*d).toInt())
   (view.layoutParams as? android.view.ViewGroup.MarginLayoutParams)?.let { it.topMargin=(4*d).toInt();it.bottomMargin=(4*d).toInt() }
  } else if(view is EditText) {
   view.textSize=16f;view.setTextColor(ink);view.setHintTextColor(Color.rgb(105,126,139));view.setPadding((14*d).toInt(),(14*d).toInt(),(14*d).toInt(),(14*d).toInt());view.background=shape(view.context,Color.WHITE,12)
  } else if(view is TextView) { view.setTextColor(ink);view.setLineSpacing(4*d,1f) }
  if(view is ViewGroup)for(i in 0 until view.childCount)apply(view.getChildAt(i))
 }
 fun job(job:org.json.JSONObject):String=when(job.optString("phase")) {
  "reconnecting"->"Зв’язок втрачено • очікуємо відновлення й результату"
  "queued"->"У черзі на сервері"
  else->if(job.optInt("total")>0)"Оброблено ${job.optInt("done")} із ${job.optInt("total")}" else "Виконується на сервері"
 }
}
