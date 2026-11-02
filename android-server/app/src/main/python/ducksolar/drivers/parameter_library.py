"""PI30 command subset supported by public protocol definitions and DAXTROMN LCD documentation.
No model-name-only matching; observed firmware/rating signature is mandatory.
PCP uses the VMII 0/1/2 overlay; every write requires readback.
Grid-tie setter/range is not established for this firmware.
"""
from decimal import Decimal, InvalidOperation
from ..protocol.pi30 import _encode_packet, decode_packet
SOURCE='mppsolar 0.16.56 PI30 (MIT); DAXTROMN AGH PRO/BMS LCD documentation'
RULES={
 'charging.source_priority':dict(index=18,prefix='PCP',enum={'0':'Спочатку сонце','1':'Сонце та мережа','2':'Лише сонце'},format='02d'),
 'output.source_priority':dict(index=17,prefix='POP',enum={'0':'Utility First','1':'Сонце спочатку / SUB','2':'Сонце → АКБ → мережа / SBU'},format='02d'),
 'grid.input_range':dict(index=16,prefix='PGR',enum={'0':'Appliance / широкий діапазон','1':'UPS / вузький діапазон'},format='02d'),
 'output.rated_frequency':dict(index=4,prefix='F',values=[50,60],format='02d'),
 'battery.type':dict(index=13,prefix='PBT',enum={'0':'AGM','1':'Flooded','2':'User'},format='02d'),
 'charging.bulk_voltage':dict(index=11,prefix='PCVV',minimum=48,maximum=61,step=.1,format='.1f',user_battery=True),
 'charging.float_voltage':dict(index=12,prefix='PBFT',minimum=48,maximum=61,step=.1,format='.1f',user_battery=True),
 'battery.cutoff_voltage':dict(index=10,prefix='PSDV',minimum=40,maximum=48,step=.1,format='.1f',user_battery=True),
 'charging.total_current_limit':dict(index=15,prefix='MCHGC0',minimum=10,maximum=120,step=10,format='02d'),
 'charging.utility_current_limit':dict(index=14,prefix='MUCHGC0',large_prefix='MNCHGC0',values=[2,10,20,30,40,50,60,70,80,90,100,110,120],format='02d'),
 'battery.recharge_voltage':dict(index=9,prefix='PBCV',minimum=44,maximum=51,step=1,format='.1f'),
 'battery.redischarge_voltage':dict(index=23,prefix='PBDV',values=[0,48,49,50,51,52,53,54,55,56,57,58],format='.1f'),
}
FLAG_SETTINGS={
 'settings.buzzer':('a','Звукова сигналізація'),
 'settings.overload_bypass':('b','Bypass при перевантаженні'),
 'settings.power_saving':('j','Економія енергії інвертора'),
 'settings.lcd_return':('k','Повернення на головну LCD'),
 'settings.overload_restart':('u','Перезапуск після перевантаження'),
 'settings.overtemperature_restart':('v','Перезапуск після перегріву'),
 'settings.backlight':('x','Підсвічування LCD'),
 'settings.source_interrupt_alarm':('y','Звук при зміні основного джерела'),
 'settings.fault_record':('z','Запис коду несправності'),
}
for _key,(_letter,_title) in FLAG_SETTINGS.items():
    RULES[_key]=dict(query='QFLAG',flag=_letter,enum={'0':'Вимкнено','1':'Увімкнено'},format='02d')

def flag_values(text):
    import re
    text=str(text).lstrip('(')
    if not re.fullmatch(r'E[A-Za-z]*D[A-Za-z]*',text):raise ValueError('Некоректна відповідь QFLAG')
    enabled,disabled=text[1:].split('D')
    # Reject conflicting/duplicated states rather than guess a flag value.
    if len(set(enabled+disabled))!=len(enabled+disabled):raise ValueError('Суперечливі прапори QFLAG')
    return {key:'1' if letter in enabled else '0' for key,(letter,_) in FLAG_SETTINGS.items() if letter in enabled+disabled}

def current_value(parameter,raw):
    rule=RULES[parameter]
    if rule.get('query')=='QFLAG':
        values=flag_values(raw.get('QFLAG',''))
        if parameter not in values:raise ValueError('Прапор відсутній у контрольному читанні')
        return values[parameter]
    return raw['QPIRI'].split()[rule['index']-1]


