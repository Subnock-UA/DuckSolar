package ua.ducksolar.b2.client

import android.app.Activity
import android.os.Handler
import android.os.Looper
import org.json.JSONObject
import java.lang.ref.WeakReference
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

class GraphController(activity:Activity, private var display:((JSONObject)->Unit)?) {
 private val owner=WeakReference(activity)
 private val handler=Handler(Looper.getMainLooper())
 private val pending=AtomicBoolean(false)
 private var visible=false
 private var closed=false
 private var knownQuery=""
 companion object { private val worker=Executors.newSingleThreadExecutor() }
 private val poll=object:Runnable {
  override fun run() {
   if(!visible || closed)return
   request { ClientBridge.graphStatus(knownQuery) }
   handler.postDelayed(this,1000)
  }
 }
 private fun request(action:()->JSONObject) {
  if(closed || !pending.compareAndSet(false,true))return
  worker.execute {
   val result=try { action() } catch(e:Exception) { JSONObject().put("state","error").put("error",e.message ?: "Запит не виконано") }
   handler.post { pending.set(false);if(result.optString("state")=="complete")knownQuery=result.optString("query_id");val a=owner.get();if(!closed && a!=null && !a.isDestroyed && !a.isFinishing)display?.invoke(result) }
  }
 }
 fun start(period:String,anchor:String,source:String,fields:org.json.JSONArray,mode:String=if(period=="year" || period=="all")"energy" else "power",windowStart:String="",windowEnd:String="") { if(pending.get())handler.postDelayed({ if(!closed)start(period,anchor,source,fields,mode,windowStart,windowEnd) },100) else request { ClientBridge.graphStart(period,anchor,source,fields,mode,windowStart,windowEnd) } }
 fun cancel() { if(pending.get())handler.postDelayed({ if(!closed)cancel() },100) else request { ClientBridge.graphCancel() } }
 fun setVisible(value:Boolean) { if(visible==value)return;visible=value;handler.removeCallbacks(poll);if(value && !closed)handler.post(poll) }
 fun close() { closed=true;visible=false;display=null;handler.removeCallbacksAndMessages(null);owner.clear() }
}
