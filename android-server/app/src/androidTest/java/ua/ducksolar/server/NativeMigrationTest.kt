package ua.ducksolar.b2.server
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.json.JSONObject
import java.io.File
import ua.ducksolar.shared.LanSupportClient
@RunWith(AndroidJUnit4::class)
class NativeMigrationTest {
 @Test fun phoneJsonUploadsPcPreparationAndVerifiedActivation() {
  assertEquals(30,android.os.Build.VERSION.SDK_INT)
  val context=InstrumentationRegistry.getInstrumentation().targetContext;Bridge.initialize(context)
  val module=com.chaquo.python.Python.getInstance().getModule("native_migration_fixture")
  try {
   val plan=JSONObject(module.callAttr("begin",context.cacheDir.absolutePath).toString())
   val client=LanSupportClient(context,"http://10.0.2.2:18817");val id=plan.getString("id");client.migrationStart(plan)
   val root=File(plan.getString("root"));val files=plan.getJSONArray("files")
   for(i in 0 until files.length()) {
    val row=files.getJSONObject(i);client.migrationUpload(id,row,File(root,row.getString("path"))) { _,_-> }
    row.optJSONObject("schema")?.let { client.migrationUpload(id,it,File(root,it.getString("path"))) { _,_-> } }
   }
   var state=client.migrationStart(plan);val deadline=System.currentTimeMillis()+120000
   while(state.optString("state")!="ready" && System.currentTimeMillis()<deadline) {
    assertNotEquals(state.toString(),"error",state.optString("state"));Thread.sleep(500);state=client.migrationStatus(id)
   }
   assertEquals(state.toString(),"ready",state.getString("state"))
   val zip=client.archiveDownload(state,File(root,"Downloads"),true,id)
   val result=JSONObject(module.callAttr("finish",zip.absolutePath,state.getString("sha256")).toString())
   assertTrue(result.getBoolean("portable_balance"));assertTrue(result.getBoolean("maintenance_api_alive"))
  } finally { module.callAttr("close") }
 }
}
