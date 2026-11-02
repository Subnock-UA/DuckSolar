from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MeterValues:
    import_day: float
    import_night: float
    export_day: float
    export_night: float = 0.0


def validate_monotonic(previous: MeterValues, new: MeterValues) -> None:
    pairs = [
        ("Споживання день", previous.import_day, new.import_day),
        ("Споживання ніч", previous.import_night, new.import_night),
        ("Генерація день", previous.export_day, new.export_day),
        ("Генерація ніч", previous.export_night, new.export_night),
    ]
    bad = [name for name, old, cur in pairs if cur < old]
    if bad:
        raise ValueError(
            "Показник лічильника не може зменшуватися. "
            "Використайте процедуру «Заміна лічильника». "
            "Проблемні поля: " + ", ".join(bad)
        )
