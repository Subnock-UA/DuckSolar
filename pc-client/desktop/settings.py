from pathlib import Path
import json,os,shutil,sys,uuid
from ducksolar.credential_store import protect,unprotect

def atomic(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 temp=path.with_name('.'+path.name+'.'+uuid.uuid4().hex+'.tmp')
 try:temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8');os.replace(temp,path)
 finally:temp.unlink(missing_ok=True)
def load_connection(root,defaults):
 path=Path(root)/'connection.json'
 if not path.exists():return dict(defaults)
 value=json.loads(path.read_text(encoding='utf-8-sig'))
 if not isinstance(value,dict):raise ValueError('Некоректний профіль підключення')
 token=value.get('token','')
 if os.name=='nt' and token and not token.startswith('dpapi:'):raise ValueError('Незахищений профіль: повторіть вхід для збереження під DPAPI')
 value['token']=unprotect(token);return {**defaults,**value}
def save_connection(root,value):
 safe=dict(value);safe['token']=protect(value.get('token',''));safe.pop('password',None)
 atomic(Path(root)/'connection.json',safe)
def default_root():
 return Path(os.environ.get('DUCK_SOLAR_B2_CLIENT_DATA',str(Path(os.environ.get('LOCALAPPDATA',Path.home()))/'DuckSolarB2/PCClient')))
def migrate_legacy(root,source=None):
 root=Path(root)
 if (root/'connection.json').exists():return False
 candidates=[Path(source)] if source else []
 for candidate in candidates:
  marker=candidate.parent/'.ds-install.json'
  if marker.is_file():
   metadata=json.loads(marker.read_text(encoding='utf-8-sig'))
   if metadata.get('data_dir'):candidate=Path(metadata['data_dir'])
  path=candidate/'config.json' if candidate.is_dir() else candidate
  if not path.is_file():continue
  old=json.loads(path.read_text(encoding='utf-8-sig'));root.mkdir(parents=True,exist_ok=True)
  # Preserve a read-only copy of the old protected profile, never modify originals.
  backup=root/'Legacy-0.3.4-config.json'
  if not backup.exists():shutil.copy2(path,backup)
  url=old.get('server_url','');pin=old.get('server_fingerprint','');username=old.get('account_username','')
  token=unprotect(old.get('auth_token',''))
  value=dict(client_id=old.get('client_id') or uuid.uuid4().hex,lan=url if old.get('connection_mode')=='lan' else '',remote=url if old.get('connection_mode')!='lan' else '',pin=pin,username=username,token=token,serial=old.get('dtu_pn',''))
  save_connection(root,value);atomic(root/'migration.json',dict(source=str(path),original_preserved=True));return True
 return False
