package ua.ducksolar.b2.client
import android.app.*
import android.content.Context
import android.content.Intent
import org.json.JSONArray

/** Post first, persist deduplication, then acknowledge to the paired server. */
class AlertDelivery(private val context:Context) {
    private val manager=context.getSystemService(NotificationManager::class.java)
    private fun contentIntent()=PendingIntent.getActivity(context,0,Intent(context,MainActivity::class.java),PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
    fun deliver(rows:JSONArray):JSONArray {
        if(!AlertMonitoring.permitted(context))return JSONArray()
        manager.createNotificationChannel(NotificationChannel("inverter_alerts",ua.ducksolar.shared.UiLanguage.text("Мережа та заряд акумуляторів"),NotificationManager.IMPORTANCE_HIGH))
        if(!AlertMonitoring.channelEnabled(context))return JSONArray()
        val prefs=context.getSharedPreferences("alerts",0)
        val seen=prefs.getStringSet("seen",emptySet())!!.toMutableSet()
        val ack=JSONArray()
        var available=(40-manager.activeNotifications.count { it.tag?.contains(':')==true }).coerceAtLeast(0)
        for(i in 0 until rows.length()) {
            val event=rows.getJSONObject(i);val id=event.optString("id");val kind=event.optString("kind")
            if(!id.matches(Regex("[0-9a-f]{32}")) || kind !in AlertMonitoring.kinds)continue
            if(!AlertMonitoring.eventEnabled(context,kind)) { ClientBridge.deliveryEvent("disabled",kind,id);ack.put(id);continue }
            if(id !in seen) {
                // Leave excess events on the server until the user dismisses
                // existing alerts; Android limits notifications per package.
                if(available==0)continue
                val created=(event.optDouble("created",System.currentTimeMillis()/1000.0)*1000).toLong()
                val stamp=java.text.SimpleDateFormat("dd.MM HH:mm:ss",java.util.Locale.getDefault()).format(java.util.Date(created))
                val detail=(if(event.has("percent"))"На час події: ${event.optDouble("percent").toInt()}%" else event.optString("detail",if(kind.startsWith("server_"))"Стан телефона або з’єднання" else "Стан підтверджено даними сервера"))+" • Подія: $stamp"
                val notification=Notification.Builder(context,"inverter_alerts").setSmallIcon(android.R.drawable.ic_dialog_alert)
                    .setContentTitle(ua.ducksolar.shared.UiLanguage.text(DisplayText.clean(event.getString("message")))).setContentText(ua.ducksolar.shared.UiLanguage.text(detail))
                    .setStyle(Notification.BigTextStyle().bigText(DisplayText.clean(event.getString("message"))+"\n"+detail))
                    .setContentIntent(contentIntent()).setAutoCancel(true).setOnlyAlertOnce(true)
                    .setCategory(Notification.CATEGORY_STATUS).setVisibility(Notification.VISIBILITY_PRIVATE)
                    .setWhen((event.optDouble("created",System.currentTimeMillis()/1000.0)*1000).toLong())
                    .setTimeoutAfter(86400000).build()
                manager.notify("$kind:$id",1,notification)
                if(manager.activeNotifications.none { it.tag=="$kind:$id" && it.id==1 }) {
                    ClientBridge.deliveryEvent("not_visible",kind,id);continue
                }
                ClientBridge.deliveryEvent("posted",kind,id)
                available--
                seen.add(id)
                // Commit after posting, before ACK. A retry uses the same tag,
                // so a crash between posting and commit replaces the alert.
                if(!prefs.edit().putStringSet("seen",seen.takeLastSafe(512)).commit()) {
                    seen.remove(id);ClientBridge.deliveryEvent("persist_failed",kind,id);continue
                }
            } else ClientBridge.deliveryEvent("duplicate",kind,id)
            ack.put(id)
        }
        return ack
    }
    private fun Set<String>.takeLastSafe(count:Int)=toList().takeLast(count).toSet()
}
