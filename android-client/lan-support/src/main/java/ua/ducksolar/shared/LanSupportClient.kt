package ua.ducksolar.shared

import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import org.json.JSONObject
import java.io.File
import java.io.RandomAccessFile
import java.net.HttpURLConnection
import java.net.Inet4Address
import java.net.InetAddress
import java.net.URI
import java.net.URLEncoder
import java.security.MessageDigest
import java.util.zip.ZipFile

data class UpdateInfo(val component:String,val version:String,val versionCode:Long,val packageName:String,
                      val sha256:String,val bytes:Long,val abis:List<String>,val path:String)

class LanSupportClient(private val context:Context,baseUrl:String,private val statusAttempts:Int=4) {
    private var supportsApkChunks=false
    var supportsInverterAppend=false
        private set
    private val base:URI=URI(baseUrl.trim())
    init {
        require(base.scheme=="http" && base.userInfo==null && base.query==null && base.fragment==null &&
                (base.path.isNullOrEmpty() || base.path=="/") && base.port in 1..65535) { "Вкажіть http://локальна-IP:порт ПК" }
        require(base.host?.matches(Regex("[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+"))==true) { "Потрібна локальна IPv4-адреса ПК" }
        val address=InetAddress.getByName(base.host)
        require(address is Inet4Address && (address.isSiteLocalAddress || address.isLoopbackAddress)) { "ПК-служба доступна лише у локальній мережі" }
    }
    private fun connection(path:String):HttpURLConnection {
        require(path.startsWith("/v1/") && !path.contains("..") && !path.contains("\\"))
        return base.resolve(path).toURL().openConnection().let { it as HttpURLConnection }.apply {
            connectTimeout=5000;readTimeout=10000;instanceFollowRedirects=false;useCaches=false
        }
    }
    private class SupportHttp(val status:Int,val retryAfter:Int):java.io.IOException("ПК-служба: HTTP $status")
    private fun delayRetry(attempt:Int,seconds:Int=0) {
        if(Thread.currentThread().isInterrupted)throw java.io.InterruptedIOException("Передачу перервано")
        try { Thread.sleep((if(seconds>0)seconds.coerceAtMost(10)*1000L else (500L shl attempt.coerceAtMost(4)))+java.util.concurrent.ThreadLocalRandom.current().nextLong(251)) }
        catch(_:InterruptedException) { Thread.currentThread().interrupt();throw java.io.InterruptedIOException("Передачу перервано") }
    }
    private fun json(path:String,body:ByteArray?=null,timeoutMs:Int=10000):JSONObject {
        val requestId=java.util.UUID.randomUUID().toString()
        val attempts=if(path=="/v1/status")statusAttempts.coerceIn(1,4) else 4
        for(attempt in 0 until attempts) {
            val c=connection(path);c.readTimeout=timeoutMs;c.setRequestProperty("X-DX-Request-ID",requestId)
            val started=android.os.SystemClock.elapsedRealtime()
            try {
                if(body!=null) { c.requestMethod="POST";c.doOutput=true;c.setFixedLengthStreamingMode(body.size);c.outputStream.use { it.write(body) } }
                val code=c.responseCode
                if(code!=200)throw SupportHttp(code,c.getHeaderField("Retry-After")?.toIntOrNull() ?: 0)
                return JSONObject(c.inputStream.use { it.readNBytesCompat(65536) }.toString(Charsets.UTF_8))
            } catch(error:java.io.IOException) {
                val detail=JSONObject().put("request_id",requestId).put("operation",path).put("attempt",attempt+1).put("duration_ms",android.os.SystemClock.elapsedRealtime()-started).put("error",error.javaClass.simpleName)
                if(error is SupportHttp)detail.put("status",error.status)
                UpdateDiagnostics.record(context,"support.request.retry",detail.toString())
                if(Thread.currentThread().isInterrupted || attempt==attempts-1 || error is SupportHttp && error.status !in listOf(429,500,502,503,504))throw error
                delayRetry(attempt,(error as? SupportHttp)?.retryAfter ?: 0)
            } finally { c.disconnect() }
        }
        error("Unreachable")
    }
    fun identity():String {
        val status=json("/v1/status");require(status.getString("contract")=="ducksolar.lan-support.v1")
        supportsInverterAppend=status.optBoolean("inverter_append",false)
        return status.getString("helper_id").also { require(it.matches(Regex("[0-9a-f]{32}"))) }
    }
    fun archiveSources():org.json.JSONArray {
        require(json("/v1/status").optInt("archive_sync")==1) { "Оновіть ПК-службу до a1.0.4" }
        return json("/v1/archive/sources",timeoutMs=60000).getJSONArray("sources")
    }
    fun archiveCatalog(source:String,cursor:Int):JSONObject {
        require(source=="pc" || source.matches(Regex("[0-9a-f]{32}")))
        require(cursor>=0)
        return json("/v1/archive/catalog?source=$source&cursor=$cursor&limit=32",timeoutMs=60000)
    }
    fun archiveRoutes(source:String):org.json.JSONArray {
        require(source.matches(Regex("[0-9a-f]{32}")))
        return json("/v1/archive/routes?source=$source",timeoutMs=60000).getJSONArray("routes")
    }
    fun verifyInverter(file:File,installation:String,name:String,size:Long) {
        require(installation.matches(Regex("[0-9a-f]{32}")) && name.matches(Regex("[A-Za-z0-9_.-]{1,160}")))
        require(size>=0 && size<=file.length())
        val hash=sha256(file,size)
        val proof=json("/v1/inverter/digest?installation=$installation&name=${URLEncoder.encode(name,"UTF-8")}&bytes=$size",timeoutMs=60000)
        require(proof.getLong("bytes")==size && proof.getString("sha256")==hash) { "Повна перевірка резервної копії не збігається: $name. Обидва оригінали збережено; потрібне вирішення конфлікту." }
    }
    fun prepareStart(model:String):JSONObject {
        require(json("/v1/status").optInt("prepared_start")==1) { "Для підготовки на ПК запустіть ПК-службу a1.0.6" }
        return json("/v1/prepared/start",model.toByteArray(Charsets.UTF_8),60000)
    }
    fun prepareStatus()=json("/v1/prepared/status",timeoutMs=60000)
    fun migrationStart(plan:JSONObject):JSONObject {
        require(json("/v1/status").optInt("history_migration")==2) { "Потрібна ПК-служба a1.0.7" }
        return json("/v1/migration/start",plan.toString().toByteArray(Charsets.UTF_8),60000)
    }
    fun migrationStatus(id:String)=json("/v1/migration/status?id=$id",timeoutMs=60000)
    fun migrationUpload(id:String,row:JSONObject,file:File,progress:(Long,Long)->Unit) {
        require(id.matches(Regex("[0-9a-f]{32}")))
        val name=row.getString("name");require(name.matches(Regex("migration_[0-9a-f]{64}\\.(csv|json)")))
        val total=row.getLong("bytes");require(file.length()==total && sha256(file)==row.getString("sha256")) { "Оригінал змінився після зупинки сервера" }
        val state=json("/v1/migration/file?id=$id&name=$name",timeoutMs=60000)
        if(state.optBoolean("verified")) { progress(total,total);return }
        var offset=state.getLong("bytes");require(offset in 0..total)
        RandomAccessFile(file,"r").use { input ->
            input.seek(offset)
            while(offset<total) {
                if(Thread.currentThread().isInterrupted)throw java.io.InterruptedIOException("Міграцію перервано")
                val data=ByteArray(minOf(256L*1024,total-offset).toInt());input.readFully(data)
                val result=json("/v1/migration/upload?id=$id&name=$name&offset=$offset&sha256=${shaBytes(data)}",data,60000)
                offset=result.getLong("bytes");progress(offset,total)
            }
        }
        require(json("/v1/migration/file?id=$id&name=$name",timeoutMs=60000).getBoolean("verified")) { "ПК не підтвердив оригінал" }
    }
    fun preparedCatalog()=json("/v1/prepared/catalog",timeoutMs=60000).getJSONArray("packages")
    fun archiveDownload(row:JSONObject,folder:File,prepared:Boolean=false,migrationId:String?=null):File {
        val hash=row.getString("sha256");val size=row.getLong("bytes")
        require(hash.matches(Regex("[0-9a-f]{64}")) && size in 1..(if(prepared)2L*1024*1024*1024 else 128L*1024*1024))
        folder.mkdirs();val partial=File(folder,"$hash.part")
        // Bound disposable unfinished transfers, never committed history objects.
        val older=folder.listFiles().orEmpty().filter { it!=partial && it.name.matches(Regex("[0-9a-f]{64}\\.part")) }.sortedBy { it.lastModified() }
        var pendingBytes=older.sumOf { it.length() }
        for(file in older) { if(pendingBytes<=256L*1024*1024)break;val length=file.length();if(file.delete())pendingBytes-=length }
        if(partial.length()>size)require(partial.delete())
        require(folder.usableSpace>size-partial.length()+16L*1024*1024) { "Недостатньо місця для історії" }
        var offset=partial.length()
        while(offset<size) {
            if(Thread.currentThread().isInterrupted)throw java.io.InterruptedIOException("Синхронізацію перервано")
            val amount=minOf(256L*1024,size-offset).toInt()
            val route=if(migrationId!=null)"migration" else if(prepared)"prepared" else "archive"
            val extra=if(migrationId!=null) { require(migrationId.matches(Regex("[0-9a-f]{32}")));"&id=$migrationId" } else ""
            val c=connection("/v1/$route/chunk?sha256=$hash&offset=$offset&length=$amount$extra")
            try {
                require(c.responseCode==200 && c.contentLengthLong==amount.toLong()) { "Не отримано частину архіву" }
                val data=c.inputStream.use { it.readNBytesCompat(amount) }
                require(data.size==amount && shaBytes(data)==c.getHeaderField("X-Chunk-SHA256")) { "Частина архіву пошкоджена" }
                java.io.FileOutputStream(partial,true).use { out ->out.write(data);out.fd.sync() }
                offset+=amount
            } finally { c.disconnect() }
        }
        if(sha256(partial)!=hash) { partial.delete();throw IllegalArgumentException("Контрольна сума історії не збігається") }
        return partial
    }
    fun manifest(component:String):UpdateInfo? {
        require(component in listOf("server","client"))
        val value=json("/v1/manifest");supportsApkChunks=value.optBoolean("apk_chunks",false);require(value.getString("contract")=="ducksolar.lan-support.v1")
        val updates=value.getJSONArray("updates");require(updates.length()<=2)
        for(i in 0 until updates.length()) {
            val row=updates.getJSONObject(i)
            if(row.getString("component")==component) {
                val abis=row.getJSONArray("abis");val allowed=(0 until abis.length()).map { abis.getString(it) }
                val update=UpdateInfo(component,row.getString("version"),row.getLong("version_code"),row.getString("package"),
                    row.getString("sha256"),row.getLong("bytes"),allowed,row.getString("url"))
                require(update.bytes in 1..128L*1024*1024 && update.versionCode>0 && update.sha256.matches(Regex("[0-9a-f]{64}")))
                require(update.path=="/v1/apk/$component")
                return update
            }
        }
        return null
    }
    fun download(update:UpdateInfo,progress:(Long,Long)->Unit={_,_->}):File = synchronized(transferLock) {
        UpdateDiagnostics.record(context,"download.begin",update.version)
        require(update.packageName==context.packageName) { "Оновлення для іншого застосунку" }
        require(Build.SUPPORTED_ABIS.any { it in update.abis }) { "APK не підтримує цей пристрій" }
        val folder=File(context.filesDir,"Updates").apply { mkdirs() }
        val ready=File(folder,"${update.component}-${update.sha256}.apk")
        val partial=File(folder,"${update.component}-${update.sha256}.part")
        if(ready.exists() && ready.length()==update.bytes && sha256(ready)==update.sha256) { verifyApk(ready,update);progress(update.bytes,update.bytes);return@synchronized ready }
        // Only derived downloads are removed. User data and original logs remain untouched.
        folder.listFiles()?.filter { it!=ready && it!=partial && it.name.matches(Regex("(server|client)-[0-9a-f]{64}\\.(apk|part)")) }?.forEach { it.delete() }
        if(partial.length()>update.bytes)partial.delete()
        require(folder.usableSpace>update.bytes-partial.length()+16L*1024*1024) { "Недостатньо місця для APK" }
        var offset=partial.length()
        progress(offset,update.bytes)
        var failures=0
        while(offset<update.bytes) {
            offset=partial.length()
            val c=connection(update.path)
            try {
                if(supportsApkChunks) {
                    val amount=minOf(256L*1024,update.bytes-offset).toInt()
                    c.setRequestProperty("Range","bytes=$offset-${offset+amount-1}")
                    val code=c.responseCode
                    if(code!=206)throw SupportHttp(code,c.getHeaderField("Retry-After")?.toIntOrNull() ?: 0)
                    require(c.getHeaderField("Content-Range")=="bytes $offset-${offset+amount-1}/${update.bytes}" && c.contentLengthLong==amount.toLong()) { "Некоректний діапазон APK" }
                    val bytes=c.inputStream.use { it.readNBytesCompat(amount) }
                    if(bytes.size!=amount || shaBytes(bytes)!=c.getHeaderField("X-Chunk-SHA256"))throw java.io.IOException("Частина APK пошкоджена")
                    java.io.FileOutputStream(partial,true).use { out ->out.write(bytes);out.fd.sync() }
                    offset=partial.length();failures=0;progress(offset,update.bytes)
                    continue
                }
                if(offset>0)c.setRequestProperty("Range","bytes=$offset-")
                val code=c.responseCode
                if(offset>0 && code==200) { partial.delete();offset=0 }
                if(code!=(if(offset>0)206 else 200))throw SupportHttp(code,c.getHeaderField("Retry-After")?.toIntOrNull() ?: 0)
                if(offset>0)require(c.getHeaderField("Content-Range")=="bytes $offset-${update.bytes-1}/${update.bytes}") { "Некоректний діапазон APK" }
                require(c.contentLengthLong==update.bytes-offset) { "Розмір APK змінився" }
                c.inputStream.use { input ->
                    java.io.FileOutputStream(partial,offset>0).use { out ->
                        val buffer=ByteArray(65536);var total=offset
                        while(true) {
                            if(Thread.currentThread().isInterrupted)throw java.io.InterruptedIOException("Завантаження перервано")
                            val count=input.read(buffer);if(count<0)break
                            total+=count;require(total<=update.bytes) { "APK перевищує заявлений розмір" };out.write(buffer,0,count);progress(total,update.bytes)
                        }
                        out.fd.sync();if(total!=update.bytes)throw java.io.EOFException("Завантаження не завершено")
                    }
                }
            } catch(error:java.io.IOException) {
                UpdateDiagnostics.record(context,"download.retry",JSONObject().put("operation",update.path).put("offset",partial.length()).put("error",error.javaClass.simpleName).toString())
                if(Thread.currentThread().isInterrupted || failures++>=3 || error is SupportHttp && error.status !in listOf(429,500,502,503,504))throw error
                delayRetry(failures,(error as? SupportHttp)?.retryAfter ?: 0)
            } finally { c.disconnect() }
            offset=partial.length()
        }
        if(sha256(partial)!=update.sha256) { partial.delete();throw IllegalArgumentException("Контрольна сума APK не збігається") }
        try { verifyApk(partial,update) } catch(error:Exception) { partial.delete();throw error }
        require(partial.renameTo(ready)) { "Не вдалося зберегти APK" }
        ready
    }
    @Suppress("DEPRECATION")
    fun verifyApk(file:File,update:UpdateInfo) {
        val flags=if(Build.VERSION.SDK_INT>=28)PackageManager.GET_SIGNING_CERTIFICATES else PackageManager.GET_SIGNATURES
        val archive=context.packageManager.getPackageArchiveInfo(file.absolutePath,flags) ?: throw IllegalArgumentException("Некоректний APK")
        val installed=context.packageManager.getPackageInfo(context.packageName,flags)
        val version=if(Build.VERSION.SDK_INT>=28)archive.longVersionCode else archive.versionCode.toLong()
        require(archive.packageName==context.packageName && archive.packageName==update.packageName && version==update.versionCode) { "APK не відповідає опису оновлення" }
        fun signatures(info:android.content.pm.PackageInfo)=
            (if(Build.VERSION.SDK_INT>=28)info.signingInfo?.apkContentsSigners else info.signatures)?.map { shaBytes(it.toByteArray()) }?.toSet() ?: emptySet()
        val owned=signatures(installed)
        var offered=signatures(archive)
        // Android 9's archive parser can omit SigningInfo despite a valid APK.
        // Its legacy parser still verifies and returns the actual certificate.
        if(offered.isEmpty()) {
            UpdateDiagnostics.record(context,"signature.legacy_fallback","Android ${Build.VERSION.SDK_INT}")
            val legacy=context.packageManager.getPackageArchiveInfo(file.absolutePath,PackageManager.GET_SIGNATURES)
            offered=legacy?.signatures?.map { shaBytes(it.toByteArray()) }?.toSet() ?: emptySet()
        }
        require(owned.isNotEmpty() && offered.isNotEmpty()) { "Android не зміг перевірити сертифікат APK" }
        require(owned==offered) { "Ключ підпису APK змінився" }
        UpdateDiagnostics.record(context,"signature.verified",update.version)
        ZipFile(file).use { zip ->
            val actual=zip.entries().asSequence().filter { it.name.startsWith("lib/") }.map { it.name.split('/')[1] }.toSet()
            require(actual.isEmpty() || Build.SUPPORTED_ABIS.any { it in actual }) { "Несумісна архітектура APK" }
        }
    }
    fun upload(file:File,installation:String,kind:String,name:String=file.name):Boolean {
        require(installation.matches(Regex("[0-9a-f]{32}")) && kind in listOf("diagnostic","inverter"))
        require(name.matches(Regex("[A-Za-z0-9_.-]{1,160}")) && !name.startsWith('.'))
        val size=file.length();require(size in 1..128L*1024*1024)
        val hash=sha256(file,size)
        val query="installation=$installation&kind=$kind&name=${URLEncoder.encode(name,"UTF-8")}&bytes=$size&sha256=$hash"
        val confirmTimeout=if(kind=="inverter")60000 else 10000
        val status=json("/v1/log/status?$query",timeoutMs=confirmTimeout)
        if(status.getBoolean("complete"))return true
        var offset=status.getLong("offset");require(offset in 0..size)
        var recoveries=0
        RandomAccessFile(file,"r").use { input ->
            while(offset<size) {
                if(Thread.currentThread().isInterrupted)throw java.io.InterruptedIOException("Копіювання перервано")
                input.seek(offset)
                val amount=minOf(256L*1024,size-offset).toInt();val chunk=ByteArray(amount);input.readFully(chunk)
                try {
                    val response=json("/v1/log/chunk?$query&offset=$offset",chunk,if(offset+amount==size)confirmTimeout else 10000)
                    val next=response.getLong("offset");require(next==offset+amount || response.getBoolean("complete") && next==size)
                    offset=next;recoveries=0
                } catch(error:java.io.IOException) {
                    if(Thread.currentThread().isInterrupted || error is SupportHttp && error.status!=409 || recoveries++>=3)throw error
                    delayRetry(recoveries)
                    val resumed=json("/v1/log/status?$query",timeoutMs=confirmTimeout)
                    offset=resumed.getLong("offset");require(offset in 0..size)
                }
            }
        }
        require(json("/v1/log/status?$query",timeoutMs=confirmTimeout).getBoolean("complete")) { "ПК не підтвердив резервну копію" }
        return true
    }
    fun appendInverter(file:File,installation:String,name:String=file.name,budgetMs:Long=10000):Boolean {
        require(supportsInverterAppend) { "ПК-служба не підтримує додавання даних" }
        require(installation.matches(Regex("[0-9a-f]{32}")) && name.matches(Regex("[A-Za-z0-9_.-]{1,160}")) && !name.startsWith('.'))
        val query="installation=$installation&name=${URLEncoder.encode(name,"UTF-8")}" 
        val state=json("/v1/inverter/status?$query",timeoutMs=60000)
        val size=file.length();var offset=state.getLong("offset");var tail=state.getString("tail_sha256")
        require(offset in 0..size) { "Резервна копія більша за файл телефона; оригінали збережено" }
        val deadline=android.os.SystemClock.elapsedRealtime()+budgetMs
        RandomAccessFile(file,"r").use { input ->
            fun regionHash(start:Long,count:Int):String {
                input.seek(start);val bytes=ByteArray(count);input.readFully(bytes);return shaBytes(bytes)
            }
            val anchor=minOf(offset,65536L).toInt()
            require(regionHash(0,anchor)==state.getString("prefix_sha256") &&
                regionHash(offset-anchor,anchor)==tail) { "Дані телефона відрізняються від резервної копії; оригінали збережено" }
            while(offset<size) {
                if(android.os.SystemClock.elapsedRealtime()>=deadline)return false
                if(Thread.currentThread().isInterrupted)throw java.io.InterruptedIOException("Резервування перервано")
                val count=minOf(256L*1024,size-offset).toInt();val chunk=ByteArray(count)
                input.seek(offset);input.readFully(chunk)
                val result=try { json("/v1/inverter/chunk?$query&offset=$offset&sha256=${shaBytes(chunk)}&previous_tail=$tail",chunk) } catch(error:SupportHttp) { if(error.status==409)return false else throw error }
                require(result.getLong("offset")==offset+count) { "ПК не підтвердив дописані дані" }
                offset+=count;tail=result.getString("tail_sha256")
            }
        }
        return true
    }
    companion object {
        private val transferLock=Any()
        fun shaBytes(bytes:ByteArray)=MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
        fun sha256(file:File,limit:Long=file.length()):String {
            val digest=MessageDigest.getInstance("SHA-256");var remaining=limit
            file.inputStream().use { input ->
                val buffer=ByteArray(65536)
                while(remaining>0) { val count=input.read(buffer,0,minOf(buffer.size.toLong(),remaining).toInt());require(count>0);digest.update(buffer,0,count);remaining-=count }
            }
            return digest.digest().joinToString("") { "%02x".format(it) }
        }
        private fun java.io.InputStream.readNBytesCompat(max:Int):ByteArray {
            val out=java.io.ByteArrayOutputStream();val buffer=ByteArray(4096)
            while(true) { val count=read(buffer);if(count<0)break;require(out.size()+count<=max) { "Відповідь ПК перевищує ліміт" };out.write(buffer,0,count) }
            return out.toByteArray()
        }
    }
}
