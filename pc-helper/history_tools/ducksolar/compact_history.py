"""Versioned appendable CSV, with exact scalar cells and shared metadata.

Blank cells mean the schema default. '~' is an explicit empty override;
literal '~' prefixes are escaped. A partial last row is never published.
"""
import csv
import copy
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4
from .prepared_history import write_json

FORMAT = 'ducksolar.compact-history.v2'
REMOVED = {'bus_v', 'scc_battery_v', 'temperature_c', 'mode', 'Working State',
           'Temperature', 'Inverter Temperature', 'Machine Temperature'}
MARKER = '__c2'
EXTRAS = '__changes'

def schema_path(path):
    return Path(str(path) + '.schema.json')

def kind(value):
    return 'null' if value is None else 'bool' if isinstance(value, bool) else 'int' if isinstance(value, int) else 'float' if isinstance(value, float) else 'str'

def from_cell(text, tag):
    if tag == 'null':
        if text != '': raise ValueError('Not null')
        return None
    if tag == 'bool':
        if text not in ('0', '1', 'False', 'True'): raise ValueError('Not boolean')
        return text in ('1', 'True')
    if tag == 'int':
        from decimal import Decimal, InvalidOperation
        try:v = Decimal(text)
        except InvalidOperation as error:raise ValueError('Not integral') from error
        if not v.is_finite() or v != v.to_integral_value(): raise ValueError('Not integral')
        return int(v)
    if tag == 'float': return float(text)
    return text

def equal(a, b):
    import math
    return kind(a) == kind(b) and a == b and (not isinstance(a,float) or a!=0 or math.copysign(1,a)==math.copysign(1,b))

def prune(value):
    if isinstance(value, dict):
        return {k: prune(v) for k, v in value.items()
                if k not in REMOVED and not any(t in k.lower() for t in ('temperature', 'bus_voltage', 'scc_battery', 'scc_voltage', 'working_state'))
                and k.lower() not in ('mode', 'bus_v')}
    if isinstance(value, list): return [prune(v) for v in value]
    return value

def flatten(value, path=(), leaves=None):
    if leaves is None: leaves = {}
    if isinstance(value, dict): return {k: flatten(v, path+(k,), leaves) for k, v in value.items()}
    if isinstance(value, list): return [flatten(v, path+(i,), leaves) for i, v in enumerate(value)]
    key = json.dumps(path, ensure_ascii=False, separators=(',', ':'))
    leaves[key] = value
    return {'$leaf': key}

def normalized(row):
    value = row.get('normalized_json')
    if not value: return {}
    from .csv_codec import unpack
    return prune(unpack(value))

def reference(value, cells, path=()):
    # Every timestamp can refer to the scalar time without repeating it per metric.
    if isinstance(value, str) and value == cells.get('time', '').replace(' ', 'T', 1):
        return {'time': True}
    if value is not None:
        preferred=None
        if len(path)>=3 and path[0]=='metrics' and path[-1]=='value':
            from .drivers.daxtromn import METRICS
            mapping={metric[0]:metric[1] for metric in METRICS}
            mapping.update({'grid.estimated_import_power':'estimated_grid_import_w','grid.estimated_export_power':'estimated_export_w','pv.corrected_power':'pv_corrected_w','battery.estimated_charge_power':'battery_charge_w','battery.channels.main.soc':'battery_estimated_pct','battery.channels.main.remaining_energy':'battery_remaining_kwh','battery.channels.main.inverter_soc':'battery_inverter_pct'})
            preferred=mapping.get(path[1])
        section=path[0] if path else ''
        last=path[-1] if path else ''
        if preferred is None:
            if section in ('grid','output') and last in ('voltage','frequency'):preferred=section+('_v' if last=='voltage' else '_hz')
            elif section=='output' and last=='active_power':preferred='output_w'
            elif section=='pv':preferred={'voltage':'pv_v','current':'pv_a','total_power':'pv_w'}.get(last)
            elif section=='battery':preferred={'voltage':'battery_v','soc':'battery_estimated_pct','charge_current':'charge_a','discharge_current':'discharge_a'}.get(last)
        candidates=[]
        for name, cell in cells.items():
            if not cell: continue
            try:
                if equal(from_cell(cell, kind(value)), value):candidates.append(name)
            except (ValueError, TypeError, OverflowError): pass
        if preferred in candidates:return {'column':preferred,'kind':kind(value)}
        if len(candidates)==1:return {'column':candidates[0],'kind':kind(value)}
    return {'constant': value}

