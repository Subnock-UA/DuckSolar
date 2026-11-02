package ua.ducksolar.b2.server

import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import ua.ducksolar.shared.UiLanguage

class LanguageSelectionTest {
 @Test fun englishDefaultUkrainianPersistenceAndInputIntegrity() {
  val inst=InstrumentationRegistry.getInstrumentation();val context=inst.targetContext
  context.getSharedPreferences("DuckSolarLanguage",0).edit().clear().commit()
  UiLanguage.load(context)
  assertEquals("en",UiLanguage.language)
  assertEquals("en",UiLanguage.localizedContext(context).resources.configuration.locales[0].language)
  assertEquals("Home",UiLanguage.text("Головна"))
  assertEquals("Grid",UiLanguage.text("Мережа"))
  assertEquals("Error: synthetic",UiLanguage.text("Помилка: synthetic"))
  assertEquals("Actual",UiLanguage.text("Факт"))
  try {
   inst.runOnMainSync {
    val root=LinearLayout(context)
    val label=TextView(context).apply { text="Головна" };root.addView(label)
    val input=EditText(context).apply { setText("Мережа");hint="Пароль" };root.addView(input)
    UiLanguage.apply(root)
    assertEquals("Home",label.text.toString());assertEquals("Мережа",input.text.toString())
    assertEquals("Password",input.hint.toString())
    UiLanguage.set(context,"uk");UiLanguage.load(context);UiLanguage.apply(root)
    assertEquals("uk",UiLanguage.language);assertEquals("Головна",label.text.toString())
    assertEquals("Пароль",input.hint.toString());assertEquals("Мережа",input.text.toString())
    UiLanguage.set(context,"en");UiLanguage.apply(root)
    assertEquals("Home",label.text.toString());assertEquals("Мережа",input.text.toString())
   }
  } finally { UiLanguage.set(context,"en") }
 }
}
