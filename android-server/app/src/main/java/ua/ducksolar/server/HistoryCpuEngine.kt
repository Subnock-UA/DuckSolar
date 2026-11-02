package ua.ducksolar.b2.server

import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.Callable
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.ThreadPoolExecutor
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong
import kotlin.math.max
import kotlin.math.min
import org.json.JSONObject

/** CPU arithmetic runs entirely in ART: no Python objects or callbacks in workers.
 * Rows: t,PV,load,importW,exportW,importCounter,exportCounter,importID,exportID,
 * importMod,exportMod,importSource,exportSource,importOrigin,exportOrigin.
 * Each ordered, non-overlapping UTC window returns touched + 4*(kWh,covered,
 * measured,count,resets). All buffers are little endian doubles, version 1.
 */
object HistoryCpuEngine {
 private const val ROW=15
 private const val OUT=21
 private val cores=max(1,Runtime.getRuntime().availableProcessors())
 private val serial=AtomicInteger()
 private val pool=ThreadPoolExecutor(cores,cores,30,TimeUnit.SECONDS,LinkedBlockingQueue<Runnable>()) { task ->
  Thread(task,"HistoryCPU-${serial.incrementAndGet()}").apply { isDaemon=true }
 }.apply { allowCoreThreadTimeOut(true) }
 private val active=AtomicInteger()
 private val peak=AtomicInteger()
 private val calls=AtomicLong()
 private val pairs=AtomicLong()
 private val cpuNs=AtomicLong()
 private val lastWorkers=AtomicInteger()
 private val hourlyRows=AtomicLong()
 private val hourlyBatches=AtomicLong()

 @JvmStatic fun status():String=JSONObject().put("engine","android.art.cpu.v1")
  .put("outside_python_gil",true).put("processor_limit",cores).put("active_workers",active.get())
  .put("peak_active_workers",peak.get()).put("last_workers",lastWorkers.get())
  .put("batches",calls.get()).put("pairs",pairs.get()).put("worker_cpu_ms",cpuNs.get()/1e6)
  .put("hourly_rows",hourlyRows.get()).put("hourly_batches",hourlyBatches.get())
  .put("idle_threads_released_after_s",30).toString()

 /** Hourly display means. Chunks return sums/counts and boundary row indexes,
  * so their coordinator can merge the same hour without averaging averages.
  * Input: UTC time, four source/origin IDs, N numeric columns. No Python calls.
  */
 @JvmStatic fun hourly(input:ByteArray,counterFlags:ByteArray,maxGap:Double,requested:Int):ByteArray {
  val fields=counterFlags.size;val width=5+fields;val stride=4+fields*2
  require(fields in 1..64 && input.size%(width*8)==0 && input.size<=65536*width*8 && maxGap.isFinite() && maxGap>=0)
  val d=DoubleArray(input.size/8);ByteBuffer.wrap(input).order(ByteOrder.LITTLE_ENDIAN).asDoubleBuffer().get(d)
  val n=d.size/width;val workers=min(min(cores,max(1,requested)),max(1,n/256))
  lastWorkers.set(workers);hourlyBatches.incrementAndGet();hourlyRows.addAndGet(n.toLong())
  val futures=(0 until workers).map { worker -> pool.submit(Callable {
   val running=active.incrementAndGet();peak.updateAndGet { max(it,running) }
   val started=android.os.Debug.threadCpuTimeNanos();val segments=ArrayList<DoubleArray>();var current:DoubleArray?=null
   try {
    for(i in worker*n/workers until (worker+1)*n/workers) {
     if(i%256==0 && Thread.currentThread().isInterrupted)throw InterruptedException("Hourly preparation cancelled")
     val at=i*width;val bucket=kotlin.math.floor(d[at]/3600);val prev=at-width
     val gap=i>0 && d[at]-d[prev]>maxGap
     val changed=i>0 && (1..4).any { d[at+it]!=d[prev+it] }
     if(current==null || bucket!=current!![3] || gap || changed) {
      current=DoubleArray(stride);current!![0]=i.toDouble();current!![2]=if(gap)1.0 else 0.0;current!![3]=bucket;segments.add(current!!)
     }
     current!![1]=i.toDouble()
     for(field in 0 until fields) {
      val value=d[at+5+field]
      if(value.isFinite()) {
       if(counterFlags[field].toInt()!=0) { current!![4+field]=value;current!![4+fields+field]=1.0 }
       else { current!![4+field]+=value;current!![4+fields+field]+=1.0 }
      }
     }
    }
    segments
   } finally { cpuNs.addAndGet(android.os.Debug.threadCpuTimeNanos()-started);active.decrementAndGet() }
  }) }
  try {
   val all=futures.map { it.get() };val count=all.sumOf { it.size }
   val out=ByteBuffer.allocate(count*stride*8).order(ByteOrder.LITTLE_ENDIAN)
   for(group in all)for(segment in group)for(value in segment)out.putDouble(value)
   return out.array()
  } catch(error:Exception) { futures.forEach { it.cancel(true) };throw error }
 }

