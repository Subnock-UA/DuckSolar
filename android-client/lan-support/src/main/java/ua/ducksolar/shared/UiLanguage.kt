package ua.ducksolar.shared

import android.app.Activity
import android.app.AlertDialog
import android.app.Application
import android.content.Context
import android.content.DialogInterface
import android.content.res.Configuration
import android.os.Bundle
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.TextView
import org.json.JSONObject
import java.util.Locale
import java.util.WeakHashMap

/** Presentation only: canonical API values, editable data and business state stay untouched. */
object UiLanguage {
    @Volatile var language="en"; private set
    private var catalog=mapOf<String,String>()
    private data class Template(val fixed:Int,val regex:Regex,val target:String,val names:List<String>)
    private var templates=listOf<Template>()
    private var phrases:Regex?=null
    private data class Source(var raw:String,var rendered:String="",var language:String="")
    private val texts=WeakHashMap<TextView,Source>()
    private val hints=WeakHashMap<TextView,Source>()
    private val errors=WeakHashMap<TextView,Source>()
    private val descriptions=WeakHashMap<View,Source>()
    private val watched=WeakHashMap<View,Boolean>()
    private val cache=object:LinkedHashMap<String,String>(256,.75f,true) {
        override fun removeEldestEntry(eldest:MutableMap.MutableEntry<String,String>?)=size>1024
    }
    @Synchronized fun load(context:Context) {
        language=context.getSharedPreferences("DuckSolarLanguage",Context.MODE_PRIVATE).getString("language","en").let { if(it=="uk")"uk" else "en" }
        if(catalog.isNotEmpty())return
        val json=JSONObject(context.assets.open("ducksolar_en.json").bufferedReader().use { it.readText() })
        catalog=json.keys().asSequence().associateWith { json.getString(it) }
        val placeholder=Regex("\\{#\\d+#\\}")
        templates=catalog.filterKeys { "{#" in it }.map { (key,value)->
            val names=placeholder.findAll(key).map { it.value }.toList()
            var start=0;val pattern=StringBuilder("^")
            for(match in placeholder.findAll(key)) {
                pattern.append(Regex.escape(key.substring(start,match.range.first))).append("(.*?)")
                start=match.range.last+1
            }
            pattern.append(Regex.escape(key.substring(start))).append("$")
            Template(placeholder.replace(key,"").length,Regex(pattern.toString(),RegexOption.DOT_MATCHES_ALL),value,names)
        }.sortedByDescending { it.fixed }
        val plain=catalog.keys.filter { "{#" !in it && it.length>1 }.sortedByDescending { it.length }
        phrases=Regex("(?<![\\p{L}\\p{N}_])(?:"+plain.joinToString("|") { Regex.escape(it) }+")(?![\\p{L}\\p{N}_])")
    }
    fun localizedContext(context:Context):Context {
        load(context)
        val configuration=Configuration(context.resources.configuration)
        configuration.setLocale(Locale(language))
        return context.createConfigurationContext(configuration)
    }
    @Synchronized fun text(value:CharSequence?):String {
        val source=value?.toString().orEmpty()
        if(language=="uk" || source.none { it in '\u0400'..'\u04ff' })return source
        return cache[source] ?: english(source,0).also { cache[source]=it }
    }
    private fun english(value:String,depth:Int):String {
        val raw=value.trim();if(raw.isEmpty())return value
        val prefix=value.takeWhile { it.isWhitespace() };val suffix=value.takeLastWhile { it.isWhitespace() }
        catalog[raw]?.let { if("{#" !in raw)return prefix+it+suffix }
        if(depth<3)for(template in templates) {
            val match=template.regex.matchEntire(raw) ?: continue
            var result=template.target
            for((i,name) in template.names.withIndex())result=result.replace(name,english(match.groupValues[i+1],depth+1))
            return prefix+result+suffix
        }
        val result=phrases?.replace(value) { catalog[it.value] ?: it.value } ?: value
        return Regex("(?<=\\d)\\s+(В|А|с)(?=$|[\\s,;·/])").replace(result) { " "+mapOf("В" to "V","А" to "A","с" to "s").getValue(it.groupValues[1]) }
    }
    fun sourceText(view:TextView):String=texts[view]?.raw ?: view.text.toString()
    private fun render(value:String,source:Source):String {
        if(value!=source.rendered && value!=source.raw)source.raw=value
        if(source.language==language && value==source.rendered)return value
        source.language=language;source.rendered=text(source.raw);return source.rendered
    }
    fun apply(view:View) {
        if(view is TextView) {
            if(view !is EditText) {
                val value=view.text.toString();val source=texts.getOrPut(view) { Source(value) }
                val target=render(value,source);if(value!=target)view.text=target
            }
            view.error?.toString()?.let { value->
                val target=render(value,errors.getOrPut(view) { Source(value) });if(value!=target)view.error=target
            }
            view.hint?.toString()?.let { value->
                val target=render(value,hints.getOrPut(view) { Source(value) });if(value!=target)view.hint=target
            }
        }
        view.contentDescription?.toString()?.let { value->
            val target=render(value,descriptions.getOrPut(view) { Source(value) });if(value!=target)view.contentDescription=target
        }
        if(view is ViewGroup)for(i in 0 until view.childCount)apply(view.getChildAt(i))
    }
    fun watch(root:View) {
        if(watched.put(root,true)!=null)return
        root.viewTreeObserver.addOnPreDrawListener { apply(root);true }
        root.post { apply(root) }
    }
    fun set(context:Context,value:String) {
        require(value=="en" || value=="uk") { "Unsupported interface language" }
        context.getSharedPreferences("DuckSolarLanguage",Context.MODE_PRIVATE).edit().putString("language",value).commit()
        language=value
        // Refresh app-owned notification presentation without restarting services.
        val manager=context.getSystemService(android.app.NotificationManager::class.java)
        fun localized(raw:CharSequence?):String {
            val source=raw?.toString().orEmpty()
            val canonical=if(value=="uk")catalog.entries.firstOrNull { it.value==source && "{#" !in it.key }?.key ?: source else source
            return text(canonical)
        }
        for(channel in manager.notificationChannels) {
            channel.name=localized(channel.name);manager.createNotificationChannel(channel)
        }
        for(active in manager.activeNotifications) {
            val notification=active.notification
            val builder=android.app.Notification.Builder.recoverBuilder(context,notification)
                .setContentTitle(localized(notification.extras.getCharSequence(android.app.Notification.EXTRA_TITLE)))
                .setContentText(localized(notification.extras.getCharSequence(android.app.Notification.EXTRA_TEXT)))
                .setOnlyAlertOnce(true)
            manager.notify(active.tag,active.id,builder.build())
        }
        val widgets=android.appwidget.AppWidgetManager.getInstance(context)
        for(info in widgets.installedProviders.filter { it.provider.packageName==context.packageName })
            context.sendBroadcast(android.content.Intent(context.packageName+".LANGUAGE_CHANGED").setComponent(info.provider))
    }
    fun select(activity:Activity) {
        AlertDialog.Builder(activity).setTitle("Language / Мова")
            .setSingleChoiceItems(arrayOf("English","Українська"),if(language=="uk")1 else 0) { dialog,index->
                val selected=if(index==1)"uk" else "en"
                set(activity,selected);dialog.dismiss();activity.recreate()
            }.setNegativeButton(if(language=="uk")"Скасувати" else "Cancel",null).show()
    }
}