def leaf_value(spec, cells):
    if 'time' in spec: return cells.get('time', '').replace(' ', 'T', 1)
    if 'column' in spec: return from_cell(cells[spec['column']], spec['kind'])
    return spec['constant']

def render(template, leaves, cells, changes):
    if isinstance(template, dict):
        if set(template) == {'$leaf'}:
            key = template['$leaf']
            return changes[key] if key in changes else leaf_value(leaves[key], cells)
        return {k: render(v, leaves, cells, changes) for k, v in template.items()}
    if isinstance(template, list): return [render(v, leaves, cells, changes) for v in template]
    raise ValueError('Invalid compact template')

def compile_template(template, leaves):
    if isinstance(template,dict):
        if set(template)=={'$leaf'}:
            key=template['$leaf'];spec=leaves[key]
            return lambda cells,changes: changes[key] if key in changes else leaf_value(spec,cells)
        fields=[(key,compile_template(value,leaves)) for key,value in template.items()]
        return lambda cells,changes:{key:fn(cells,changes) for key,fn in fields}
    if isinstance(template,list):
        fields=[compile_template(value,leaves) for value in template]
        return lambda cells,changes:[fn(cells,changes) for fn in fields]
    raise ValueError('Invalid compact template')

class Codec:
    def __init__(self, path, fields=None, meta_path=None):
        self.path = Path(path)
        self.meta = Path(meta_path) if meta_path is not None else schema_path(path)
        if self.meta.exists():
            raw=self.meta.read_bytes();self.schema_sha256=hashlib.sha256(raw).hexdigest();self.schema=json.loads(raw)
            if self.schema.get('format') != FORMAT: raise ValueError('Unsupported compact schema')
        elif fields is not None:
            self.schema = dict(format=FORMAT, fields=[k for k in fields if k not in REMOVED and k != 'normalized_json'],
                               defaults=None, templates={})
        else: raise ValueError('Missing compact schema')
        self.shapes = {json.dumps(v['template'], sort_keys=True, ensure_ascii=False): k
                       for k, v in self.schema['templates'].items()}
        self.decoders={}

    def encode(self, row):
        cells = {k: '' if row.get(k) is None else str(row.get(k, '')) for k in self.schema['fields']}
        previous = copy.deepcopy(self.schema) if self.schema['defaults'] is None else None
        dirty = self.schema['defaults'] is None
        if dirty: self.schema['defaults'] = dict(cells)
        leaves = {}
        template = flatten(normalized(row), leaves=leaves)
        shape = json.dumps(template, sort_keys=True, ensure_ascii=False)
        ident = self.shapes.get(shape)
        if ident is None:
            if previous is None: previous=copy.deepcopy(self.schema)
            ident = str(len(self.shapes)); self.shapes[shape] = ident
            self.schema['templates'][ident] = dict(template=template, leaves={k: reference(v, cells,tuple(json.loads(k))) for k, v in leaves.items()})
            dirty = True
        definition = self.schema['templates'][ident]
        changes = {}
        for k, v in leaves.items():
            try: same = equal(v, leaf_value(definition['leaves'][k], cells))
            except (ValueError, TypeError, KeyError, OverflowError): same = False
            if not same: changes[k] = v
        out = {k: '' if v == self.schema['defaults'][k] else '~'+v if v == '' or v.startswith('~') else v for k, v in cells.items()}
        out[MARKER] = ident
        out[EXTRAS] = json.dumps(changes, ensure_ascii=False, allow_nan=False, separators=(',', ':')) if changes else ''
        # Publish new metadata before a CSV row can refer to it.
        if dirty:
            previous_hash=hashlib.sha256(self.meta.read_bytes()).hexdigest() if self.meta.exists() else None
            if previous_hash and previous.get('defaults') is not None:
                proofs=dict(previous.get('append_only_proofs',{}))
                proofs[previous_hash]=schema_contract(previous)
                self.schema['append_only_proofs']=dict(list(proofs.items())[-64:])
            write_json(self.meta, self.schema)
        return out

    def decode(self, row, grid_only=False):
        cells = {k: self.schema['defaults'][k] if row.get(k, '') == '' else row[k][1:] if row[k].startswith('~') else row[k] for k in self.schema['fields']}
        definition = self.schema['templates'][row[MARKER]]
        changes = json.loads(row.get(EXTRAS) or '{}')
        key=(row[MARKER],bool(grid_only))
        decoder=self.decoders.get(key)
        if decoder is None:
            template=definition['template']
            if grid_only:
                needed={'grid.measured_net_power','grid.measured_import_power','grid.measured_export_power',
                        'grid.estimated_import_power','grid.estimated_export_power','grid.import_energy_total','grid.export_energy_total'}
                template={'grid':{'measurement_context':template.get('grid',{}).get('measurement_context',{})},
                          'metrics':{k:v for k,v in template.get('metrics',{}).items() if k in needed}}
            decoder=compile_template(template,definition['leaves']);self.decoders[key]=decoder
        cells['normalized_json'] = decoder(cells,changes)
        return cells

    def append(self, row):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        output = self.encode(row)
        if self.path.exists():
            # Truncate only an interrupted append, preserving all complete rows.
            with self.path.open('r+b') as f:
                f.seek(0, 2); size = f.tell()
                if size:
                    f.seek(size-1)
                    if f.read(1) != b'\n':
                        pos = size
                        while pos:
                            step = min(pos, 65536); pos -= step; f.seek(pos); block = f.read(step)
                            cut = block.rfind(b'\n')
                            if cut >= 0: f.truncate(pos+cut+1); break
                        else: raise ValueError('Corrupt compact CSV header')
        header = not self.path.exists() or self.path.stat().st_size == 0
        with self.path.open('a', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, self.schema['fields']+[MARKER, EXTRAS], lineterminator='\n')
            if header: writer.writeheader()
            writer.writerow(output); f.flush(); os.fsync(f.fileno())

