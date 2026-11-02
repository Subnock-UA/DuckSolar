"""Server-owned monthly settlement. Client receives presentation DTOs only."""
from dataclasses import asdict
from .finance import calculate_month


class FinanceService:
    def __init__(self, storage, cfg):
        self.storage = storage
        self.cfg = cfg

    def month(self, year, month, now=None):
        delta = self.storage.meter_month_delta(year, month, now=now)
        if not delta:
            return None
        effective = f'{year:04d}-{month:02d}-01'
        tariff = self.storage.tariff_for_date(effective)
        rates = self.storage.finance_rates_for_date(effective) or {
            'retail_effective_from': '—', 'tax_effective_from': '—',
            'retail_day_tariff_uah': self.cfg.retail_day_tariff_uah,
            'retail_night_factor': self.cfg.retail_night_factor,
            'pit_pct': self.cfg.personal_income_tax_pct,
            'military_pct': self.cfg.military_tax_pct, 'source': 'config',
        }
        result = calculate_month(delta['import_day'], delta['import_night'],
            delta['export_day'] + delta['export_night'], rates['retail_day_tariff_uah'],
            rates['retail_night_factor'], float(tariff['uah_per_kwh']) if tariff else 0.0,
            rates['pit_pct'], rates['military_pct'], export_day_kwh=delta['export_day'],
            export_night_kwh=delta['export_night'])
        return dict(year=year, month=month, delta=delta, finance=asdict(result), tariff=tariff, rates=rates)

    def history(self, limit=36):
        return [self.month(year, month) for year, month, _ in self.storage.available_finance_months(limit)]

    def view(self, year, month):
        return {'selected': self.month(year, month), 'history': self.history()}