def matches(raw):
    fields=str(raw.get('QPIRI','')).split()
    try:return (raw.get('QPI')=='PI30' and raw.get('QMN')=='VMII-NXPW5KW'
        and raw.get('QVFW')=='VERFW:00074.11' and len(fields)>=27
        and Decimal(fields[6])==6200 and Decimal(fields[7])==48)
    except InvalidOperation:return False

def normalized(value):
    if isinstance(value,bool):raise ValueError('Некоректне значення')
    try:v=Decimal(str(value))
    except (InvalidOperation,ValueError):raise ValueError('Потрібне числове значення') from None
    if not v.is_finite():raise ValueError('Потрібне скінченне значення')
    return v

def command(parameter,value):
    if parameter not in RULES:raise ValueError('Команда для цього параметра не підтверджена')
    rule=RULES[parameter];v=normalized(value)
    if 'enum' in rule and str(int(v)) not in rule['enum']:raise ValueError('Непідтримуване значення')
    if 'values' in rule and v not in rule['values']:raise ValueError('Непідтримуване значення')
    if rule['format']=='02d' and v!=int(v):raise ValueError('Потрібне ціле значення')
    if 'minimum' in rule:
        if not Decimal(str(rule['minimum']))<=v<=Decimal(str(rule['maximum'])):raise ValueError('Значення поза діапазоном')
        if (v-Decimal(str(rule['minimum'])))%Decimal(str(rule['step'])):raise ValueError('Неправильний крок значення')
    if rule.get('flag'):return _encode_packet(('PE' if v==1 else 'PD')+rule['flag'])
    if rule.get('large_prefix') and v>=100:return _encode_packet(rule['large_prefix']+format(int(v),'03d'))
    number=int(v) if rule['format']=='02d' else v
    return _encode_packet(rule['prefix']+format(number,rule['format']))

def valid_request(request):
    try:
        name=decode_packet(request).decode('ascii')
        for parameter,rule in RULES.items():
            if rule.get('flag'):
                if request in (command(parameter,0),command(parameter,1)):return True
            elif rule.get('large_prefix') and name.startswith(rule['large_prefix']):
                if command(parameter,name[len(rule['large_prefix']):])==request:return True
            elif name.startswith(rule['prefix']):
                if command(parameter,name[len(rule['prefix']):])==request:return True
    except (ValueError,UnicodeError,InvalidOperation):pass
    return False


def allowed_note(rule):
    if 'enum' in rule:return '; '.join(k+' = '+v for k,v in rule['enum'].items())
    if 'values' in rule:return ', '.join(map(str,rule['values']))
    return f"{rule['minimum']}–{rule['maximum']}; крок {rule['step']}"

def validate_state(parameter,value,raw,mode):
    if not matches(raw):raise ValueError('Модель, firmware або номінали не відповідають підтвердженому профілю')
    if mode not in ('L','B','S','H'):raise ValueError('Стан інвертора не дозволяє зміну')
    command(parameter,value)
    fields=raw['QPIRI'].split();rule=RULES[parameter]
    if rule.get('user_battery') and normalized(fields[12])!=2:
        raise ValueError('Напруги можна змінювати лише для типу батареї User')
    bulk=normalized(fields[10]);floating=normalized(fields[11]);cutoff=normalized(fields[9]);v=normalized(value)
    if parameter=='charging.bulk_voltage':bulk=v
    if parameter=='charging.float_voltage':floating=v
    if parameter=='battery.cutoff_voltage':cutoff=v
    if parameter.startswith(('charging.bulk','charging.float','battery.cutoff')) and not cutoff<floating<=bulk:
        raise ValueError('Потрібно: cutoff < float ≤ bulk')
    if parameter=='charging.utility_current_limit' and v>normalized(fields[14]):
        raise ValueError('Мережевий струм не може перевищувати загальний ліміт заряду')
    if parameter=='charging.total_current_limit' and v<normalized(fields[13]):
        raise ValueError('Спочатку зменште мережевий ліміт заряду')
    return current_value(parameter,raw)