def convert(source, destination, cancelled=None, source_schema=None):
    """Never edit the source. Verify the committed snapshot row by row."""
    from .energy_streaming import _snapshot_lines
    source, destination = Path(source), Path(destination)
    stat = source.stat()
    tmp = destination.with_name(destination.name+'.'+uuid4().hex+'.tmp')
    destination.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    metadata=Path(source_schema) if source_schema is not None else schema_path(source)
    meta_stat=metadata.stat() if metadata.exists() else None
    old = Codec(source,meta_path=metadata) if meta_stat else None
    try:
        reader = csv.DictReader(_snapshot_lines(source, stat.st_size), strict=True)
        codec = Codec(tmp, old.schema['fields']+['normalized_json'] if old else reader.fieldnames or ['time'])
        with tmp.open('w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, codec.schema['fields']+[MARKER, EXTRAS], lineterminator='\n'); writer.writeheader()
            for raw in reader:
                if cancelled and cancelled(): raise ValueError('Compact conversion cancelled')
                if None in raw or any(v is None for v in raw.values()): raise ValueError('Malformed source CSV')
                row = old.decode(raw) if old else raw
                packed = codec.encode(row); restored = codec.decode(packed)
                for k in codec.schema['fields']:
                    if restored[k] != str(row.get(k, '')): raise ValueError('Compact scalar verification failed: '+k)
                if restored['normalized_json'] != normalized(row): raise ValueError('Compact metadata verification failed')
                writer.writerow(packed); count += 1
            f.flush(); os.fsync(f.fileno())
        after = source.stat()
        if (stat.st_size, stat.st_mtime_ns, stat.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino): raise ValueError('Source changed during conversion')
        if meta_stat:
            current=metadata.stat()
            if (meta_stat.st_size,meta_stat.st_mtime_ns,meta_stat.st_ino)!=(current.st_size,current.st_mtime_ns,current.st_ino):raise ValueError('Source metadata changed during conversion')
        if not codec.meta.exists():
            codec.schema['defaults'] = {k: '' for k in codec.schema['fields']}
            write_json(codec.meta, codec.schema)
        os.replace(codec.meta, schema_path(destination)); os.replace(tmp, destination)
        return dict(rows=count, bytes=destination.stat().st_size+schema_path(destination).stat().st_size, source_bytes=stat.st_size)
    finally:
        tmp.unlink(missing_ok=True); schema_path(tmp).unlink(missing_ok=True)


def schema_contract(schema):
    def h(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    return dict(format=schema.get('format'),fields=schema.get('fields'),defaults=schema.get('defaults'),templates={k:h(v) for k,v in schema.get('templates',{}).items()})


def compatible_schema(schema, previous_hash, previous_contract=None):
    old=previous_contract or schema.get('append_only_proofs',{}).get(previous_hash)
    if not old:return False
    current=schema_contract(schema)
    return all(old.get(k)==current.get(k) for k in ('format','fields','defaults')) and all(current['templates'].get(k)==v for k,v in old.get('templates',{}).items())
