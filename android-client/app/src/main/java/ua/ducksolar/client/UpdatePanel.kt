package ua.ducksolar.b2.client

import android.app.Activity
import android.widget.*
import ua.ducksolar.shared.*
import java.io.File
import java.util.concurrent.Executors

object UpdatePanel {
 private val worker=Executors.newSingleThreadExecutor()
 fun attach(activity:Activity,parent:LinearLayout) {
  val prefs=activity.getSharedPreferences("ClientUpdates",Activity.MODE_PRIVATE)
  val busy=java.util.concurrent.atomic.AtomicBoolean(false)
  TextView(activity).apply { text="Оновлення та журнали";textSize=20f;parent.addView(this) }
  val address=EditText(activity).apply { hint="http://<адреса ПК>:28765"; setSingleLine();setText(prefs.getString("pc_url",""));parent.addView(this) }
  val status=TextView(activity).apply { text="ПК-служба оновлень: порт 28765";setTextIsSelectable(true);parent.addView(this) }
  fun task(action:(LanSupportClient)->String) {
   if(!busy.compareAndSet(false,true))return
   val url=address.text.toString().trim();prefs.edit().putString("pc_url",url).apply();status.text="Виконується…"
   worker.execute {
    try { val result=action(LanSupportClient(activity,url));activity.runOnUiThread { status.text=result } }
    catch(error:Exception) { UpdateDiagnostics.record(activity,"support.error",error.message ?: error.javaClass.simpleName);activity.runOnUiThread { status.text=error.message ?: "Операцію не завершено" } }
    finally { busy.set(false) }
   }
  }
  Button(activity).apply { text="Перевірити оновлення";parent.addView(this);setOnClickListener {
   UpdateInstaller.status=""
   task { client -> UpdateWorkflow.from(activity,"client",client).check() }
  } }
  Button(activity).apply { text="Встановити оновлення";parent.addView(this);setOnClickListener {
   UpdateInstaller.status=""
   task { client ->
    UpdateWorkflow.from(activity,"client",client).install({done,total->activity.runOnUiThread { status.text=DownloadProgress.text(done,total) } }) { file,update ->
     if(!UpdateInstaller.permissionReady(activity))UpdateInstaller.status
     else {
      ClientBridge.stop()
      // Stop the connection only after the complete APK passed hash/signature validation.
      try {
       val id=UpdateInstaller.install(activity,file,update)
       if(id<0) { ClientBridge.resume();UpdateInstaller.status } else "Підтвердьте встановлення у вікні Android"
      }
      catch(error:Exception) { try { ClientBridge.resume() } catch(_:Exception) {};throw error }
     }
    }
   }
  } }
  Button(activity).apply { text="Передати журнали на ПК";parent.addView(this);setOnClickListener {
   task { client ->
    val config=org.json.JSONObject(File(activity.filesDir,"connection.json").readText())
    val id=config.getString("client_id");var sent=0
    val logs=activity.filesDir.listFiles().orEmpty().filter { it.name.startsWith("client-events") && it.extension=="jsonl" }+
      File(activity.filesDir,"UpdateDiagnostics").listFiles().orEmpty().filter { it.extension=="jsonl" }
    for(file in logs) {
     if(file.length()>0) {
      val copy=File(activity.cacheDir,"upload-"+file.name)
      try { file.copyTo(copy,true);client.upload(copy,id,"diagnostic",file.name);sent++ }
      finally { copy.delete() }
     }
    }
    "ПК підтвердив журналів: $sent. Оригінали збережено."
   }
  } }
 }
}
