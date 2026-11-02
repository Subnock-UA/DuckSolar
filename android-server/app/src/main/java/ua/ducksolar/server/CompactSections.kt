package ua.ducksolar.b2.server

import android.view.View
import android.widget.*

/** Controls first, readable information next, editable settings last.
 * Long labels and large accessibility fonts retain full-width touch targets. */
object CompactSections {
 fun apply(parent:LinearLayout,reorder:Boolean=true) {
  if(parent.orientation!=LinearLayout.VERTICAL)return
  val children=(0 until parent.childCount).map { parent.getChildAt(it) }
  fun setting(v:View):Boolean = v is EditText || v is Spinner || v is Switch || v is CheckBox ||
   v is LinearLayout && (0 until v.childCount).any { setting(v.getChildAt(it)) }
  val title=children.firstOrNull()?.takeIf { it is TextView && it !is Button }
  fun action(v:View):Boolean = v is Button && v !is CompoundButton || v is LinearLayout && v.childCount>0 && (0 until v.childCount).all { v.getChildAt(it) is Button && v.getChildAt(it) !is CompoundButton }
  val controls=children.filter { action(it) }
  val labelled=children.filterIndexed { i,v->v is TextView && v !is Button && v!==title && v.text.length<=90 && i+1<children.size && setting(children[i+1]) }

  val info=children.filter { it!==title && it !in controls && it !in labelled && !setting(it) }
  val settings=children.filter { setting(it) || it in labelled }
  val ordered=if(reorder) listOfNotNull(title)+controls+info+settings else children
  parent.removeAllViews()
  var row:LinearLayout?=null;var previous:Button?=null
  val compact=parent.resources.configuration.screenWidthDp>=340 && parent.resources.configuration.fontScale<=1.2f
  for(v in ordered) {
   val b=(v as? Button)?.takeUnless { it is CompoundButton }
   val pair=compact && b!=null && previous!=null && previous!!.text.length+b.text.length<=38 &&
    !previous!!.text.startsWith("‹") && !b.text.startsWith("‹")
   if(pair) {
    val first=previous!!;parent.removeView(first)
    row=LinearLayout(parent.context).apply { orientation=LinearLayout.HORIZONTAL }
    parent.addView(row,LinearLayout.LayoutParams(-1,-2))
    for(button in listOf(first,b!!)) {
     button.minWidth=0;button.minimumWidth=0;button.minHeight=(48*parent.resources.displayMetrics.density).toInt();button.isSingleLine=false
     row.addView(button,LinearLayout.LayoutParams(0,-2,1f).apply { setMargins(2,3,2,3) })
    }
    previous=null
   } else {
    parent.addView(v,LinearLayout.LayoutParams(-1,-2))
    previous=b
   }
  }
 }
}
