"""Verified, relocatable open-month checkpoint; new rows use normal resume guards."""
import copy
import hashlib
import json
import shutil
from pathlib import Path
from .prepared_history import write_json, digest

CONTRACT = 'ducksolar.open-month-checkpoint.v1'


def export(summary, history, destination, stem):
    value = json.loads(summary.read_text(encoding='utf-8'))
    if not value.get('deferred_audit') or not value['checkpoint'].get('last_row'):
        return []
    from .energy_streaming import _audit_valid
    if not _audit_valid(value, summary.with_suffix('.audit.jsonl')):
        raise ValueError('Invalid open month checkpoint')
    paths = {}
    for entry in value['checkpoint']['prefixes']:
        path = Path(entry['path'])
        relative = path.resolve().relative_to(history.resolve()).as_posix()
        if path.stat().st_size != entry['size'] or digest(path) != entry['digest']:
            raise ValueError('Checkpoint input changed')
        paths[entry['path']] = 'history/'+relative
    destination.mkdir(parents=True, exist_ok=True)
    members = []
    for index, item in enumerate(value['input_parts']):
        name = stem+'-'+str(index)+'.inputs.jsonl'
        target = destination/name
        shutil.copyfile(item['path'], target)
        item['path'] = 'seeds/'+name
        members.append((target, item['path']))
    envelope = dict(contract=CONTRACT, paths=paths, summary=value)
    target = destination/(stem+'.checkpoint.json')
    write_json(target, envelope)
    members.append((target, 'seeds/'+target.name))
    return members


def install(root, package, manifest, device_id):
    """Package member hashes were verified by migration.activate before this call."""
    from .energy_streaming import _json, _audit_valid
    from .deferred_audit import part
    members = {row['name']: row for row in manifest['files']}
    target = Path(root)/'Data/EnergyAudit'/device_id
    target.mkdir(parents=True, exist_ok=True)
    count = 0
    for name in members:
        if not name.startswith('seeds/') or not name.endswith('.checkpoint.json'):
            continue
        envelope = json.loads((package/name).read_text(encoding='utf-8'))
        if envelope['contract'] != CONTRACT:
            raise ValueError('Unsupported open month checkpoint')
        value = copy.deepcopy(envelope['summary'])
        mapping = {}
        for original, relative in envelope['paths'].items():
            if relative not in members or not relative.startswith('history/'):
                raise ValueError('Unknown checkpoint source')
            path = package/relative
            path.resolve().relative_to((package/'history').resolve())
            mapping[original] = path
        state = value['checkpoint']
        signature = state['signature']
        if signature['device_id'] != device_id:
            raise ValueError('Checkpoint device mismatch')
        for entry in state['prefixes']:
            path = mapping[entry['path']]
            if path.stat().st_size != entry['size'] or members[path.relative_to(package).as_posix()]['sha256'] != entry['digest']:
                raise ValueError('Checkpoint prefix mismatch')
            entry.update(path=str(path), mtime=path.stat().st_mtime_ns)
        signature['files'] = [(str(mapping[path]), origin, day, size, mapping[path].stat().st_mtime_ns)
                              for path, origin, day, size, mtime in signature['files']]
        signature['schemas'] = [(str(mapping[path]), sha) for path, sha in signature.get('schemas', [])]
        signature['schema_contracts'] = {str(mapping[path]): row for path, row in signature.get('schema_contracts', {}).items()}
        if any(item['path'] not in members or not item['path'].startswith('seeds/') for item in value['input_parts']):
            raise ValueError('Missing checkpoint segment')
        value['input_parts'] = [part(package/item['path'], item['start'], item['end'])
                                for item in value['input_parts']]
        value['signature'] = hashlib.sha256(_json(signature).encode()).hexdigest()
        value['audit_metadata'].update(signature)
        value['audit_metadata']['source_signature'] = value['signature']
        value['created_at'] = 0  # First request must validate new rows and meters.
        if not _audit_valid(value, target/'unused.audit.jsonl'):
            raise ValueError('Relocated checkpoint invalid')
        stem = Path(name).name.removesuffix('.checkpoint.json')
        write_json(target/(stem+'.summary.json'), value)
        count += 1
    return count
