"""Small audit records; public audit pages retain the existing object contract."""
FIELDS=('timestamp','pv_w','grid_import_w','grid_export_w','grid_import_source',
 'grid_export_source','grid_import_origin','grid_export_origin','grid_import_reason',
 'grid_export_reason','grid_import_energy_total_kwh','grid_export_energy_total_kwh',
 'grid_import_counter_id','grid_export_counter_id','grid_import_counter_modulus_kwh',
 'grid_export_counter_modulus_kwh')

class InputEncoder:
    """Same i1 ledger bytes, without repeated imports, wrappers and field scans."""
    def __init__(self):
        import json
        self.encoder=json.JSONEncoder(ensure_ascii=False,sort_keys=True,allow_nan=False,separators=(',',':'),default=lambda x:x.isoformat())
        self.contracts={}
    def encode(self,row):
        keys=frozenset(row)
        contract=self.contracts.get(keys)
        if contract is None:
            selected=tuple((i,k) for i,k in enumerate(FIELDS) if k in row)
            contract=(sum(1<<i for i,k in selected),tuple(k for i,k in selected))
            if len(self.contracts)<64:self.contracts[keys]=contract
        mask,fields=contract
        return (self.encoder.encode(['i1',mask,*[row[k] for k in fields]])+'\n').encode('utf-8')

def compact(record):
    kind=record.get('type')
    if kind=='input':
        row=record['row']
        # Presence is separate from null, for old audits and exact API roundtrips.
        mask=sum(1<<i for i,k in enumerate(FIELDS) if k in row)
        return ['i1',mask,*[row[k] for k in FIELDS if k in row]]
    if kind=='interval':
        return ['e1',record['direction'],[[x['start'],x['end'],x['kwh'],x['source'],x['reason']] for x in record['intervals']],record['resets'],record.get('duration_s')]
    return record

def expand(record):
    if isinstance(record,dict):return record
    if record[0]=='i1':
        values=iter(record[2:]);return dict(type='input',row={k:next(values) for i,k in enumerate(FIELDS) if record[1]&(1<<i)})
    if record[0]=='e1':
        out=dict(type='interval',direction=record[1],intervals=[dict(zip(('start','end','kwh','source','reason'),x)) for x in record[2]],resets=record[3])
        if record[4] is not None:out['duration_s']=record[4]
        return out
    raise ValueError('Unsupported audit record')