open class LocalizedActivity:Activity() {
    override fun attachBaseContext(newBase:Context) { super.attachBaseContext(UiLanguage.localizedContext(newBase)) }
    override fun onCreate(state:Bundle?) { super.onCreate(state);UiLanguage.watch(window.decorView) }
}

open class BilingualApplication:Application() {
    override fun onCreate() { super.onCreate();UiLanguage.load(this) }
}

object LocalizedDialog {
    class Builder(context:Context):AlertDialog.Builder(context) {
        override fun setTitle(title:CharSequence?):AlertDialog.Builder=super.setTitle(UiLanguage.text(title))
        override fun setMessage(message:CharSequence?):AlertDialog.Builder=super.setMessage(UiLanguage.text(message))
        override fun setPositiveButton(text:CharSequence?,listener:DialogInterface.OnClickListener?):AlertDialog.Builder=super.setPositiveButton(UiLanguage.text(text),listener)
        override fun setNegativeButton(text:CharSequence?,listener:DialogInterface.OnClickListener?):AlertDialog.Builder=super.setNegativeButton(UiLanguage.text(text),listener)
        override fun setNeutralButton(text:CharSequence?,listener:DialogInterface.OnClickListener?):AlertDialog.Builder=super.setNeutralButton(UiLanguage.text(text),listener)
        override fun setItems(items:Array<out CharSequence>?,listener:DialogInterface.OnClickListener?):AlertDialog.Builder=super.setItems(items?.map { UiLanguage.text(it) }?.toTypedArray(),listener)
        override fun setSingleChoiceItems(items:Array<out CharSequence>?,checkedItem:Int,listener:DialogInterface.OnClickListener?):AlertDialog.Builder=super.setSingleChoiceItems(items?.map { UiLanguage.text(it) }?.toTypedArray(),checkedItem,listener)
        override fun setMultiChoiceItems(items:Array<out CharSequence>?,checkedItems:BooleanArray?,listener:DialogInterface.OnMultiChoiceClickListener?):AlertDialog.Builder=super.setMultiChoiceItems(items?.map { UiLanguage.text(it) }?.toTypedArray(),checkedItems,listener)
        override fun create():AlertDialog=super.create().also { dialog->dialog.window?.decorView?.let { root->UiLanguage.watch(root) } }
        override fun show():AlertDialog=super.show().also { dialog->dialog.window?.decorView?.let { root->UiLanguage.watch(root) } }
    }
}

object LocalizedToast {
    fun makeText(context:Context,text:CharSequence?,duration:Int):android.widget.Toast=android.widget.Toast.makeText(context,UiLanguage.text(text),duration)
    fun makeText(context:Context,text:Int,duration:Int):android.widget.Toast=android.widget.Toast.makeText(context,text,duration)
}
