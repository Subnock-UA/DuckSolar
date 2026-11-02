package ua.ducksolar.b2.client
import android.content.Context
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject
object ClientBridge {
 private var appContext:Context?=null
 @Synchronized fun initialize(context:Context):JSONObject {
  appContext=context.applicationContext
  if(!Python.isStarted())Python.start(AndroidPlatform(context.applicationContext))
  return JSONObject(module().callAttr("initialize",context.filesDir.absolutePath).toString())
 }
 private fun module()=Python.getInstance().getModule("android_client")
 fun connect(lan:String,remote:String,user:String,password:String,serial:String,code:String,register:Boolean)=JSONObject(module().callAttr("connect",lan,remote,user,password,serial,code,register).toString())
 private fun networkState() {
  val manager=appContext?.getSystemService(android.net.ConnectivityManager::class.java) ?: return
  val active=manager.activeNetwork
  val wifi=active?.let { manager.getNetworkCapabilities(it)?.hasTransport(android.net.NetworkCapabilities.TRANSPORT_WIFI) }==true
  module().callAttr("network_state",active!=null,wifi,active?.toString() ?: "")
 }
 fun resume():JSONObject { networkState();return JSONObject(module().callAttr("resume").toString()) }
 fun networkChanged():JSONObject { networkState();return JSONObject(module().callAttr("network_changed").toString()) }
 fun switchRoute(route:String,lan:String,remote:String)=JSONObject(module().callAttr("switch_route",route,lan,remote).toString())
 fun lastSnapshot()=JSONObject(module().callAttr("last_snapshot").toString())
 fun stop()=module().callAttr("stop")
 fun lifecycleEvent(event:String)=module().callAttr("lifecycle_event",event)
 fun snapshot():JSONObject { networkState();return JSONObject(module().callAttr("snapshot").toString()).also { value -> appContext?.let { SolarWidget.capture(it,value) } } }
 fun compactMonth(month:String)=JSONObject(module().callAttr("compact_month",month).toString())
 fun meterReadings()=org.json.JSONArray(module().callAttr("meter_readings").toString())
 fun balanceStart(month:String,source:String="Local")=JSONObject(module().callAttr("balance_start",month,source).toString())
 fun balanceStatus()=JSONObject(module().callAttr("balance_status").toString())
 fun balanceCancel()=JSONObject(module().callAttr("balance_cancel").toString())
 fun events()=org.json.JSONArray(module().callAttr("event_rows").toString())
 fun weatherStatus()=JSONObject(module().callAttr("weather_status").toString())
 fun weatherSettings(value:JSONObject)=JSONObject(module().callAttr("weather_settings",value.toString()).toString())
 fun weatherStart(train:Boolean)=JSONObject(module().callAttr("weather_start",train).toString())
 fun weatherCancel(pause:Boolean=false)=JSONObject(module().callAttr("weather_cancel",pause).toString())
 fun weatherResume()=JSONObject(module().callAttr("weather_resume").toString())
 fun weatherProfile()=JSONObject(module().callAttr("weather_profile").toString())
 fun connectionHealth()=JSONObject(module().callAttr("connection_health").toString())
 fun historyDates()=JSONObject(module().callAttr("history_dates").toString())
 fun graphStart(period:String,anchor:String,source:String,fields:org.json.JSONArray,mode:String=if(period=="year" || period=="all")"energy" else "power",windowStart:String="",windowEnd:String="")=JSONObject(module().callAttr("graph_start",period,anchor,source,fields.toString(),mode,windowStart,windowEnd).toString())
 fun graphStatus(knownQuery:String="")=JSONObject(module().callAttr("graph_status",knownQuery).toString())
 fun graphCancel()=JSONObject(module().callAttr("graph_cancel").toString())
 fun financeMonth(month:String)=JSONObject(module().callAttr("finance_month",month).toString())
 fun addMeterReading(stamp:String,values:JSONObject)=JSONObject(module().callAttr("add_meter_reading",stamp,values.toString(),true).toString())
 fun parameters()=JSONObject(module().callAttr("parameter_snapshot").toString())
 fun refreshParameters()=module().callAttr("refresh_parameters")
 fun submitParameter(key:String,value:String,expected:String,device:String,profile:String)=JSONObject(module().callAttr("submit_parameter",key,value,expected,device,true,profile).toString())
 fun commandStatus()=JSONObject(module().callAttr("parameter_command_status").toString())
 fun tariffStatus()=JSONObject(module().callAttr("tariff_status").toString())
 fun tariffCheck()=JSONObject(module().callAttr("tariff_check").toString())
 fun notificationSettings(value:String="")=JSONObject(module().callAttr("notification_settings",value).toString())
 fun notificationBatch()=JSONObject(module().callAttr("notification_batch").toString())
 fun notificationAck(ids:org.json.JSONArray)=module().callAttr("notification_ack",ids.toString())
 fun backgroundEvent(kind:String,details:JSONObject)=module().callAttr("background_event",kind,details.toString())
 fun deliveryEvent(result:String,kind:String,id:String)=module().callAttr("delivery_event",result,kind,id)
 fun widgetSnapshot():JSONObject { networkState();return JSONObject(module().callAttr("widget_snapshot").toString()) }
 fun featureCall(method:String,args:org.json.JSONArray=org.json.JSONArray())=JSONObject().put("value",org.json.JSONTokener(module().callAttr("feature_call",method,args.toString()).toString()).nextValue()).get("value")
 fun featureStart(kind:String,anchor:String,other:String="",period:String="day",metric:String="pv_w")=JSONObject(module().callAttr("feature_start",kind,anchor,other,period,metric).toString())
 fun featureStatus()=JSONObject(module().callAttr("feature_status").toString())
}
