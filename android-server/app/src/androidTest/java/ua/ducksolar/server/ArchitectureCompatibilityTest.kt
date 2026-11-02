package ua.ducksolar.b2.server

import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.json.JSONObject
import java.io.File

@RunWith(AndroidJUnit4::class)
class ArchitectureCompatibilityTest {
    @Test fun pythonNativeArchitectureAndTls() {
        val inst = InstrumentationRegistry.getInstrumentation()
        val context = inst.targetContext
        val expected = InstrumentationRegistry.getArguments().getString("expected_bits")!!.toInt()
        assertEquals(expected == 64, android.os.Process.is64Bit())
        if (expected == 32) {
            // adb --abi forces a 32-bit process on this dual-ABI emulator, but
            // Build.SUPPORTED_ABIS still puts x86_64 first. Chaquopy 17 chooses
            // assets from that order. Model a genuine 32-bit device for this test.
            val order = android.os.Build.SUPPORTED_ABIS.sortedBy {
                if (it in android.os.Build.SUPPORTED_32_BIT_ABIS) 0 else 1
            }
            order.forEachIndexed { index, abi -> android.os.Build.SUPPORTED_ABIS[index] = abi }
        }
        Bridge.initialize(context)
        val bits = com.chaquo.python.Python.getInstance().getModule("struct")
            .callAttr("calcsize", "P").toInt() * 8
        assertEquals(expected, bits)
        val checks = Bridge.selfTest()
        assertTrue(checks.getBoolean("tls13"))
        assertEquals("ok", checks.getString("sqlite_integrity"))
        val result = JSONObject().put("python_bits", bits).put("tls13", true)
            .put("sqlite_integrity", "ok").put("supported_abis", android.os.Build.SUPPORTED_ABIS.joinToString(","))
        File(context.filesDir, "ARCHITECTURE_RESULT.json").writeText(result.toString(2))
    }
}
