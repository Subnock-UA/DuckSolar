package ua.ducksolar.b2.server

import android.content.Context
import org.json.JSONObject
import ua.ducksolar.shared.LanSupportClient
import java.io.File
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

object ServerMaintenance {
    @Volatile var status="ПК-служба не налаштована"
    private val diagnosticBusy=java.util.concurrent.atomic.AtomicBoolean(false)
    private val inverterBusy=java.util.concurrent.atomic.AtomicBoolean(false)
    fun redact(line:String):String {
        val safe=line.replace(Regex("(?i)Bearer\\s+[A-Za-z0-9._~+/-]+"),"Bearer [REDACTED]")
        return safe.replace(Regex("(?i)(\"?(?:password|passwd|auth_token|access_token|refresh_token|api_access_key|token|authorization|secret|trust_ticket|pairing_code)\"?\\s*[:=]\\s*)(\"[^\"]*\"|[^,\\s}]+)")) { match ->
            match.groupValues[1]+JSONObject.quote("[REDACTED]")
        }
    }
    fun sync(context:Context,url:String,includeInverter:Boolean=false,fullArchive:Boolean=false,progress:((String)->Unit)?=null):String {
        val busy=if(includeInverter)inverterBusy else diagnosticBusy
        if(!busy.compareAndSet(false,true))return "Копіювання вже виконується"
        try {
            val client=LanSupportClient(context,url)
            val root=File(context.filesDir,"DuckSolar")
            val migration=File(root,"Data/HistoryMigration/state.json")
            if(includeInverter && migration.exists() && JSONObject(migration.readText()).optBoolean("active"))return "Резервування призупинено на час міграції"
            val config=File(root,"Server/DS_Server_Beta_2/config.json")
            require(config.exists()) { "Спочатку запустіть сервер для створення його конфігурації" }
            val installation=JSONObject(config.readText()).getString("installation_id")
            val diagnostics=File(root,"Logs/DS_Server_Beta_2")
            val inverter=File(root,"Logs/Inverter")
            var sent=0;var skipped=0
            val stateFile=File(context.filesDir,if(includeInverter)"InverterBackupState.json" else "BackupState.json")
            var acknowledged=try { JSONObject(stateFile.readText()) } catch(_:Exception) { JSONObject() }
            val cursors=context.getSharedPreferences(if(includeInverter)"InverterBackupCursor" else "BackupCursor",Context.MODE_PRIVATE)
            val pcIdentity=client.identity()
            if(cursors.getString("pc_id","")!=pcIdentity) {
                acknowledged=JSONObject();cursors.edit().clear().putString("pc_id",pcIdentity).apply()
            }
            if(fullArchive) {
                require(includeInverter)
                cursors.edit().putInt("inverter",0).putInt("smartess-history",0).commit()
            }
            fun transfer(folder:File,kind:String,cursorKey:String=kind,onlyFile:File?=null) {
                fun files()=folder.walkTopDown().filter { it.isFile && !it.isHidden &&
                    (it.extension in listOf("log","jsonl","csv","1","2","3") || it.name.endsWith(".csv.schema.json")) && (onlyFile==null || it==onlyFile) }
                // Bound each pass; repeating sync will resume from persisted file revisions.
                for(file in files().drop(cursors.getInt(cursorKey,0)).take(if(fullArchive)10000 else if(includeInverter)2 else 50)) {
                    val seen=cursors.getInt(cursorKey,0)+1
                    fun advance() { cursors.edit().putInt(cursorKey,seen).apply() }
                    if(file.length()==0L) { advance();continue }
                    if(file.length()>128L*1024*1024 && !(includeInverter && client.supportsInverterAppend)) { skipped++;advance();continue }
                    val flat=file.relativeTo(folder).path.replace(File.separatorChar,'_')
                    val name=if(folder.path.contains("CompactHistory") && flat.startsWith("SmartESS_"))"History_"+flat.removePrefix("SmartESS_") else if(kind=="diagnostic" || folder.name=="History")folder.name+"_"+flat else flat
                    if(!name.matches(Regex("[A-Za-z0-9_.-]{1,160}"))) { skipped++;advance();continue }
                    val key=kind+"/"+name;val size=file.length();val modified=file.lastModified()
                    progress?.invoke("Передача на ПК: $name")
                    val previous=acknowledged.optJSONObject(key)
                    if(previous?.optLong("size")==size && previous.optLong("modified")==modified &&
                        !(includeInverter && client.supportsInverterAppend && file.extension=="csv")) { advance();continue }
                    if(kind=="diagnostic") {
                        // Redact credential-bearing text before sending diagnostics.
                        val snapshot=File(context.cacheDir,"diagnostic-upload.tmp")
                        try {
                            file.bufferedReader().use { input ->snapshot.bufferedWriter().use { out ->
                                input.forEachLine { line ->
                                    val clean=redact(line)
                                    out.write(clean);out.newLine()
                                }
                            } }
                            if(snapshot.length()>0)client.upload(snapshot,installation,kind,name)
                        } finally { snapshot.delete() }
                    } else {
                        if(client.supportsInverterAppend && file.extension=="csv") {
                            val schema=File(file.absolutePath+".schema.json")
                            if(schema.exists())client.upload(schema,installation,kind,name+".schema.json")
                            var done=client.appendInverter(file,installation,name)
                            while(!done && fullArchive) {
                                if(Thread.currentThread().isInterrupted)throw java.io.InterruptedIOException("Синхронізацію перервано")
                                done=client.appendInverter(file,installation,name)
                            }
                            if(!done)return
                            if(fullArchive)client.verifyInverter(file,installation,name,size)
                            acknowledged.put(key,JSONObject().put("size",size).put("modified",modified))
                            File(context.cacheDir,"InverterBackup/$name.snapshot").delete()
                            File(context.cacheDir,"InverterBackup/$name.json").delete()
                        } else {
                        // A live CSV must not change the revision hash while uploading.
                        // Keep a pending snapshot on failure so a retry resumes its bytes.
                        val pending=File(context.cacheDir,"InverterBackup").apply { mkdirs() }
                        val snapshot=File(pending,name+".snapshot")
                        val revision=File(pending,name+".json")
                        if(!snapshot.exists() || !revision.exists()) {
                            require(pending.usableSpace>size+16L*1024*1024) { "Недостатньо місця для тимчасової резервної копії" }
                            val partial=File(pending,name+".partial")
                            file.inputStream().use { input ->partial.outputStream().use { out ->
                                val buffer=ByteArray(65536);var remaining=size
                                while(remaining>0) {
                                    val count=input.read(buffer,0,minOf(remaining,buffer.size.toLong()).toInt())
                                    check(count>0) { "Файл даних змінився; повторіть резервування" }
                                    out.write(buffer,0,count);remaining-=count
                                }
                            } }
                            check(partial.renameTo(snapshot))
                            revision.writeText(JSONObject().put("size",size).put("modified",modified).toString())
                        }
                        val captured=JSONObject(revision.readText())
                        client.upload(snapshot,installation,kind,name)
                        acknowledged.put(key,captured)
                        snapshot.delete();revision.delete()
                        }
                    }
                    if(kind=="diagnostic")acknowledged.put(key,JSONObject().put("size",size).put("modified",modified))
                    sent++
                    while(acknowledged.length()>1024)acknowledged.remove(acknowledged.keys().next())
                    val temporary=File(context.filesDir,if(includeInverter)"InverterBackupState.tmp" else "BackupState.tmp");temporary.writeText(acknowledged.toString())
                    check(temporary.renameTo(stateFile));advance()
                }
                // A complete traversal resets the cursor for the next pass; a 50-file
                // slice advances it so large archives cannot starve later files.
                if(files().count()<=cursors.getInt(cursorKey,0))cursors.edit().putInt(cursorKey,0).apply()
            }
            if(includeInverter) {
                val newest=inverter.walkTopDown().filter { it.isFile && it.extension=="csv" }.maxByOrNull { it.lastModified() }
                if(newest!=null)transfer(inverter,"inverter","inverter-live",newest)
                transfer(inverter,"inverter")
                transfer(File(root,"History"),"inverter","smartess-history")
                transfer(File(root,"Data/CompactHistory/inverter-1"),"inverter","compact-history")
            } else {
                transfer(diagnostics,"diagnostic");transfer(File(root,"Logs/AndroidResources"),"diagnostic","android-resources")
                transfer(File(context.filesDir,"UpdateDiagnostics"),"diagnostic","updates")
            }
            val result="ПК підтвердив ${if(includeInverter)"дані інвертора" else "діагностику"}: $sent; пропущено: $skipped."
            if(!includeInverter)status=result
            return result
        } finally { busy.set(false) }
    }
}

