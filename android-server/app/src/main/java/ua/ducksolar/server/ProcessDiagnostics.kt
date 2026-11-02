package ua.ducksolar.b2.server

import android.app.ActivityManager
import android.content.Context
import android.os.Build
import android.os.Process
import org.json.JSONObject

object ProcessDiagnostics {
 private var recorded=false
 @Synchronized fun record(context:Context) {
  if(recorded)return
  val prefs=context.getSharedPreferences("ProcessDiagnostics",Context.MODE_PRIVATE)
  val previous=prefs.getInt("pid",0);val pid=Process.myPid()
  val detail=JSONObject().put("pid",pid).put("previous_pid",previous).put("version",AppVersion.name(context))
  if(Build.VERSION.SDK_INT>=30 && previous!=0) {
   try {
    val match=context.getSystemService(ActivityManager::class.java).getHistoricalProcessExitReasons(context.packageName,previous,10).firstOrNull { it.pid==previous && it.timestamp>=prefs.getLong("started_at",0) }
    detail.put("previous_exit_available",match!=null)
    if(match!=null)detail.put("reason",match.reason).put("status",match.status).put("importance",match.importance).put("exit_at_ms",match.timestamp)
   } catch(error:Exception) { detail.put("previous_exit_available",false).put("inspection_error",error.javaClass.simpleName) }
  } else detail.put("previous_exit_available",false)
  ua.ducksolar.shared.UpdateDiagnostics.record(context,"server.process.started",detail.toString())
  prefs.edit().putInt("pid",pid).putLong("started_at",System.currentTimeMillis()).commit();recorded=true
 }
}
