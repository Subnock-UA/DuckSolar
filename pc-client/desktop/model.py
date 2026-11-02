import math,re,copy
from datetime import datetime
from zoneinfo import ZoneInfo
ZONE=ZoneInfo('Europe/Kyiv')
GROUPS={'pv':'Сонячні панелі','grid':'Мережа','output':'Навантаження','battery':'Акумулятор','inverter':'Інвертор','other':'Інші показники'}
FIELDS={'pv_w':'Генерація PV','output_w':'Споживання','battery_v':'Напруга АКБ','battery_pct':'SOC інвертора','charge_a':'Струм заряду','discharge_a':'Струм розряду','grid_v':'Напруга мережі','grid_hz':'Частота мережі','grid_import_w':'Імпорт','grid_export_w':'Експорт','pv_v':'Напруга PV','pv_a':'Струм PV','output_va':'Повна потужність','output_pf':'Коефіцієнт потужності PF','output_v':'Вихідна напруга','output_hz':'Вихідна частота','load_pct':'Навантаження, %','temperature_c':'Температура','battery_charge_w':'Потужність заряду'}
PRESETS={'PV і навантаження':['pv_w','output_w'],'АКБ':['battery_v','charge_a','discharge_a'],'Мережа':['grid_v','grid_hz'],'Імпорт і експорт':['grid_import_w','grid_export_w'],'PV':['pv_w','pv_v','pv_a'],'Вихід':['output_w','output_va','output_pf','output_v','output_hz','load_pct'],'Напруги':['pv_v','battery_v','grid_v','output_v'],'Усі потоки':['pv_w','output_w','grid_import_w','grid_export_w']}
LABELS={'generation':'Генерація','consumption':'Споживання','export':'Експорт','import':'Імпорт','balance':'Сальдо','kwh':'кВт·год','coverage_seconds':'Покриття, с','duration_seconds':'Тривалість, с','start':'Початок','end':'Кінець','source':'Джерело','note':'Примітка','status':'Стан','partial':'Неповні дані','estimate':'Оцінка','values':'Показники','soc':'SOC БМС, %','remaining_kwh':'Залишок, кВт·год','available_kwh':'Понад резерв, кВт·год','current_hours':'За поточним навантаженням, год','average_hours':'За середнім навантаженням, год','curve_hours':'За кривою навантаження, год','confidence':'Достовірність','anchor_at':'Опорна точка','anchor_source':'Джерело опори','charged_kwh':'Заряджено, кВт·год','discharged_kwh':'Витрачено, кВт·год','gap_s':'Пропуски, с','kind':'Розділ','day':'Дата','date':'Дата','time':'Час','message':'Повідомлення','actual_kwh':'Факт, кВт·год','forecast_kwh':'Прогноз, кВт·год','error_kwh':'Відхилення, кВт·год','error_pct':'Відхилення, %','solar_coverage_pct':'Сонячне покриття, %','expected_total_kwh':'Оперативний підсумок, кВт·год','original_kwh':'Початковий прогноз, кВт·год','weather_updated':'Оновлено погоду','recommended_a':'Рекомендований струм, А','current_cap_a':'Граничний струм, А','target_kwh':'Ціль, кВт·год','target_pct':'Ціль, %','needed_kwh':'Необхідно зарядити, кВт·год','pv_low_kwh':'Нижній прогноз PV, кВт·год','day_load_kwh':'Денне споживання, кВт·год','night_load_kwh':'Нічне споживання, кВт·год','fallback':'Причина фіксованого розкладу','available':'Доступний','can_reach_target':'Можливо досягти цілі','history_days':'Діб історії','mean':'Середнє','mae_kwh':'Середня абсолютна похибка, кВт·год','mae_pct':'Середня похибка, %','bias_kwh':'Систематичне відхилення, кВт·год','samples':'Придатних діб','horizon':'Горизонт, днів','input_count':'Записів','import_day_kwh':'Імпорт день, кВт·год','import_night_kwh':'Імпорт ніч, кВт·год','export_day_kwh':'Експорт день, кВт·год','export_night_kwh':'Експорт ніч, кВт·год','net_kwh':'Сальдо, кВт·год','saldo_kwh':'Сальдо, кВт·год','import_cost_uah':'Вартість імпорту, грн','export_income_uah':'Дохід експорту, грн','net_uah':'Сальдо, грн','sale_kwh':'До продажу, кВт·год','uah_per_kwh':'грн/кВт·год','effective_from':'Чинний з','period_start':'Початок обліку','period_end':'Кінець обліку','interim':'Проміжний результат','boundary_adjusted':'Межі скориговані за показниками','cache_hit':'Готовий кеш','incremental':'Додано нові записи','created':'Створено','updated':'Оновлено','old':'Було','new':'Стало','parameter':'Параметр','error':'Помилка','raw_value':'Початкове значення','quality':'Якість','unit':'Одиниця','min_soc':'Мінімальний заряд, %','max_load':'Максимальне навантаження, Вт'}
LABELS.update(known_hours='Підтверджений час',sunshine_h='Сонячний час',duration_s='Тривалість',elapsed_s='Час виконання',age_s='Вік даних',uptime_s='Час роботи',manual_priority_remaining_s='Ручний пріоритет')
UNITS={'W':'Вт','V':'В','A':'А','Hz':'Гц','VA':'ВА','C':'°C','kWh':'кВт·год'}
def clean(value):
 text=str(value);text=re.sub(r'\s*\((?:НП|розрах\.)\)','',text);text=re.sub(r'(?<!\w)НП(?!\w)','',text)
 return text.strip()