object ArchiveRestore {
    private val busy=java.util.concurrent.atomic.AtomicBoolean(false)
    fun restore(context:Context,url:String,source:String,progress:(String)->Unit):String {
        check(busy.compareAndSet(false,true)) { "Синхронізація вже виконується" }
        try {
            val client=LanSupportClient(context,url);val pc=client.identity()
            client.archiveSources()
            val root=File(context.filesDir,"DuckSolar")
            val prefs=context.getSharedPreferences("ArchiveRestore",Context.MODE_PRIVATE)
            val cursorKey="$pc/$source";var cursor=prefs.getInt(cursorKey,0)
            var imported=0;var unchanged=0;var revisions=0
            val first=client.archiveCatalog(source,0)
            val generation=first.getString("generation")
            if(prefs.getString(cursorKey+"/generation","")!=generation)cursor=0
            check(prefs.edit().putString(cursorKey+"/generation",generation).commit())
            while(true) {
                val catalog=client.archiveCatalog(source,cursor)
                require(catalog.getString("source_id")==source)
                if(catalog.getString("generation")!=generation) {
                    prefs.edit().putInt(cursorKey,0).commit()
                    throw IllegalStateException("Склад архіву змінився; повторіть синхронізацію. Завантажені дані збережені.")
                }
                val items=catalog.getJSONArray("items");require(items.length()<=32)
                for(i in 0 until items.length()) {
                    val row=items.getJSONObject(i).put("source_id",source)
                    progress("Історія: ${cursor+i+1}/${catalog.getInt("total")} • ${row.getString("source")} ${row.getString("name")}")
                    if(Bridge.historyImported(row)) { unchanged++;check(prefs.edit().putInt(cursorKey,cursor+i+1).commit());continue }
                    val file=client.archiveDownload(row,File(root,"Data/ArchiveDownloads"))
                    row.optJSONObject("schema")?.let { metadata ->
                        val schema=client.archiveDownload(metadata,File(root,"Data/ArchiveDownloads"))
                        schema.copyTo(File(file.absolutePath+".schema.json"),overwrite=true);schema.delete()
                    }
                    val result=Bridge.importHistory(file.absolutePath,row)
                    when(result.getString("state")) { "unchanged" -> unchanged++;"revision" -> revisions++;else -> imported++ }
                    file.delete()
                    File(file.absolutePath+".schema.json").delete()
                    check(prefs.edit().putInt(cursorKey,cursor+i+1).commit())
                }
                if(catalog.isNull("next_cursor")) { prefs.edit().putInt(cursorKey,0).commit();break }
                val next=catalog.getInt("next_cursor");require(next>cursor);cursor=next
            }
            val result="Історія синхронізована: нових $imported, без змін $unchanged, нових ревізій $revisions. Локальні журнали збережені."
            ua.ducksolar.shared.UpdateDiagnostics.record(context,"archive.sync.complete",result)
            return result
        } finally { busy.set(false) }
    }
}

