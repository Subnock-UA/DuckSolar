package ua.ducksolar.b2.server
import android.content.Context
import android.os.StatFs
import org.json.JSONObject
import java.io.File
import java.io.RandomAccessFile

object DiagnosticView {
    fun tail(file:File,limit:Int):String {
        if(!file.isFile)return ""
        return RandomAccessFile(file,"r").use { input ->
            val size=input.length();val start=(size-limit.coerceIn(1024,65536)).coerceAtLeast(0)
            input.seek(start);val bytes=ByteArray((size-start).toInt());input.readFully(bytes)
            val raw=bytes.toString(Charsets.UTF_8)
            val text=if(start>0)raw.substringAfter('\n',"") else raw
            text.lineSequence().takeLastBounded(40).joinToString("\n") { ServerMaintenance.redact(it) }
        }
    }
    private fun Sequence<String>.takeLastBounded(count:Int):List<String> {
        val result=java.util.ArrayDeque<String>()
        for(line in this) { if(result.size==count)result.removeFirst();result.addLast(line) }
        return result.toList()
    }
    fun resources(context:Context):String {
        val free=StatFs(context.filesDir.absolutePath).availableBytes/(1024*1024)
        val file=File(context.filesDir,"DuckSolar/Logs/AndroidResources/resources.jsonl")
        val row=try { JSONObject(tail(file,4096).lineSequence().last { it.isNotBlank() }) } catch(_:Exception) { null }
        return if(row==null)"Вільне сховище: $free МБ" else
            "ОЗП: ${row.optLong("pss_kib")/1024} МБ • CPU: ${"%.1f".format(row.optDouble("cpu_percent_total",row.optDouble("cpu_percent_one_core")/row.optInt("cpu_core_count",1).coerceAtLeast(1)))}% усіх ядер\nПотоків: ${row.optInt("threads")} • Вільне сховище: $free МБ\nОстання проба: ${java.text.SimpleDateFormat("HH:mm:ss",java.util.Locale.getDefault()).format(java.util.Date(row.optLong("time_ms")))}"
    }
}
