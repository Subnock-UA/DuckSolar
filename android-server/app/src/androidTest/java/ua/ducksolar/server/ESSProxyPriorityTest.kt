package ua.ducksolar.b2.server

import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import java.io.File
import org.json.JSONObject
import com.chaquo.python.Python

@RunWith(AndroidJUnit4::class)
class ESSProxyPriorityTest {
    @Test fun realTcpPriorityReuseAndOfflineFallback() {
        val inst=InstrumentationRegistry.getInstrumentation()
        val context=inst.targetContext
        Bridge.initialize(context)
        val folder=File(context.cacheDir,"ESSFixtures").apply { mkdirs() }
        for(name in listOf("test_ess.py","test_priority.py","test_settings_proxy.py","test_beta_settings.py")) {
            inst.context.assets.open(name).use { input ->File(folder,name).outputStream().use { input.copyTo(it) } }
        }
        val python=Python.getInstance()
        python.getModule("sys").get("path")!!.callAttr("insert",0,folder.absolutePath)
        val unittest=python.getModule("unittest")
        val loader=unittest.get("defaultTestLoader")!!
        val suite=loader.callAttr("loadTestsFromModule",python.getModule("test_priority"))
        suite.callAttr("addTests",loader.callAttr("loadTestsFromName","test_ess.SocketTests.test_full_proxy_local_reuse_and_cloud_loss"))
        suite.callAttr("addTests",loader.callAttr("loadTestsFromName","test_settings_proxy.SettingsProxyTest"))
        suite.callAttr("addTests",loader.callAttr("loadTestsFromName","test_beta_settings.SettingsBetaTests"))
        val result=unittest.callAttr("TextTestRunner",com.chaquo.python.Kwarg("verbosity",2)).callAttr("run",suite)
        assertTrue(result.toString(),result.callAttr("wasSuccessful").toBoolean())
        File(context.filesDir,"ESS_PROXY_RESULT.json").writeText(JSONObject()
            .put("tests",result.get("testsRun")!!.toInt()).put("success",true)
            .put("actual_equipment",false).put("android_api",android.os.Build.VERSION.SDK_INT).toString())
    }
}
