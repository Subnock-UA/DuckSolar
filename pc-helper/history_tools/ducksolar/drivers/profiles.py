"""Daxtromn/EyBond profiles are data, independently extensible from protocol I/O."""
from decimal import Decimal, InvalidOperation

CURRENT_PROFILE='daxtromn.vmii-nxpw5kw.00074.11'

def current_profile(raw):
    fields=str(raw.get('QPIRI','')).lstrip('(').split()
    try:
        return (raw.get('QPI')=='PI30' and raw.get('QMN')=='VMII-NXPW5KW'
            and raw.get('QVFW')=='VERFW:00074.11' and len(fields)>=28
            and Decimal(fields[6])==6200 and Decimal(fields[7])==48)
    except (InvalidOperation,IndexError):return False

EXTRA_FIELDS=[
 ('pv.ok_condition','Умова роботи PV',''),
 ('pv.power_balance','Баланс потужності PV',''),
 ('battery.offgrid_cutoff_voltage','Додатковий поріг QPIRI 26','V'),
 ('battery.bms_protocol_index','Додатковий параметр QPIRI 27',''),
 ('battery.low_warning_voltage','Додатковий поріг QPIRI 28','V'),
]
USER_ENUMS={13:{'2':'User-defined'},16:{'0':'Appliance / широкий діапазон','1':'UPS / вузький діапазон'},
 17:{'0':'Мережа спочатку / Utility first','1':'Сонце спочатку / SUB','2':'Сонце → АКБ → мережа / SBU'},
 18:{'0':'Сонце пріоритетно / Solar first','1':'Сонце + мережа / SNU','2':'Лише сонце / Only Solar'},
 20:{'01':'Тип машини 01'},21:{'0':'Безтрансформаторний'},
 22:{'0':'Однофазний'},24:{'0':'Достатньо енергії PV'},25:{'1':'Увімкнено'}}
