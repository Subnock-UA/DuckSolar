package ua.ducksolar.shared

import android.content.Context
import org.json.JSONObject
import java.io.File

object UpdateDiagnostics {
    @Synchronized fun record(context:Context,event:String,detail:String="") {
        try {
            val folder=File(context.filesDir,"UpdateDiagnostics").apply { mkdirs() }
            val file=File(folder,"update-events.jsonl")
            if(file.length()>128*1024)file.renameTo(File(folder,"update-events.1.jsonl").apply { delete() })
            val safe=detail.replace(Regex("(?i)Bearer\\s+[^\\s]+"),"Bearer [REDACTED]")
                .replace(Regex("(?i)(password|token|secret|trust_ticket|pairing_code)\\s*[:=]\\s*[^\\s,}]+"),"$1=[REDACTED]")
            file.appendText(JSONObject().put("time",System.currentTimeMillis()).put("event",event)
                .put("detail",safe.take(512)).toString()+"\n")
        } catch(_:Exception) { }
    }
}
