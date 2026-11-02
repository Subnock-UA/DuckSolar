package ua.ducksolar.b2.client
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import android.content.Intent
import android.os.Debug
import org.json.JSONObject
import org.json.JSONArray
import java.io.File
@RunWith(AndroidJUnit4::class)
class ConnectionSoakTest {
 @Test fun liveRouteChecksAndBalanceRemainStable() {
  val inst=InstrumentationRegistry.getInstrumentation();val context=inst.targetContext
  val duration=InstrumentationRegistry.getArguments().getString("duration_s","600").toLong()*1000
  ClientBridge.initialize(context)
  inst.startActivitySync(Intent(context,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
  ClientBridge.resume()
  val deadline=System.currentTimeMillis()+15000
  while(!ClientBridge.snapshot().optBoolean("connected") && System.currentTimeMillis()<deadline)Thread.sleep(100)
  assertTrue(ClientBridge.snapshot().optBoolean("connected"))
  val samples=JSONArray();var missed=0;var advanced=0;var prior=-1L;var balances=0
  val started=System.currentTimeMillis();var check=0
  try {
   while(System.currentTimeMillis()-started<duration) {
    val snapshot=ClientBridge.snapshot();val sequence=snapshot.optJSONObject("state")?.optLong("sequence",-1) ?: -1
    if(!snapshot.optBoolean("connected"))missed++
    if(sequence>prior)advanced++;prior=sequence
    if(check%3==0)ClientBridge.networkChanged()
    if(check%6==0) { assertEquals("energy.month.compact.v1",ClientBridge.compactMonth("2026-10").getString("schema"));balances++ }
    val memory=Debug.MemoryInfo();Debug.getMemoryInfo(memory)
    samples.put(JSONObject().put("elapsed_s",(System.currentTimeMillis()-started)/1000).put("pss_kib",memory.totalPss).put("connected",snapshot.optBoolean("connected")).put("sequence",sequence))
    check++;Thread.sleep(5000)
   }
   val report=JSONObject().put("duration_s",duration/1000).put("samples",samples).put("missed",missed).put("advanced",advanced).put("balance_requests",balances)
   File(context.filesDir,"CONNECTION_SOAK_RESULT.json").writeText(report.toString())
   assertEquals("Unplanned live disconnects",0,missed);assertTrue("Live sequence stopped advancing",advanced>=samples.length()-2)
   val initial=samples.getJSONObject(minOf(12,samples.length()-1)).getInt("pss_kib")
   val final=samples.getJSONObject(samples.length()-1).getInt("pss_kib")
   assertTrue("Ten-minute client PSS growth exceeds 16MiB",final-initial<16384)
  } finally { ClientBridge.stop() }
 }
}
