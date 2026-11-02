package ua.ducksolar.b2.client

import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.*
import android.view.View
import android.view.ViewGroup
import android.view.Gravity
import android.widget.*

object AppStyle {
 val ink=Color.rgb(24,48,67);val accent=Color.rgb(0,126,125);val canvas=Color.rgb(238,245,247)
 val muted=Color.rgb(102,124,139);val border=Color.rgb(218,231,235)
 fun shape(context:Context,color:Int,radius:Int=18)=GradientDrawable().apply { setColor(color);cornerRadius=radius*context.resources.displayMetrics.density }
 fun backdrop()=GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM,intArrayOf(Color.rgb(233,245,245),Color.rgb(246,248,252)))
 private fun colors(on:Int,off:Int)=ColorStateList(arrayOf(intArrayOf(android.R.attr.state_checked),intArrayOf()),intArrayOf(on,off))
 private fun icon(context:Context,name:String,color:Int=accent)=AppIcon(name,color).apply { val n=(22*context.resources.displayMetrics.density).toInt();setBounds(0,0,n,n) }
 fun menu(button:Button,name:String) { button.setTag(R.id.style_kind,"menu");button.setTag(R.id.style_icon,name);apply(button) }
 fun navigation(button:Button,name:String,selected:Boolean) {
  button.setTag(R.id.style_icon,name);button.setTag(R.id.style_kind,"navigation");button.isSelected=selected
  if(button.getTag(R.id.style_ready)!=true) { apply(button);button.setTag(R.id.style_ready,true) }
 }
 fun watch(view:View) {
  apply(view)
  if(view is ViewGroup) {
   view.setOnHierarchyChangeListener(object:ViewGroup.OnHierarchyChangeListener {
    override fun onChildViewAdded(parent:View?,child:View?) { child?.post { watch(child) } }
    override fun onChildViewRemoved(parent:View?,child:View?) {}
   })
   for(i in 0 until view.childCount)watch(view.getChildAt(i))
  }
 }
 fun apply(view:View) {
  val d=view.resources.displayMetrics.density;val context=view.context
  if(view is TextView && view !is EditText) {
   if(!view.filters.contains(DisplayText.filter))view.filters=view.filters+DisplayText.filter
   val cleaned=DisplayText.clean(view.text);if(cleaned!=view.text.toString())view.text=cleaned
   view.contentDescription?.let { view.contentDescription=DisplayText.clean(it) }
  }
  fun dp(n:Int)=(n*d).toInt()
  when(view) {
   is Switch -> {
    view.splitTrack=false
    view.thumbTintList=null;view.trackTintList=null
    view.thumbDrawable=shape(context,Color.WHITE,20).apply { setSize(dp(23),dp(23));setStroke(dp(1),border) }
    view.trackDrawable=StateListDrawable().apply { addState(intArrayOf(android.R.attr.state_checked),shape(context,accent,20).apply { setSize(dp(44),dp(27)) });addState(intArrayOf(),shape(context,Color.rgb(196,213,221),20).apply { setSize(dp(44),dp(27)) }) }
    view.switchMinWidth=dp(48);view.switchPadding=dp(16);view.minHeight=dp(56);view.setPadding(dp(4),dp(8),dp(4),dp(8));view.setTextColor(ink);view.textSize=15f
   }
   is CheckBox -> { view.buttonTintList=colors(accent,muted);view.minHeight=dp(44);view.setPadding(dp(2),dp(4),dp(4),dp(4)) }
   is RadioButton -> { view.buttonTintList=colors(accent,muted) }
   is Button -> {
    val kind=view.getTag(R.id.style_kind)?.toString()
    val nav=kind=="navigation";val menu=kind=="menu"
    val primary=!nav && !menu && listOf("Зберегти","Підключитися","Побудувати","Отримати","Оновити","Продовжити").any { ua.ducksolar.shared.UiLanguage.sourceText(view).startsWith(it) }
    val fill=if(primary)accent else Color.WHITE
    val baseShape=shape(context,fill,if(menu)18 else 12).apply { if(!primary && !nav)setStroke(dp(1),border) }
    val background=if(nav)StateListDrawable().apply { addState(intArrayOf(android.R.attr.state_selected),shape(context,Color.rgb(215,239,237),14));addState(intArrayOf(),shape(context,Color.TRANSPARENT,14)) } else baseShape
    view.backgroundTintList=null;view.background=RippleDrawable(ColorStateList.valueOf(Color.rgb(192,225,224)),background,null)
    view.stateListAnimator=null;view.elevation=if(menu)1*d else 0f;view.isAllCaps=false
    view.typeface=Typeface.create("sans-serif-medium",Typeface.NORMAL)
    view.setTextColor(ColorStateList(arrayOf(intArrayOf(-android.R.attr.state_enabled),intArrayOf(android.R.attr.state_selected),intArrayOf()),intArrayOf(muted,accent,if(primary)Color.WHITE else if(nav)muted else ink)))
    view.textSize=if(nav)11f else if(menu)16f else 14f
    view.minHeight=dp(if(nav)60 else if(menu)60 else 44);view.minimumHeight=view.minHeight
    view.setPadding(dp(if(menu)16 else if(nav)2 else 12),dp(if(nav)6 else 8),dp(if(menu)12 else if(nav)2 else 12),dp(if(nav)6 else 8))
    if(menu) {
     view.gravity=Gravity.START or Gravity.CENTER_VERTICAL;view.maxLines=2
     view.setCompoundDrawables(icon(context,view.getTag(R.id.style_icon).toString()),null,icon(context,"arrow",muted),null);view.compoundDrawablePadding=dp(14)
    } else if(nav) {
     view.gravity=Gravity.CENTER;view.setSingleLine();view.minWidth=0;view.minimumWidth=0
     view.setCompoundDrawables(null,icon(context,view.getTag(R.id.style_icon).toString(),muted),null,null);view.compoundDrawablePadding=dp(3)
    } else {
     val parent=view.parent as? LinearLayout
     if(parent!=null && parent.orientation==LinearLayout.HORIZONTAL && parent.childCount>=3 && (view.layoutParams as? LinearLayout.LayoutParams)?.weight?.let { it>0 }==true) {
      view.textSize=12f;view.setPadding(dp(4),dp(8),dp(4),dp(8));view.minWidth=0;view.minimumWidth=0
     }
     if(view.text.toString()=="⚙") { view.text="";view.setCompoundDrawables(icon(context,"settings"),null,null,null);view.gravity=Gravity.CENTER }
    }
   }
   is EditText -> {
    view.textSize=16f;view.setTextColor(ink);view.setHintTextColor(muted)
    view.background=StateListDrawable().apply { addState(intArrayOf(android.R.attr.state_focused),shape(context,Color.WHITE,12).apply { setStroke(dp(2),accent) });addState(intArrayOf(),shape(context,Color.WHITE,12).apply { setStroke(dp(1),border) }) }
    view.setPadding(dp(12),dp(8),dp(12),dp(8));view.minHeight=dp(44)
   }
   is Spinner -> { view.backgroundTintList=ColorStateList.valueOf(accent) }
   is TextView -> { if(view.currentTextColor in listOf(Color.rgb(38,54,65),Color.rgb(29,48,61),Color.BLACK))view.setTextColor(ink);view.setLineSpacing(2*d,1f) }
  }
  if(view is ViewGroup)for(i in 0 until view.childCount)apply(view.getChildAt(i))
 }
 fun job(job:org.json.JSONObject):String=when(job.optString("phase")) {
  "discovery"->"Пошук історії"
  "projection"->"Підготовка даних для розрахунку"
  "integration"->"Обчислення балансу"
  "reconnecting"->"Зв’язок втрачено • очікуємо відновлення й результату"
  "queued"->"У черзі на сервері"
  else->if(job.optInt("total")>0)"Оброблено ${job.optInt("done")} із ${job.optInt("total")}" else "Виконується на сервері"
 }
}
