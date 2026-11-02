package ua.ducksolar.b2.client

import android.content.Intent
import android.graphics.*
import android.view.View
import android.view.ViewGroup
import android.widget.*
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

@RunWith(AndroidJUnit4::class)
class ForecastArtworkPatchTest {
 private fun views(v:View):List<View> = listOf(v)+(if(v is ViewGroup)(0 until v.childCount).flatMap { views(v.getChildAt(it)) } else emptyList())
 @Test fun recoloringPreservesApprovedCasingDarkScreenAndAlpha() {
  val context=InstrumentationRegistry.getInstrumentation().targetContext
  val original=BitmapFactory.decodeResource(context.resources,R.drawable.inverter_agh_pro)
  for(color in listOf(InverterArtwork.BLUE,InverterArtwork.RED,InverterArtwork.PURPLE)) {
   val image=InverterArtwork.recolor(original,color)
   // The actual strip is top-center; the LCD and lower white cover are unchanged.
   val x=original.width/2;val lightY=(original.height*.2f).toInt()
   val pixel=image.getPixel(x,lightY)
   assertTrue("Stripe should change to requested hue",when(color) { InverterArtwork.BLUE->Color.blue(pixel)>Color.red(pixel);InverterArtwork.PURPLE->Color.blue(pixel)>Color.green(pixel);else->Color.red(pixel)>Color.green(pixel) })
   for((rx,ry) in listOf(.5f to .7f,.5f to .9f,.2f to .3f,.03f to .03f)) {
    val px=(original.width*rx).toInt();val py=(original.height*ry).toInt()
    assertEquals(original.getPixel(px,py),image.getPixel(px,py))
   }
   assertEquals(original.width,image.width);assertEquals(original.height,image.height);image.recycle()
  }
  assertTrue(Color.red(original.getPixel(original.width/2,(original.height*.9f).toInt()))>180)
  original.recycle()
 }
 @Test fun realServerResultShowsActualBarsInBothForecastScreens() {
  val inst=InstrumentationRegistry.getInstrumentation();val context=inst.targetContext;ClientBridge.initialize(context)
  val fixture=JSONObject(inst.context.assets.open("forecast-fact-regression.json").bufferedReader().readText())
  assertTrue(fixture.getJSONObject("comparison").getDouble("observed_kwh")>0)
  for(kind in listOf("forecast","forecast_live")) {
   val a=inst.startActivitySync(Intent(context,InsightsActivity::class.java).putExtra("page",if(kind=="forecast")"forecast_actual" else "forecast_live").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
   try {
    val result=JSONObject(fixture.toString()).put("kind",kind)
    inst.runOnMainSync {
     InsightsActivity::class.java.getDeclaredMethod("renderResult",JSONObject::class.java).apply { isAccessible=true }.invoke(a,result)
     assertEquals("Exactly one graph, without legacy duplicate",1,views(a.window.decorView).count { it is HistoryChart })
    }
    inst.waitForIdleSync()
    inst.runOnMainSync {
     val chart=views(a.window.decorView).filterIsInstance<HistoryChart>().single()
     val image=Bitmap.createBitmap(900,600,Bitmap.Config.ARGB_8888);chart.layout(0,0,900,600);chart.draw(Canvas(image))
     var teal=0;for(y in 20 until 560 step 2)for(x in 150 until 850 step 2) { val p=image.getPixel(x,y);if(Color.green(p)>70 && Color.blue(p)>60 && Color.red(p)<60)teal++ }
     assertTrue("Actual series must paint real colored bars",teal>200)
     File(context.cacheDir,"forecast-$kind-chart.png").outputStream().use { image.compress(Bitmap.CompressFormat.PNG,100,it) };image.recycle()
    }
   } finally { inst.runOnMainSync { a.finish() } }
  }
 }
}
