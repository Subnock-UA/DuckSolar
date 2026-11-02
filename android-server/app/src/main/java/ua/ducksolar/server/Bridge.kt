package ua.ducksolar.b2.server

import android.content.Context
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject

object Bridge {
    private var application:Context?=null
    @Volatile var state = "Сервер зупинено"
    @Synchronized fun initialize(context: Context) {
        application=context.applicationContext
        ProcessDiagnostics.record(context.applicationContext)
        if (!Python.isStarted()) Python.start(AndroidPlatform(context.applicationContext))
        module().callAttr("initialize", context.filesDir.absolutePath)
    }
    private fun module() = Python.getInstance().getModule("android_bridge")
    fun start(ip: String, pn: String, offline: Boolean, equipmentMode:String="normal"): JSONObject =
        JSONObject(module().callAttr("start", ip, pn, offline,equipmentMode).toString())
    fun stop() = JSONObject(module().callAttr("stop").toString())
    fun status() = JSONObject(module().callAttr("status").toString())
    fun pairingCode() = module().callAttr("pairing_code").toString()
    fun updateCheckpoint(target:String):JSONObject {
        val result=JSONObject(module().callAttr("update_checkpoint",target).toString())
        val context=checkNotNull(application)
        val folder=java.io.File(context.filesDir,"DuckSolar/UpdateCheckpoints/${result.getString("checkpoint")}")
        val preferences=java.io.File(folder,"Android/MainActivity.preferences.json")
        preferences.parentFile?.mkdirs()
        preferences.writeText(JSONObject(context.getSharedPreferences("MainActivity",Context.MODE_PRIVATE).all).toString())
        val file=java.io.File(folder,"manifest.json");val manifest=JSONObject(file.readText())
        manifest.getJSONArray("files").put(JSONObject().put("path","Android/MainActivity.preferences.json")
            .put("bytes",preferences.length()).put("sha256",ua.ducksolar.shared.LanSupportClient.sha256(preferences)))
        file.writeText(manifest.toString());result.put("files",manifest.getJSONArray("files").length())
        return result
    }
    fun verifyAfterUpdate() = JSONObject(module().callAttr("verify_after_update").toString())
    fun importHistory(path:String,metadata:JSONObject) = JSONObject(module().callAttr("import_history",path,metadata.toString()).toString())
    fun historyImported(metadata:JSONObject) = module().callAttr("history_import_status",metadata.toString()).toBoolean()
    fun essHistoryStatus() = JSONObject(module().callAttr("ess_history_status").toString())
    fun essHistoryStart(username:String,password:String,pn:String,start:String,end:String) = JSONObject(module().callAttr("ess_history_start",username,password,pn,start,end).toString())
    fun essHistoryStop() = JSONObject(module().callAttr("ess_history_stop").toString())
    fun historyInventory() = JSONObject(module().callAttr("history_inventory").toString())
    fun recoverEssRoute(row:JSONObject) = JSONObject(module().callAttr("recover_ess_route",row.toString()).toString())
    fun selfTest() = JSONObject(module().callAttr("self_test").toString())
    fun forecastStatus(device:String="")=JSONObject(module().callAttr("forecast_status",device).toString())
    fun cacheStatus()=JSONObject(module().callAttr("graph_cache_status").toString())
    fun cacheStart()=JSONObject(module().callAttr("graph_cache_start").toString())
    fun cacheCancel()=JSONObject(module().callAttr("graph_cache_cancel").toString())
    fun forecastTrain(settings:JSONObject,force:Boolean,device:String="")=JSONObject(module().callAttr("forecast_train",settings.toString(),force,device).toString())
    fun forecastCancel(device:String="")=JSONObject(module().callAttr("forecast_cancel",device).toString())
}
