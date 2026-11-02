package ua.ducksolar.b2.client
import android.app.Activity
import android.app.Application
import android.os.Bundle
import android.view.ViewGroup

class DuckSolarApplication:ua.ducksolar.shared.BilingualApplication() {
 override fun onCreate() {
  super.onCreate()
  registerActivityLifecycleCallbacks(object:ActivityLifecycleCallbacks {
   override fun onActivityCreated(a:Activity,b:Bundle?) {
    a.window.decorView.post {
     if(!a.isDestroyed) {
      a.window.statusBarColor=AppStyle.canvas;a.window.navigationBarColor=AppStyle.canvas
      a.findViewById<ViewGroup>(android.R.id.content)?.let { AppStyle.watch(it) }
     }
    }
   }
   override fun onActivityResumed(a:Activity) { a.window.decorView.post { if(!a.isDestroyed)AppStyle.apply(a.findViewById(android.R.id.content)) } }
   override fun onActivityStarted(a:Activity) {} override fun onActivityPaused(a:Activity) {}
   override fun onActivityStopped(a:Activity) {} override fun onActivitySaveInstanceState(a:Activity,b:Bundle) {}
   override fun onActivityDestroyed(a:Activity) {}
  })
 }
}