class MaintenanceScheduler(private val context:Context) {
    private val worker=Executors.newSingleThreadScheduledExecutor()
    private var failures=0
    private var firstFailure=0L
    private var lastReported=0L
    private var lastReason=""
    private var pcFailures=0
    private var nextPcProbe=0L
    fun start() {
        worker.scheduleWithFixedDelay({
            val url=context.getSharedPreferences("MainActivity",Context.MODE_PRIVATE).getString("pc_url","") ?: ""
            if(url.isNotBlank() && android.os.SystemClock.elapsedRealtime()>=nextPcProbe) {
                try {
                    LanSupportClient(context,url,1).identity()
                    pcFailures=0;nextPcProbe=0L
                } catch(error:Exception) {
                    pcFailures++
                    val minutes=(15L shl (pcFailures-1).coerceAtMost(2)).coerceAtMost(60)
                    nextPcProbe=android.os.SystemClock.elapsedRealtime()+minutes*60*1000
                    ua.ducksolar.shared.UpdateDiagnostics.record(context,"support.waiting",JSONObject().put("retry_in_minutes",minutes).put("error",error.javaClass.simpleName).toString())
                    ServerMaintenance.status="ПК недоступний; наступна автоматична перевірка через $minutes хв. Ручна перевірка доступна."
                    return@scheduleWithFixedDelay
                }
                try { ServerMaintenance.sync(context,url) }
                catch(error:Exception) { ServerMaintenance.status="Діагностику не передано: "+(error.message ?: error.javaClass.simpleName) }
                val battery=context.registerReceiver(null,android.content.IntentFilter(android.content.Intent.ACTION_BATTERY_CHANGED))
                val charging=(battery?.getIntExtra(android.os.BatteryManager.EXTRA_PLUGGED,0) ?: 0)!=0
                try { if(charging) {
                    ServerMaintenance.sync(context,url,true)
                    if(failures>0)ua.ducksolar.shared.UpdateDiagnostics.record(context,"inverter.backup.resumed",JSONObject().put("failed_attempts",failures).put("first_at_ms",firstFailure).put("last_at_ms",System.currentTimeMillis()).toString())
                    failures=0;firstFailure=0;lastReason=""
                } }
                catch(error:Exception) {
                    val now=System.currentTimeMillis();val reason=error.message ?: error.javaClass.simpleName
                    val unavailable=generateSequence(error as Throwable?) { it.cause }.any { it is java.net.ConnectException || it is java.net.SocketTimeoutException || it is java.net.UnknownHostException || it is java.net.NoRouteToHostException }
                    if(failures==0)firstFailure=now
                    failures++
                    if(failures==1 || reason!=lastReason || now-lastReported>=60*60*1000L) {
                        ua.ducksolar.shared.UpdateDiagnostics.record(context,if(unavailable)"inverter.backup.waiting" else "inverter.backup.failed",JSONObject().put("reason",reason).put("failed_attempts",failures).put("first_at_ms",firstFailure).put("last_at_ms",now).toString())
                        lastReported=now;lastReason=reason
                    }
                    ServerMaintenance.status=if(unavailable)"Резервна копія очікує зв’язку з ПК; записи збережені на телефоні" else "Не вдалося передати резервну копію: $reason"
                }
            }
        },60,15*60,TimeUnit.SECONDS)
    }
    fun stop() { worker.shutdownNow() }
}