 @JvmStatic fun calculate(input:ByteArray,bounds:ByteArray,maxGap:Double,requested:Int):ByteArray {
  require(input.size%(ROW*8)==0 && input.size<=65537*ROW*8)
  require(bounds.size%16==0 && bounds.size<=4096*16 && maxGap.isFinite() && maxGap>=0)
  val data=DoubleArray(input.size/8);ByteBuffer.wrap(input).order(ByteOrder.LITTLE_ENDIAN).asDoubleBuffer().get(data)
  val windows=DoubleArray(bounds.size/8);ByteBuffer.wrap(bounds).order(ByteOrder.LITTLE_ENDIAN).asDoubleBuffer().get(windows)
  for(i in windows.indices step 2)require(windows[i].isFinite() && windows[i+1].isFinite() && windows[i+1]>windows[i] && (i==0 || windows[i]>=windows[i-1]))
  val n=max(0,data.size/ROW-1);val workers=min(min(cores,max(1,requested)),max(1,n/256))
  lastWorkers.set(workers);calls.incrementAndGet();pairs.addAndGet(n.toLong())
  val tasks=(0 until workers).map { worker -> Callable {
   val running=active.incrementAndGet();peak.updateAndGet { max(it,running) }
   val started=android.os.Debug.threadCpuTimeNanos()
   try { integrate(data,windows,maxGap,worker*n/workers,(worker+1)*n/workers) }
   finally { cpuNs.addAndGet(android.os.Debug.threadCpuTimeNanos()-started);active.decrementAndGet() }
  } }
  // Coordinators do not occupy this pool, so simultaneous requests cannot cause
  // the nested-executor deadlock of workers waiting for their own children.
  val futures=tasks.map { pool.submit(it) }
  val result=DoubleArray(windows.size/2*OUT)
  try {
   for(future in futures) {
    val part=future.get()
    for(i in result.indices)result[i]+=part[i]
   }
  } catch(error:Exception) {
   futures.forEach { it.cancel(true) };throw error
  }
  return ByteBuffer.allocate(result.size*8).order(ByteOrder.LITTLE_ENDIAN).apply { asDoubleBuffer().put(result) }.array()
 }

