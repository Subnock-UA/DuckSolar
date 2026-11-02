package ua.ducksolar.b2.client
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class HomeMiniPatchTest {
 @Test fun friendlyNameRequiresVerifiedProfile() {
  val d=JSONObject().put("model","VMII-NXPW5KW")
  assertEquals("VMII-NXPW5KW",InverterName.display(d,null))
  d.put("profile_confirmed",true).put("profile_id","daxtromn.vmii-nxpw5kw.00074.11")
  assertEquals("DAXTROMN AGH 6.2 PRO",InverterName.display(d,null))
  d.put("model","Other inverter")
  assertEquals("Other inverter",InverterName.display(d,null))
  assertEquals("Identity model",InverterName.display(JSONObject(),JSONObject().put("model","Identity model")))
  assertEquals("—",InverterName.display(JSONObject(),null))
 }
}