def number(value):return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)
def valid(metric,stale=False):
 if not isinstance(metric,dict) or stale or metric.get('stale',False) or metric.get('quality','good') not in ('good','estimated') or metric.get('value') is None:return False
 value=metric['value']
 if isinstance(value,(int,float)) and not isinstance(value,bool) and not number(value):return False
 age=metric.get('age_s',0);ttl=metric.get('valid_for_s',math.inf)
 age=age if number(age) else 0;ttl=ttl if number(ttl) else math.inf
 return age<=ttl
def display(value,unit=''):
 from .duration_text import format_unit
 duration=format_unit(value,unit)
 if duration is not None:return duration
 if value is None:return '—'
 if isinstance(value,bool):return 'Так' if value else 'Ні'
 if isinstance(value,(int,float)):return (f'{value:,.2f}'.replace(',',' ').rstrip('0').rstrip('.') if math.isfinite(value) else '—')+(' '+UNITS.get(unit,unit) if unit else '')
 if isinstance(value,dict) and set(value) in ({'$date'},{'$datetime'}):return next(iter(value.values()))
 return {'verified':'Підтверджено читанням','queued':'У черзі','writing':'Запис','verifying':'Контрольне читання','running':'Виконується','completed':'Завершено','complete':'Завершено','error':'Помилка','cancelled':'Скасовано','estimated':'Розрахункова','uncertain':'Знижена через пропуски','unknown':'Невідомо','automatic_full_charge':'Автоматичний повний заряд','manual':'Ручна опора'}.get(str(value),clean(value) or '—')
def field_display(key,value):
 from .duration_text import field_unit
 return display(value,field_unit(key) or '')

def field_label(key):
 from .duration_text import field_unit
 label=LABELS.get(key,FIELDS.get(key,key))
 if field_unit(key):label=re.sub(r', (?:год|хв|с|мс)$','',label)
 return label

def home_metric_text(metric,stale=False):
 if not valid(metric,stale):return '—'
 value=metric.get('value');unit=metric.get('unit')
 if number(value) and unit in ('W','VA'):
  kilo=abs(value)>=1000
  return display(value/1000 if kilo else value,('кВт' if kilo else 'Вт') if unit=='W' else ('кВА' if kilo else 'ВА'))
 return metric_text(metric,stale)

def metric_text(metric,stale=False):return display(metric.get('value'),metric.get('unit','')) if valid(metric,stale) else '—'
def group(key):return key.split('.')[0] if key.split('.')[0] in ('pv','grid','output','battery') else 'inverter' if key.startswith(('temperature.','dc.','inverter.')) else 'other'
def with_currents(metrics):
 result=copy.deepcopy(metrics or {})
 def n(key,unit=None):
  m=result.get(key,{})
  return m['value'] if valid(m) and number(m.get('value')) and m['value']>=0 and (unit is None or m.get('unit')==unit) else None
 def derived(key,value,source,unit='A'):result[key]=dict(value=value,unit=unit,quality='estimated',confidence='estimated',source=source,stale=False)
 if n('output.phases.L1.current') is None and not any(k.startswith(('output.phases.L2.','output.phases.L3.')) for k in result):
  u=n('output.phases.L1.voltage');s=n('output.apparent_power');w=n('output.active_power');power=s if s is not None and (w is None or s>=w) else w
  if u and power is not None:derived('output.phases.L1.current',power/u,'desktop.S/U' if power==s else 'desktop.P/U;cosφ=1')
 if n('pv.inputs.aggregate.current','A') is None and not any(k.startswith('pv.mppts.') or k.startswith('pv.inputs.') and not k.startswith('pv.inputs.aggregate.') for k in result):
  u=n('pv.inputs.aggregate.voltage','V');w=n('pv.total_power','W')
  if u and w is not None:derived('pv.inputs.aggregate.current',w/u,'desktop.PV_P/U')
 for direction in ('charge','discharge'):
  key='battery.'+direction+'_power';u=n('battery.channels.main.voltage');a=n('battery.channels.main.'+direction+'_current')
  if n(key) is None and u is not None and a is not None:derived(key,u*a,'desktop.U*I','W')
 return result
def graph_energy(result):
 totals=result.get('energy_summary') or {};parts=[]
 for key,title in [('generation','Генерація'),('consumption','Споживання'),('export','Експорт'),('import','Імпорт'),('balance','Сальдо')]:parts.append(title+': '+display((totals.get(key) or {}).get('kwh'),'кВт·год'))
 if any((totals.get(k) or {}).get('partial',True) for k in ('generation','consumption','export','import')):parts.append('Неповне покриття; пропуски не є нулями')
 return '    ·    '.join(parts)
def validate_parameter(row,value):
 rule=row.get('write_rule') or {};value=str(value).strip().replace(',','.')
 if not row.get('writable') or not row.get('present'):raise ValueError('Параметр не доступний для запису')
 if rule.get('enum') and value not in rule['enum']:raise ValueError('Виберіть дозволене значення')
 if rule.get('values') and value not in [str(x) for x in rule['values']]:raise ValueError('Значення не входить до дозволеного переліку')
 if not rule.get('enum'):
  n=float(value)
  if not math.isfinite(n) or 'minimum' in rule and not rule['minimum']<=n<=rule.get('maximum',math.inf):raise ValueError('Значення поза допустимим діапазоном')
 return value
