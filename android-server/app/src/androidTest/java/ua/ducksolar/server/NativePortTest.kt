package ua.ducksolar.b2.server

import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import java.net.ServerSocket
import java.net.InetSocketAddress
import androidx.test.platform.app.InstrumentationRegistry
import com.chaquo.python.Python
import java.io.File

@RunWith(AndroidJUnit4::class)
class NativePortTest {
    @Test fun nativeRouteRecoveryAndIdentityInPython() {
        val inst=InstrumentationRegistry.getInstrumentation()
        val context=inst.targetContext
        Bridge.initialize(context)
        val folder=File(context.cacheDir,"NativeRouteFixtures").apply { mkdirs() }
        inst.context.assets.open("test_native_route.py").use { input ->
            File(folder,"test_native_route.py").outputStream().use { input.copyTo(it) }
        }
        val python=Python.getInstance()
        python.getModule("sys").get("path")!!.callAttr("insert",0,folder.absolutePath)
        val unittest=python.getModule("unittest")
        val suite=unittest.get("defaultTestLoader")!!.callAttr("loadTestsFromModule",python.getModule("test_native_route"))
        val result=unittest.callAttr("TextTestRunner",com.chaquo.python.Kwarg("verbosity",2)).callAttr("run",suite)
        assertTrue(result.toString(),result.callAttr("wasSuccessful").toBoolean())
        // Exercise the Python listener under the real unprivileged app UID.
        val listener=python.getModule("socket").callAttr("socket")
        val address=python.getModule("builtins").callAttr("tuple",arrayOf("0.0.0.0",18899))
        try { listener.callAttr("bind",address) }
        finally { listener.callAttr("close") }
    }
    @Test fun nativePortAvailableToApplicationWithoutRoot() {
        assertTrue("Must run as application UID",android.os.Process.myUid()>=10000)
        ServerSocket().use { listener ->
            listener.reuseAddress=true
            listener.bind(InetSocketAddress("0.0.0.0",18899))
            assertEquals(18899,listener.localPort)
        }
    }
}