 /** Five legacy generation-summary power columns, without grid-counter logic. */
 @JvmStatic fun plain(input:ByteArray,maxGap:Double,requested:Int):ByteArray {
  require(input.size%48==0 && input.size<=65537*48 && maxGap.isFinite() && maxGap>=0)
  val d=DoubleArray(input.size/8);ByteBuffer.wrap(input).order(ByteOrder.LITTLE_ENDIAN).asDoubleBuffer().get(d)
  val n=max(0,d.size/6-1);val workers=min(min(cores,max(1,requested)),max(1,n/256))
  calls.incrementAndGet();pairs.addAndGet(n.toLong());lastWorkers.set(workers)
  val futures=(0 until workers).map { worker -> pool.submit(Callable {
   val running=active.incrementAndGet();peak.updateAndGet { max(it,running) }
   val started=android.os.Debug.threadCpuTimeNanos();val out=DoubleArray(6)
   try {
    for(i in worker*n/workers until (worker+1)*n/workers) {
     if(i%256==0 && Thread.currentThread().isInterrupted)throw InterruptedException("History calculation cancelled")
     val a=i*6;val b=a+6;val dt=d[b]-d[a]
     if(dt>0 && dt<=maxGap) {
      out[5]+=dt
      for(field in 0..4)if(d[a+1+field].isFinite() && d[b+1+field].isFinite())out[field]+=(d[a+1+field]+d[b+1+field])*.5*dt
     }
    }
    out
   } finally { cpuNs.addAndGet(android.os.Debug.threadCpuTimeNanos()-started);active.decrementAndGet() }
  }) }
  val out=DoubleArray(6)
  try { for(future in futures) { val part=future.get();for(i in out.indices)out[i]+=part[i] } }
  catch(error:Exception) { futures.forEach { it.cancel(true) };throw error }
  for(i in 0..4)out[i]/=3600000
  return ByteBuffer.allocate(48).order(ByteOrder.LITTLE_ENDIAN).apply { asDoubleBuffer().put(out) }.array()
 }

 private fun integrate(d:DoubleArray,w:DoubleArray,gap:Double,from:Int,to:Int):DoubleArray {
  val out=DoubleArray(w.size/2*OUT)
  for(i in from until to) {
   if(i%256==0 && Thread.currentThread().isInterrupted)throw InterruptedException("History calculation cancelled")
   val a=i*ROW;val b=a+ROW;val x=d[a];val y=d[b];val dt=y-x
   if(!x.isFinite() || !y.isFinite() || dt<=0)continue
   // First window whose right edge is strictly beyond the pair's left edge.
   var lo=0;var hi=w.size/2
   while(lo<hi) { val mid=(lo+hi)/2;if(w[mid*2+1]<=x)lo=mid+1 else hi=mid }
   var window=lo
   while(window<w.size/2 && w[window*2]<y) {
    val left=max(x,w[window*2]);val right=min(y,w[window*2+1]);val duration=right-left
    if(duration>0) {
     val base=window*OUT;out[base]+=1
     for(field in 0..3) {
      var value=Double.NaN;var measured=false;var reset=false
      if(field<2) {
       val av=d[a+field+1];val bv=d[b+field+1]
       if(dt<=gap && av.isFinite() && bv.isFinite())value=trapezoid(av,bv,x,dt,left,right)
      } else {
       val direction=field-2;val av=d[a+5+direction];val bv=d[b+5+direction]
       if(d[a+7+direction]!=0.0 && d[a+7+direction]==d[b+7+direction] && av.isFinite() && bv.isFinite()) {
        if(bv>=av) { value=(bv-av)*duration/dt;measured=duration==dt }
        else {
         val limit=d[a+9+direction]
         if(limit.isFinite() && limit==d[b+9+direction] && bv>=0 && av>bv && av<limit) {
          value=(limit-av+bv)*duration/dt;measured=duration==dt
         } else reset=true
        }
       }
       if(value.isNaN() && dt<=gap) {
        val ap=d[a+3+direction];val bp=d[b+3+direction];val source=d[a+11+direction]
        if(ap.isFinite() && bp.isFinite() && (source==1.0 || source==2.0) && source==d[b+11+direction] && d[a+13+direction]==d[b+13+direction]) {
         value=trapezoid(ap,bp,x,dt,left,right);measured=source==1.0
        }
       }
      }
      val offset=base+1+field*5
      if(reset)out[offset+4]+=1
      if(!value.isNaN()) { out[offset]+=value;out[offset+1]+=duration;if(measured)out[offset+2]+=duration;out[offset+3]+=1 }
     }
    }
    window++
   }
  }
  return out
 }
 private fun trapezoid(a:Double,b:Double,x:Double,dt:Double,left:Double,right:Double):Double {
  val f=(left-x)/dt;val g=(right-x)/dt
  return ((a+(b-a)*f)+(a+(b-a)*g))*.5*(right-left)/3600000
 }
}
