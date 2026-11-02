package ua.ducksolar.b2.client

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.util.UUID
import java.io.File

@RunWith(AndroidJUnit4::class)
class LongBalanceTimeoutTest {
 @Test fun responseAfterPrevious120SecondLimitIsReceivedOnce() {
  val inst=InstrumentationRegistry.getInstrumentation();val context=inst.targetContext;val args=InstrumentationRegistry.getArguments()
  ClientBridge.initialize(context)
  ClientBridge.connect("https://127.0.0.1:28766","","slow_"+UUID.randomUUID().toString().replace("-","").take(12),"fixture-pass-"+UUID.randomUUID(),args.getString("serial")!!,args.getString("pair_code")!!,true)
  ClientBridge.balanceStart("2026-08")
  val query=ClientBridge.balanceStatus().getString("query_id")
  val deadline=System.currentTimeMillis()+145000
  var state=ClientBridge.balanceStatus()
  while(state.optString("state")=="running" && System.currentTimeMillis()<deadline) {
   assertEquals(query,ClientBridge.balanceStart("2026-09").getString("query_id"))
   Thread.sleep(1000);state=ClientBridge.balanceStatus()
  }
  File(context.filesDir,"LONG_BALANCE_RESULT.json").writeText(state.toString())
  assertEquals(state.toString(),"complete",state.optString("state"))
  assertTrue(state.getDouble("elapsed_s")>=125)
  assertEquals("2026-08",state.getString("month"))
 }
}
