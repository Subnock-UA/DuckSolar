"""Self-contained normalized metadata: lossless and append-backup compatible."""
import base64,json,zlib
def pack(value):
 if not value:return value
 raw=value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,allow_nan=False)
 # CSV quoting amplifies the JSON keys; compression removes their repetition.
 payload=base64.b64encode(zlib.compress(raw.encode('utf-8'),3)).decode('ascii')
 obj=json.loads(raw)
 wrapper={'$ds_normalized':1,'zlib':payload}
 # Desktop 0.3.4 reads grid provenance directly from these legacy keys.
 if isinstance(obj,dict):
  wrapper['metrics']={k:v for k,v in obj.get('metrics',{}).items() if k.startswith('grid.')}
  if 'grid' in obj:wrapper['grid']=obj['grid']
 packed=json.dumps(wrapper,ensure_ascii=False,separators=(',',':'))
 return packed if len(packed)<len(raw) else raw
class MetadataCodecError(RuntimeError):pass

def unpack(value):
 obj=value if isinstance(value,dict) else json.loads(value or '{}')
 if isinstance(obj,dict) and '$ds_normalized' in obj:
  wrapper=obj
  try:
   if obj.get('$ds_normalized')!=1 or not {'$ds_normalized','zlib'}<=set(obj) or set(obj)-{'$ds_normalized','zlib','metrics','grid'}:raise ValueError('Unsupported metadata codec')
   raw=base64.b64decode(obj['zlib'],validate=True);decoder=zlib.decompressobj()
   # Validation ceiling for a single metadata record, not a working RAM budget.
   decoded=decoder.decompress(raw,8*1024*1024+1)
   if len(decoded)>8*1024*1024 or decoder.unconsumed_tail or decoder.unused_data or not decoder.eof:raise ValueError('Invalid compressed metadata')
   obj=json.loads(decoded.decode('utf-8'))
   if 'metrics' in wrapper and wrapper['metrics']!={k:v for k,v in obj.get('metrics',{}).items() if k.startswith('grid.')}:raise ValueError('Mismatched grid metadata')
   if 'grid' in wrapper and wrapper['grid']!=obj.get('grid'):raise ValueError('Mismatched grid metadata')
  except (ValueError,TypeError,KeyError,zlib.error) as exc:raise MetadataCodecError("Corrupt compressed history metadata") from exc
 return obj
