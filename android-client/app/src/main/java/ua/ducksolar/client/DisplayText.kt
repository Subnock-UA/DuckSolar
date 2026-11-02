package ua.ducksolar.b2.client
import android.text.InputFilter
import android.text.Spanned
object DisplayText {
 private val marker=Regex("""\s*\(\s*Н\s*/?\s*П\s*\)|(?<![\p{L}\p{N}])Н\s*/?\s*П(?![\p{L}\p{N}])""",RegexOption.IGNORE_CASE)
 fun clean(value:CharSequence?):String=marker.replace(value?.toString() ?: "","")
 val filter=InputFilter { source:CharSequence,start:Int,end:Int,_:Spanned,_:Int,_:Int ->
  val part=source.subSequence(start,end);val text=clean(part);if(text==part.toString())null else text
 }
}
