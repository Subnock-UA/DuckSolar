from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MonthlyFinance:
    import_day_kwh: float
    import_night_kwh: float
    export_day_kwh: float
    export_night_kwh: float
    export_kwh: float
    payable_day_kwh: float
    payable_night_kwh: float
    sale_kwh: float
    import_cost_uah: float
    green_gross_uah: float
    personal_income_tax_uah: float
    military_tax_uah: float
    green_net_uah: float


def calculate_month(
    import_day_kwh: float,
    import_night_kwh: float,
    export_kwh: float,
    day_tariff_uah: float,
    night_factor: float,
    green_tariff_uah: float,
    pit_pct: float,
    military_pct: float,
    export_day_kwh: float | None = None,
    export_night_kwh: float | None = None,
) -> MonthlyFinance:
    day = max(0.0, float(import_day_kwh))
    night = max(0.0, float(import_night_kwh))
    export = max(0.0, float(export_kwh))
    exp_day = export if export_day_kwh is None else max(0.0, float(export_day_kwh))
    exp_night = 0.0 if export_night_kwh is None else max(0.0, float(export_night_kwh))
    if export_day_kwh is not None or export_night_kwh is not None:
        export = exp_day + exp_night

    total_import = day + night
    payable_day = 0.0
    payable_night = 0.0
    sale = 0.0

    if total_import > export:
        remaining = total_import - export
        if total_import > 0:
            payable_day = remaining * day / total_import
            payable_night = remaining * night / total_import
    else:
        sale = export - total_import

    import_cost = (
        payable_day * max(0.0, float(day_tariff_uah))
        + payable_night * max(0.0, float(day_tariff_uah)) * max(0.0, float(night_factor))
    )

    gross = sale * max(0.0, float(green_tariff_uah))
    pit = gross * max(0.0, float(pit_pct)) / 100.0
    military = gross * max(0.0, float(military_pct)) / 100.0
    net = max(0.0, gross - pit - military)

    return MonthlyFinance(
        import_day_kwh=day,
        import_night_kwh=night,
        export_day_kwh=exp_day,
        export_night_kwh=exp_night,
        export_kwh=export,
        payable_day_kwh=payable_day,
        payable_night_kwh=payable_night,
        sale_kwh=sale,
        import_cost_uah=import_cost,
        green_gross_uah=gross,
        personal_income_tax_uah=pit,
        military_tax_uah=military,
        green_net_uah=net,
    )
