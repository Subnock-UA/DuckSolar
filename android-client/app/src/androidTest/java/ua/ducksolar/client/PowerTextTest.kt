package ua.ducksolar.b2.client
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.json.JSONObject
import java.util.Locale

@RunWith(AndroidJUnit4::class)
class PowerTextTest {
 @Test fun wattsAndVaUseOriginalThresholdAndPfHasTwoDecimals() {
  val prior=Locale.getDefault();Locale.setDefault(Locale.US)
  try {
   assertEquals("410 Вт",HomePowerText.format(410.0,"W"))
   assertEquals("999 Вт",HomePowerText.format(999.0,"W"))
   assertEquals("1.00 кВт",HomePowerText.format(1000.0,"W"))
   assertEquals("1.25 кВА",HomePowerText.format(1250.0,"VA"))
   assertEquals("0 ВА",HomePowerText.format(0.0,"VA"))
   assertNull(HomePowerText.format(Double.NaN,"W"))
   assertNull(HomePowerText.format(13.9,"кВт·год"))
   val pf=JSONObject().put("value",410.0/450).put("unit","").put("quality","good").put("precision",2)
   assertEquals("0.91",MetricText.value(pf,false).trim())
  } finally { Locale.setDefault(prior) }
 }
}
