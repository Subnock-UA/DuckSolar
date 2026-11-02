package ua.ducksolar.b2.server

import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test

class PublicBetaIsolationTest {
    @Test fun cleanPublicIdentityAndNoBundledMeterReadings() {
        val context=InstrumentationRegistry.getInstrumentation().targetContext
        assertEquals("ua.ducksolar.b2.server",context.packageName)
        assertEquals("b2.0.0",AppVersion.name(context))
        val prefs=context.getSharedPreferences("MainActivity",0)
        assertEquals("",prefs.getString("ip",""))
        assertEquals("",prefs.getString("pn",""))
        assertEquals("",prefs.getString("pc_url",""))
        assertTrue(prefs.getBoolean("offline",true))
        Bridge.initialize(context)
        val py=com.chaquo.python.Python.getInstance()
        val script="""
from ducksolar.config import load_config
from ducksolar.meter_bootstrap import import_snapshot
c=load_config()
assert c.lwip_ip == c.dtu_pn == c.logger_mac == c.weather_location_name == ''
assert c.weather_latitude is None and c.weather_longitude is None
assert c.api_port == 28766
assert import_snapshot(c.root_dir)['imported'] == 0
from ducksolar.storage import Storage
s=Storage(c)
assert s.seed_user_meter_readings() == 0
assert s.list_meter_readings() == []
""".trimIndent()
        py.getModule("builtins").callAttr("exec",script,py.getModule("builtins").callAttr("dict"))
        try {
            val status=Bridge.start("","",true)
            assertTrue(status.toString(),status.optBoolean("running"))
        } finally { Bridge.stop() }
    }
}
