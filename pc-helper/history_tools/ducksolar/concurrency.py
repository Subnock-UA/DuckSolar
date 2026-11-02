"""Adaptive heavy-task admission and cancellable locks for individual caches."""
import os,threading,time
from contextlib import contextmanager
from pathlib import Path
CPU_WORKERS=max(2,os.cpu_count() or 2)
TASK_BYTES=128*1024*1024
_condition=threading.Condition();_active={};_waiting=[];_serial=0
_keys={};_key_guard=threading.Lock();_local=threading.local()

def active_count():
 with _condition:return len(_active)

def snapshot():
 from .resource_manager import budget
 with _condition:return dict(worker_limit=CPU_WORKERS,memory_slots=max(1,budget()//TASK_BYTES),active=len(_active),waiting=len(_waiting),tasks=[x for x in _active.values()])

@contextmanager
def heavy_slot(name,cancelled=lambda:False,priority=0):
 global _serial
 if getattr(_local,'depth',0):
  if cancelled():raise ValueError('Паралельне завдання скасовано')
  _local.depth+=1
  try:yield
  finally:_local.depth-=1
  return
 from .resource_manager import budget,STATE,_state_lock
 with _condition:
  _serial+=1;ticket=(priority,_serial);_waiting.append(ticket)
 try:
  while True:
   # Cancellation callbacks may acquire job/cache locks. Never call them while
   # holding admission's condition, to avoid reversing those lock orders.
   if cancelled():raise ValueError('Паралельне завдання скасовано')
   available=budget()
   with _state_lock:low=STATE.get('low',False)
   slots=min(CPU_WORKERS,max(1,available//TASK_BYTES))
   if name.startswith('forecast.'):slots=max(1,slots-1)
   with _condition:
    if not low and available>=64*1024*1024 and len(_active)<slots and ticket==min(_waiting):
     _waiting.remove(ticket);_active[ticket]=dict(name=name,thread=threading.current_thread().name,priority=priority);break
    _condition.wait(.1)
 except BaseException:
  with _condition:_waiting.remove(ticket);_condition.notify_all()
  raise
 _local.depth=1;_local.priority=priority;_local.name=name
 try:yield
 finally:
  _local.depth=0
  with _condition:_active.pop(ticket,None);_condition.notify_all()

@contextmanager
def keyed_lock(key,cancelled=None):
 # Waiting holders count as references, so a lock cannot be replaced mid-wait.
 with _key_guard:
  row=_keys.setdefault(key,[threading.RLock(),0]);row[1]+=1
 acquired=False
 try:
  while not acquired:
   if cancelled and cancelled():raise ValueError('Очікування кешу скасовано')
   acquired=row[0].acquire(timeout=.1)
  yield
 finally:
  if acquired:row[0].release()
  with _key_guard:
   row[1]-=1
   if not row[1]:_keys.pop(key,None)

def path_key(kind,path):return kind,os.path.normcase(str(Path(path).resolve()))


def yield_background(cancelled=lambda:False):
 # Yield between rows so existing background tasks do not monopolize the GIL
 # and shared projection locks while a foreground job is waiting/running.
 if not getattr(_local,'name','').startswith('forecast.'):return
 while True:
  if cancelled():raise ValueError('Фонове завдання скасовано')
  with _condition:
   interactive=any(x['name'].startswith('history.') for x in _active.values())
   if not interactive:return
   _condition.wait(.05)


def wait_interactive(cancelled=lambda:False):
 while True:
  if cancelled():raise ValueError('Фонове завдання скасовано')
  with _condition:
   if not any(x['name'].startswith('history.') for x in _active.values()) and not any(p<=0 for p,_ in _waiting):return
   _condition.wait(.05)
