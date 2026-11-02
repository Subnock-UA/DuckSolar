package ua.ducksolar.b2.client

import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test

class PublicBetaIsolationTest {
    @Test fun publicClientHasNoPreconfiguredIdentity() {
        val context=InstrumentationRegistry.getInstrumentation().targetContext
        assertEquals("ua.ducksolar.b2.client",context.packageName)
        ClientBridge.initialize(context)
        val py=com.chaquo.python.Python.getInstance()
        val script="""
import android_client as c
assert c.DEFAULT_LAN == c.DEFAULT_REMOTE == ''
assert not c._cfg.get('username') and not c._cfg.get('serial')
assert not c._cfg.get('token')
""".trimIndent()
        py.getModule("builtins").callAttr("exec",script,py.getModule("builtins").callAttr("dict"))
    }
}
