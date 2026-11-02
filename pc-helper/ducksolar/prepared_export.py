"""Read-only prepared package transport; published metadata fixes its checksum."""
import hashlib,json,re
from pathlib import Path
def catalog(root):
    folder=Path(root)/'Data/AndroidSupport/PreparedHistory';items=[]
    for metadata in sorted(folder.glob('*.metadata.json')):
        row=json.loads(metadata.read_text(encoding='utf-8'))
        path=Path(row['path']).resolve()
        if not path.is_relative_to(folder.resolve()) or path.is_symlink() or not path.is_file():continue
        if row.get('contract')!='ducksolar.prepared-history.v1' or not re.fullmatch('[0-9a-f]{64}',row.get('sha256','')):continue
        if path.stat().st_size!=row['bytes']:continue
        items.append({k:row[k] for k in ('contract','sha256','bytes','files','model','device_id')})
    return {'contract':'ducksolar.prepared-history.v1','packages':items}
def chunk(root,sha,offset,length):
    if not re.fullmatch('[0-9a-f]{64}',sha) or offset<0 or not 1<=length<=256*1024:raise ValueError('Invalid prepared chunk')
    folder=Path(root)/'Data/AndroidSupport/PreparedHistory'
    for metadata in folder.glob('*.metadata.json'):
        row=json.loads(metadata.read_text(encoding='utf-8'))
        if row.get('sha256')!=sha:continue
        path=Path(row['path']).resolve()
        if not path.is_relative_to(folder.resolve()) or path.is_symlink():raise ValueError('Invalid prepared path')
        if offset+length>row['bytes'] or path.stat().st_size!=row['bytes']:raise ValueError('Prepared package changed')
        with path.open('rb') as f:f.seek(offset);return f.read(length)
    raise ValueError('Prepared package unavailable')
