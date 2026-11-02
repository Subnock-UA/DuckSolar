import dataclasses
from datetime import date, datetime
from pathlib import Path


def encode(value):
    if isinstance(value, datetime): return {'$datetime': value.isoformat()}
    if isinstance(value, date): return {'$date': value.isoformat()}
    if isinstance(value, Path): return str(value)
    if dataclasses.is_dataclass(value): return encode(dataclasses.asdict(value))
    if isinstance(value, dict): return {str(k): encode(v) for k,v in value.items()}
    if isinstance(value, (list, tuple)): return [encode(v) for v in value]
    return value


def decode(value):
    if isinstance(value, dict):
        if set(value) == {'$datetime'}: return datetime.fromisoformat(value['$datetime'])
        if set(value) == {'$date'}: return date.fromisoformat(value['$date'])
        return {k: decode(v) for k,v in value.items()}
    if isinstance(value, list): return [decode(v) for v in value]
    return value
