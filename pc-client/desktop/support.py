import json,hashlib,urllib.request,urllib.parse,urllib.error,ipaddress,socket,tempfile,shutil,zipfile,time
from pathlib import Path
def sha256(path):
 with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):raise ValueError('Перенаправлення ПК-служби заборонене')
class Support:
 def __init__(self,url,root,identity=None):
  parts=urllib.parse.urlsplit(url)
  if parts.scheme!='http' or not parts.hostname or parts.username or parts.password or parts.path not in ('','/') or parts.query or parts.fragment:raise ValueError('Задайте LAN HTTP адресу ПК-служби')
  for row in socket.getaddrinfo(parts.hostname,parts.port or 80,type=socket.SOCK_STREAM):
   addr=ipaddress.ip_address(row[4][0])
   if not (addr.is_private or addr.is_loopback):raise ValueError('ПК-служба доступна лише через LAN')
  self.base=url.rstrip('/');self.root=Path(root);self.identity=identity;self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
 def request(self,path,data=None,headers=None):
  req=urllib.request.Request(self.base+path,data=data,headers=headers or {})
  for attempt in range(3):
   try:return self.opener.open(req,timeout=30)
   except urllib.error.HTTPError as error:
    status=error.code;body=error.read(8192);error.close()
    if data is None and status in (429,503) and attempt<2:time.sleep(2);continue
    try:message=json.loads(body).get('error',str(status))
    except (ValueError,UnicodeError):message=str(status)
    raise ValueError('ПК-служба: '+str(message)) from None
 def json(self,path,data=None):
  with self.request(path,data) as reply:
   raw=reply.read(4*1024*1024+1)
   if len(raw)>4*1024*1024:raise ValueError('Завелика відповідь ПК-служби')
   return json.loads(raw)
 def status(self):
  result=self.json('/v1/status')
  if result.get('contract')!='ducksolar.lan-support.v1' or not result.get('helper_id'):raise ValueError('Невідома ПК-служба')
  if self.identity and result['helper_id']!=self.identity:raise ValueError('Ідентичність ПК-служби змінилася; перевірте її перед передаванням даних')
  return result
 def trusted(self):
  if not self.identity:raise ValueError('Спочатку перевірте та підтвердьте ідентичність ПК-служби')
  return self.status()
 def upload_diagnostics(self,installation):
  self.trusted();done=[]
  with tempfile.TemporaryDirectory() as tmp:
   for source in diagnostic_files(self.root):
    snap=Path(tmp)/source.name;shutil.copy2(source,snap);size=snap.stat().st_size
    if not 0<size<=128*1024*1024:continue
    sha=sha256(snap);query=urllib.parse.urlencode(dict(installation=installation,kind='diagnostic',name=source.name,bytes=size,sha256=sha));path='/v1/log/status?'+query;status=self.json(path);offset=status['offset']
    with snap.open('rb') as stream:
     while offset<size and not status.get('complete'):
      if not 0<=offset<=size:raise ValueError('Некоректна позиція відновлення')
      stream.seek(offset);chunk=stream.read(min(256*1024,size-offset));status=self.json('/v1/log/chunk?'+query+'&offset='+str(offset),chunk);next_offset=status['offset']
      if next_offset!=offset+len(chunk):raise ValueError('ПК не підтвердив частину журналу')
      offset=next_offset
    if not self.json(path).get('complete'):raise ValueError('ПК не підтвердив повний журнал')
    done.append(dict(name=source.name,bytes=size,sha256=sha))
  return {'uploaded':done}
 def desktop_manifest(self):
  status=self.trusted()
  if not status.get('desktop_client'):return {'note':'Для оновлень ПК-клієнта потрібна ПК-служба b1.0.5 або новіша'}
  value=self.json('/v1/desktop/manifest')
  if value.get('component')!='desktop_client' or value.get('contract')!='ducksolar.desktop-client.v1':raise ValueError('Некоректний каталог ПК-клієнта')
  import re
  if not re.fullmatch(r'b\d+\.\d+\.\d+',value.get('version','')) or type(value.get('version_code')) is not int or value['version_code']<=0 or not re.fullmatch('[0-9a-f]{64}',value.get('sha256','')) or not 0<value.get('bytes',0)<=512*1024*1024 or value.get('url')!='/v1/desktop/bundle':raise ValueError('Некоректний опис оновлення')
  return value
 def download(self,folder):
  manifest=self.desktop_manifest()
  if 'sha256' not in manifest:raise ValueError(manifest['note'])
  folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);target=folder/('DS_PC_Client_ver.'+manifest['version']+'.zip');temp=target.with_suffix('.zip.part');offset=temp.stat().st_size if temp.exists() else 0
  if offset>manifest['bytes']:raise ValueError('Частковий пакет більший за очікуваний; збережіть у нову папку')
  with temp.open('ab') as out:
   while offset<manifest['bytes']:
    end=min(offset+256*1024,manifest['bytes'])-1
    with self.request(manifest['url'],headers={'Range':f'bytes={offset}-{end}'}) as reply:
     if reply.status!=206 or reply.headers.get('Content-Range')!=f'bytes {offset}-{end}/{manifest["bytes"]}':raise ValueError('Сервер не підтвердив діапазон пакета')
     chunk=reply.read(end-offset+2)
     if len(chunk)!=end-offset+1:raise ValueError('Неповна частина пакета')
     expected=reply.headers.get('X-Chunk-SHA256')
     if expected and hashlib.sha256(chunk).hexdigest()!=expected:raise ValueError('Контрольна сума частини не збігається')
     out.write(chunk);offset+=len(chunk)
  if sha256(temp)!=manifest['sha256']:raise ValueError('Пакет змінився; частковий файл збережений для діагностики')
  temp.replace(target);return dict(path=str(target),version=manifest['version'],note='SHA256 перевірено. Розпакуйте пакет, закрийте клієнт і запустіть Install.cmd. Дані зберігаються окремо.')
def diagnostic_files(root):
 root=Path(root)
 return [p for name in ('client-events.jsonl','client-events.1.jsonl','desktop.log','desktop.log.1','notifications-history.jsonl') if (p:=root/name).is_file()]
def export_diagnostics(root,destination):
 with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as archive:
  for path in diagnostic_files(root):archive.write(path,path.name)
 return str(destination)
