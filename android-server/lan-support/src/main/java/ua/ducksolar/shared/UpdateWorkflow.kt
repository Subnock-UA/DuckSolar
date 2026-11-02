package ua.ducksolar.shared

import android.content.Context
import android.os.Build
import java.io.File
import java.util.Locale

/** Checking never transfers a payload. Installing fetches fresh metadata and verifies the download first. */
class UpdateWorkflow(private val packageName:String,private val currentVersion:String,private val currentCode:Long,
 private val manifest:()->UpdateInfo?,private val download:(UpdateInfo,(Long,Long)->Unit)->File) {
 private fun offered():UpdateInfo?=manifest()?.also { require(it.packageName==packageName) { "Оновлення для іншого застосунку" } }
 private fun absent(update:UpdateInfo?)=if(update==null)"ПК не має пакета оновлення" else "Оновлень немає. Встановлено $currentVersion; на ПК ${update.version}."
 fun check():String {
  val update=offered()
  return if(update==null || update.versionCode<=currentCode)absent(update)
   else "Доступне оновлення ${update.version} (${DownloadProgress.bytes(update.bytes)}). Натисніть «Встановити оновлення»."
 }
 fun install(progress:(Long,Long)->Unit,apply:(File,UpdateInfo)->String):String {
  val update=offered()
  if(update==null || update.versionCode<=currentCode)return absent(update)
  val file=download(update,progress)
  return apply(file,update)
 }
 companion object {
  @Suppress("DEPRECATION") fun from(context:Context,component:String,client:LanSupportClient):UpdateWorkflow {
   val current=context.packageManager.getPackageInfo(context.packageName,0)
   val code=if(Build.VERSION.SDK_INT>=28)current.longVersionCode else current.versionCode.toLong()
   return UpdateWorkflow(context.packageName,current.versionName ?: code.toString(),code,{client.manifest(component)},{update,progress->client.download(update,progress)})
  }
 }
}

object DownloadProgress {
 fun bytes(value:Long):String=if(value<1024L*1024)"${(value.coerceAtLeast(0)+1023)/1024} КБ" else String.format(Locale.getDefault(),"%.1f МБ",value/1048576.0)
 fun text(done:Long,total:Long):String=(if(done>=total)"Завантажено: " else "Завантаження: ")+bytes(done)+" / "+bytes(total)+(if(done>=total)" • перевірка пакета…" else "")
}
