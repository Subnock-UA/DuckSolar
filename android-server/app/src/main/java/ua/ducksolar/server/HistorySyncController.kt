package ua.ducksolar.b2.server

import android.app.Activity
import org.json.JSONObject
import org.json.JSONArray
import java.io.File
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import ua.ducksolar.shared.LanSupportClient
import ua.ducksolar.shared.UpdateDiagnostics

/** One operation, durable block-level resume. Never interrupts activation. */
object HistorySyncController {
    private val worker=Executors.newSingleThreadExecutor()
    private val control=Executors.newSingleThreadExecutor()
    private val gate=Any()
    private val active=AtomicBoolean(false)
    private val cancelled=AtomicBoolean(false)
    private val activating=AtomicBoolean(false)
    @Volatile private var session=""
    @Volatile var status=""
        private set
    val running:Boolean get()=active.get()
    private fun check() { if(cancelled.get())throw java.io.InterruptedIOException("Синхронізацію зупинено") }
    fun start(activity:Activity,address:String,update:(String)->Unit) {
        if(!active.compareAndSet(false,true)) { update("Синхронізація вже виконується");return }
        synchronized(gate) { cancelled.set(false);activating.set(false);session="" }
        fun report(message:String) { status=message;activity.runOnUiThread { update(message) } }
        report("Перевіряємо зв’язок з ПК…")
        worker.execute {
            var registered=false
            try {
                Bridge.initialize(activity)
                val module=com.chaquo.python.Python.getInstance().getModule("android_bridge")
                val client=LanSupportClient(activity,address)
                client.identity();require(client.supportsHistorySync && client.supportsCompressedSync && client.supportsAppendSync && client.supportsCasRecovery && client.supportsStreamingSync) { "Для синхронізації потрібна ПК-служба b1.0.11 або новіша" }
                report("Фіксуємо знімок історії. Під час передавання збір продовжується…")
                val plan=JSONObject(module.callAttr("sync_begin").toString())
                if(plan.optBoolean("completed")) { report(plan.optString("message"));return@execute }
                session=plan.getString("id");check()
                val started=client.syncStart(plan);require(started.getString("id")==session) { "Ідентифікатор плану не збігається" };registered=true
                var uploaded=0L;var downloaded=0L;var expectedDownload=0L;var transferReported=false
                while(true) {
                    check();val need=client.syncNeed(session).getJSONArray("items")
                    if(need.length()==0)break
                    for(i in 0 until need.length()) {
                        check();val row=need.getJSONObject(i);val sha=row.getString("sha256")
                        val file=File(module.callAttr("sync_block_source",sha).toString());val data=file.readBytes()
                        require(data.size==row.getInt("bytes"));client.syncUpload(session,sha,data);uploaded+=data.size;file.delete()
                        report("Передано лише відсутні дані на ПК: ${uploaded/1024} КБ")
                    }
                }
                var state=client.syncPrepare(session)
                while(state.optString("state")!="ready") {
                    check();require(state.optString("state") !in listOf("error","cancelled")) { state.optString("error","Синхронізацію перервано") }
                    val stats=state.optJSONObject("stats") ?: JSONObject()
                    report("${when(state.optString("stage")){"discovering_changes"->"Зіставляємо архіви";"updating_changed_days"->"Оновлюємо змінені дні";"updating_changed_months"->"Оновлюємо залежні підсумки";"publishing_changes"->"Готуємо лише змінені об’єкти";"deduplicating_archives"->"Об’єднуємо перевірені копії архівів";else->"Перевіряємо зміни"}} · оброблено рядків балансу: ${stats.optLong("balance_new_rows")} · продовжень файлів: ${stats.optInt("append_sources_reused")} · нових конвертацій: ${stats.optInt("new_conversions")} · об’єктів: ${state.optInt("done")}")
                    Thread.sleep(1000);state=client.syncStatus(session)
                }
                fun download(row:JSONObject) {
                    check();val sha=row.getString("sha256");val size=row.getInt("bytes")
                    if(module.callAttr("sync_has_block",sha,size).toBoolean())return
                    val data=client.syncBlock(session,sha);require(data.size==size)
                    val temp=File(activity.cacheDir,"history-sync-$sha.block")
                    try {
                        java.io.FileOutputStream(temp).use { it.write(data);it.fd.sync() }
                        module.callAttr("sync_accept_block",sha,temp.absolutePath)
                    } finally { temp.delete() }
                    downloaded+=data.size;report("Отримуємо лише зміни з ПК: ${downloaded/1024} КБ${if(expectedDownload>0) " / ${expectedDownload/1024} КБ" else ""} · залишилось: ${if(expectedDownload>0) ((expectedDownload-downloaded).coerceAtLeast(0)/1024).toString()+" КБ" else "визначаємо"} · передано: ${uploaded/1024} КБ")
                }
                val descriptor=state.getJSONObject("manifest");val blocks=descriptor.getJSONArray("blocks")
                for(i in 0 until blocks.length())download(blocks.getJSONObject(i))
                val path=module.callAttr("sync_materialize_manifest",descriptor.toString()).toString()
                while(true) {
                    check();val transfer=JSONObject(module.callAttr("sync_transfer_plan",path).toString())
                    val missing=transfer.getJSONArray("items")
                    expectedDownload=downloaded+transfer.optLong("remaining_bytes")
                    if(!transferReported) {
                        transferReported=true
                        UpdateDiagnostics.record(activity,"history.sync.transfer_plan",JSONObject().put("session",session).put("required_bytes",transfer.optLong("total_bytes")).put("categories",transfer.optJSONObject("categories")).toString())
                    }
                    if(missing.length()==0)break
                    for(i in 0 until missing.length())download(missing.getJSONObject(i))
                }
                synchronized(gate) { check();activating.set(true) }
                report("Безпечне застосування змін. Не вимикайте сервер…")
                val ticker=java.util.concurrent.Executors.newSingleThreadScheduledExecutor()
                ticker.scheduleWithFixedDelay({
                    try {
                        val info=JSONObject(module.callAttr("sync_progress").toString())
                        val stage=when(info.optString("stage")){"stopping_for_commit"->"Завершуємо поточний запис";"validating"->"Перевіряємо отримані об’єкти";"installing"->"Встановлюємо перевірені кеші";"committing"->"Застосовуємо історію та кеші";"committed"->"Відновлюємо збір";else->"Готуємо активацію"}
                        report("$stage · ${info.optInt("done")}/${info.optInt("total")}")
                    } catch(_:Exception) { }
                },1,2,java.util.concurrent.TimeUnit.SECONDS)
                val applied=try { JSONObject(module.callAttr("sync_activate",path).toString()) } finally { ticker.shutdownNow() }
                val stats=state.optJSONObject("stats") ?: JSONObject()
                report("Історію синхронізовано. На ПК: ${uploaded/1024} КБ; з ПК: ${downloaded/1024} КБ. Оброблено рядків балансу: ${stats.optLong("balance_new_rows")}. Збір відновлено. Очищено на телефоні: ${applied.optJSONObject("cleanup")?.optLong("freed_bytes")?.div(1024) ?: 0} КБ; на ПК: ${stats.optJSONObject("archive_cleanup")?.optLong("freed_bytes")?.div(1024) ?: 0} КБ.")
            } catch(error:Exception) {
                UpdateDiagnostics.record(activity,"history.sync.failed",error.toString())
                if(cancelled.get()) {
                    try {
                        val client=LanSupportClient(activity,address)
                        if(registered)try { client.syncCancel(session) } catch(_:Exception) { /* Local recording must remain available even when PC is offline. */ }
                        val module=com.chaquo.python.Python.getInstance().getModule("android_bridge")
                        report(module.callAttr("sync_cancel_local").toString())
                    } catch(stop:Exception) { report("Зупинка очікує завершення: ${stop.message}. Архіви збережено.") }
                } else {
                    var recovery="Запустіть збір окремою кнопкою."
                    try { recovery=com.chaquo.python.Python.getInstance().getModule("android_bridge").callAttr("sync_cancel_local").toString() } catch(_:Exception) { }
                    report("Синхронізацію не завершено: ${error.message}. $recovery Уже отримані блоки збережено.")
                }
            } finally { synchronized(gate) { activating.set(false);active.set(false);session="" } }
        }
    }
    fun resume(activity:Activity,update:(String)->Unit) {
        synchronized(gate) {
            if(activating.get()) { update("Триває безпечна активація; дочекайтесь завершення.");return }
            cancelled.set(true)
            try { com.chaquo.python.Python.getInstance().getModule("android_bridge").callAttr("sync_request_stop") } catch(_:Exception) { }
        }
        worker.execute {
            try {
                Bridge.initialize(activity)
                status=com.chaquo.python.Python.getInstance().getModule("android_bridge").callAttr("sync_cancel_local").toString()
            } catch(error:Exception) { status="Відновлення: ${error.message}" }
            activity.runOnUiThread { update(status) }
        }
    }
    fun cancel(activity:Activity,address:String,update:(String)->Unit) {
        synchronized(gate) {
            if(activating.get()) { cancelled.set(true);update("Запит зупинки прийнято: завершуємо безпечну активацію, потім збір працюватиме.");return }
            cancelled.set(true)
            try { com.chaquo.python.Python.getInstance().getModule("android_bridge").callAttr("sync_request_stop") } catch(_:Exception) { }
        }
        control.execute {
            try {
                Bridge.initialize(activity)
                val module=com.chaquo.python.Python.getInstance().getModule("android_bridge")
                val id=session.ifEmpty { module.callAttr("sync_pending_id").toString() }
                if(id.isNotEmpty()) {
                    val state=LanSupportClient(activity,address).syncCancel(id)
                    if(state.optString("state")!="cancelled")status="ПК завершує поточний етап; локальний збір доступний."
                }
                if(!active.get())status=module.callAttr("sync_cancel_local").toString()
                else status="Зупинку підтверджено. Відновлюємо збір…"
            } catch(error:Exception) {
                status="ПК недоступний: ${error.message}."
                if(!active.get())try { status+=" "+com.chaquo.python.Python.getInstance().getModule("android_bridge").callAttr("sync_cancel_local").toString() } catch(local:Exception) { status+=" "+local.message }
            }
            activity.runOnUiThread { update(status) }
        }
    }
}
