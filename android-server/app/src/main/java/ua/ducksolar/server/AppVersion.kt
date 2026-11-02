package ua.ducksolar.b2.server
object AppVersion {
 fun name(context:android.content.Context):String = try { context.packageManager.getPackageInfo(context.packageName,0).versionName ?: "—" } catch(_:Exception) { "—" }
}
