"""Profile-scoped event descriptions; transport framing stays outside this module."""
import re

# Candidate PI30 positions supported by multiple references; conflicting positions
# are deliberately absent, and remain visible as unknown in the UI.
NAMES = {
 1:'PV-вхід не готовий: недостатня напруга / умови запуску',2:'Несправність інвертора',3:'Завищена напруга DC-шини',4:'Занижена напруга DC-шини',
 5:'Невдалий запуск DC-шини',6:'Мережа відсутня або неприйнятна',7:'Коротке замикання виходу',
 8:'Занижена вихідна напруга',9:'Завищена вихідна напруга',10:'Перегрів',
 11:'Блокування вентилятора',12:'Завищена напруга АКБ',13:'Низька напруга АКБ',
 15:'Вимкнення через низьку напругу АКБ',17:'Перевантаження',18:'Помилка EEPROM',
 19:'Надструм інвертора',20:'Невдалий запуск інвертора',21:'Помилка самоперевірки',
 22:'Завищена постійна складова виходу',23:'Обрив підключення АКБ',
 24:'Помилка датчика струму',25:'Коротке замикання АКБ',26:'Обмеження потужності',
 27:'Завищена напруга PV',28:'Аварійне перевантаження MPPT',
 29:'Перевантаження MPPT',30:'Напруга АКБ недостатня для заряду',
}
SOURCE = 'PI30 20150924; mpp-solar eafdd432; Daxtromn profile validation required'

def decode_warnings(raw, confirmed_profile=False):
    raw = str(raw or '').strip()
    if not re.fullmatch(r'[01]{32}', raw):
        return {'raw':raw,'valid':False,'events':[], 'display':'Невідомий формат попереджень' if raw else '—'}
    events=[]
    for index, value in enumerate(raw):
        if value!='1':continue
        position=index+1
        known=position in NAMES and (position!=1 or confirmed_profile)
        confirmed=confirmed_profile and known
        title=NAMES[position] if known else f'Нерозшифроване попередження #{position}'
        events.append(dict(id=f'pi30.qpiws.{position}',position=position,title=title,
            display=title,
            confidence=('verified_current_device' if position in (1,6) else 'documented_profile') if confirmed else 'high_probability' if known else 'unknown',
            severity=('info' if position==1 else 'error' if position==2 else 'warning') if confirmed else 'unconfirmed',
            source=('PI30 model-specific PV readiness definition' if position==1 else 'Detected-model PI30 event definitions') if confirmed else SOURCE))
    return {'raw':raw,'valid':True,'events':events,
            'display':'; '.join(item['display'] for item in events) or 'Немає активних попереджень'}

def confidence_label(value):
    return {'user_confirmed':'Підтверджено користувачем','verified_current_device':'Підтверджено для профілю',
        'documented_profile':'Документовано для профілю','high_probability':'Високовірогідне',
        'protocol_family':'Високовірогідне','unknown':'Невідоме',
        'unverified':'Не підтверджено','unavailable':'Не отримано'}.get(value,value)
