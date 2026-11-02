package ua.ducksolar.b2.client

import android.os.Handler
import android.os.Looper
import java.util.concurrent.Executors

/** Shared across all client screens: internal navigation keeps the live channel. */
object ClientLifecycle {
 private val handler=Handler(Looper.getMainLooper())
 private val worker=Executors.newSingleThreadExecutor()
 @Volatile private var screens=0
 private val background=Runnable { worker.execute { if(screens==0)try { ClientBridge.lifecycleEvent("background") } catch(_:Exception) {} } }
 private val stop=Runnable { worker.execute { if(screens==0 && !NotificationService.running)try { ClientBridge.stop() } catch(_:Exception) {} } }
 fun hasScreens()=screens>0
 fun enter() {
  screens++;handler.removeCallbacks(stop);handler.removeCallbacks(background)
  worker.execute { try { ClientBridge.lifecycleEvent("foreground");ClientBridge.resume() } catch(_:Exception) {} }
 }
 fun leave() {
  screens=(screens-1).coerceAtLeast(0)
  if(screens==0) {
   handler.removeCallbacks(background);handler.postDelayed(background,700)
   handler.removeCallbacks(stop);handler.postDelayed(stop,8000)
  }
 }
}
