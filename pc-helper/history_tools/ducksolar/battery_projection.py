"""Separate estimated battery energy from untrusted inverter SOC, including history."""
DEFINITIONS=[('battery.channels.main.soc','Розрахунковий заряд АКБ','%'),('battery.channels.main.remaining_energy','Розрахунковий залишок енергії АКБ','кВт·год'),('battery.channels.main.inverter_soc','SOC інвертора — недостовірний','%')]
def apply(state,battery):
 data=state.setdefault('data',{});metrics=state.setdefault('normalized',{}).setdefault('metrics',{})
 estimate=battery.get('estimate',{});soc=battery.get('values',{}).get('soc');remaining=estimate.get('remaining_kwh')
 data.update(battery_estimated_pct=soc,battery_remaining_kwh=remaining,battery_inverter_pct=data.get('battery_pct'),battery_estimate_confidence=estimate.get('confidence','unavailable'))
 for key,label,unit in DEFINITIONS:
  raw=key.endswith('.inverter_soc');energy=key.endswith('.remaining_energy')
  value=data.get('battery_pct') if raw else remaining if energy else soc
  source='inverter_untrusted' if raw else battery.get('origins',{}).get('soc','energy_ledger')
  metrics[key]={**metrics.get(key,{}),'value':value,'unit':unit,'quality':'good' if value is not None else 'unavailable','source':source,'confidence':'untrusted' if raw else estimate.get('confidence','unavailable'),'timestamp':state.get('updated'),'note':'Показник інвертора збережено для діагностики; не використовується для оцінки залишку' if raw else estimate.get('note','')}
 for channel in state['normalized'].get('battery',{}).get('channels',[]):
  if channel.get('id')=='main':channel.update(soc=soc,remaining_kwh=remaining,inverter_soc=data.get('battery_pct'))
 state['battery']=battery
 return state

def descriptor(value):
 definitions=value.setdefault('metric_definitions',[]);keys={x['canonical_id'] for x in definitions}
 labels={key:(label,unit) for key,label,unit in DEFINITIONS}
 for row in definitions:
  if row['canonical_id'] in labels:row['ui_name'],row['unit']=labels[row['canonical_id']]
 for key,label,unit in DEFINITIONS:
  if key not in keys:definitions.append(dict(canonical_id=key,ui_name=label,unit=unit))
  if key not in value.setdefault('available_metrics',[]):value['available_metrics'].append(key)
 return value
