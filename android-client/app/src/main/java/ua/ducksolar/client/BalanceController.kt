package ua.ducksolar.b2.client

import android.app.Activity
import android.os.Handler
import android.os.Looper
import org.json.JSONObject
import java.lang.ref.WeakReference
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

class BalanceController(activity:Activity, private var display:((JSONObject)->Unit)?) {
 private val owner=WeakReference(activity)
 private val handler=Handler(Looper.getMainLooper())
 private val pending=AtomicBoolean(false)
 private var visible=false
 private var closed=false
 companion object { private val worker=Executors.newSingleThreadExecutor() }
 private val poll=object:Runnable {
  override fun run() {
   if(!visible || closed)return
   request { ClientBridge.balanceStatus() }
   handler.postDelayed(this,1000)
  }
 }
 private fun request(action:()->JSONObject) {
  if(closed || !pending.compareAndSet(false,true))return
  worker.execute {
   val result=try { action() } catch(e:Exception) { JSONObject().put("state","error").put("error",e.message ?: "Запит не виконано") }
   handler.post { pending.set(false);val a=owner.get();if(!closed && a!=null && !a.isDestroyed && !a.isFinishing)display?.invoke(result) }
  }
 }
 fun start(month:String,source:String="Local") { if(pending.get())handler.postDelayed({ if(!closed)start(month,source) },100) else request { ClientBridge.balanceStart(month,source) } }
 fun cancel() { if(pending.get())handler.postDelayed({ if(!closed)cancel() },100) else request { ClientBridge.balanceCancel() } }
 fun setVisible(value:Boolean) { if(visible==value)return;visible=value;handler.removeCallbacks(poll);if(value && !closed)handler.post(poll) }
 fun close() { closed=true;visible=false;display=null;handler.removeCallbacksAndMessages(null);owner.clear() }
}
