package ua.ducksolar.b2.client
import android.app.Activity
import android.os.Bundle
import android.graphics.Color
import android.widget.*

class BalanceActivity:ua.ducksolar.shared.LocalizedActivity() {
 private lateinit var balance:BalanceController
 override fun onCreate(state:Bundle?) {
  super.onCreate(state)
  val root=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL;setPadding(20,8,20,12);background=AppStyle.backdrop() }
  setContentView(root)
  root.setOnApplyWindowInsetsListener { _,i ->root.setPadding(20+i.systemWindowInsetLeft,8+i.systemWindowInsetTop,20+i.systemWindowInsetRight,12+i.systemWindowInsetBottom);i }
  Button(this).apply { text="‹ Додатково";isAllCaps=false;root.addView(this);setOnClickListener { finish() } }
  val content=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL }
  root.addView(ScrollView(this).apply { addView(content) },LinearLayout.LayoutParams(-1,0,1f))
  balance=BalancePanel.attach(this,content,false)
 }
 override fun onResume() { super.onResume();ClientLifecycle.enter();balance.setVisible(true) }
 override fun onPause() { ClientLifecycle.leave();balance.setVisible(false);super.onPause() }
 override fun onDestroy() { balance.close();super.onDestroy() }
}
