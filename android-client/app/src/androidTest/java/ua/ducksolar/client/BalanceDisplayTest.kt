package ua.ducksolar.b2.client
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.json.JSONObject

@RunWith(AndroidJUnit4::class)
class BalanceDisplayTest {
 @Test fun absentZeroAndEstimatedEnergyStayDistinct() {
  assertTrue(BalanceText.energy(JSONObject().put("kwh",JSONObject.NULL)).contains("немає даних"))
  val zero=JSONObject().put("kwh",0.0).put("coverage_pct",100.0).put("estimated_pct",0.0).put("missing_pct",0.0)
  assertTrue(BalanceText.energy(zero).startsWith("0"));assertFalse(BalanceText.energy(zero).contains("розрах."))
  zero.put("estimated_pct",50.0);assertTrue(BalanceText.energy(zero).contains("розрах."))
  assertTrue(BalanceText.coverage(zero).contains("50"))
  val day=JSONObject().put("date","2026-10-01").put("pv",zero)
  assertTrue(BalanceText.day(day).contains("2026-10-01"));assertTrue(BalanceText.day(day).contains("З мережі: —"))
 }
}
