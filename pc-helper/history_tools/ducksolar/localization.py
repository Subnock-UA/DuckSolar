"""Presentation boundary. Internal IDs, timestamps and protocol values stay neutral."""
from datetime import date, datetime

LOCALE = 'uk-UA'
DATE_FORMAT = '%d.%m.%Y'
DATETIME_FORMAT = '%d.%m.%Y %H:%M:%S'
TEXTS = {
    'parameter.waiting': 'Очікування інвертора',
    'parameter.offline': 'Інвертор не підключений',
    'parameter.reading': 'Читання параметрів…',
    'parameter.current': 'Актуально',
    'parameter.error': 'Помилка читання',
    'server.stopped': 'Зупинено', 'server.starting': 'Запуск…',
    'server.running': 'Працює', 'server.stopping': 'Зупинка…',
    'server.error': 'Помилка',
}

def text(key, fallback=None):
    return TEXTS.get(key, fallback if fallback is not None else key)

def format_date(value):
    if isinstance(value, (datetime, date)):
        return f"{value.day:02d}.{value.month:02d}.{value.year:04d}"
    try:
        return format_date(datetime.fromisoformat(str(value).replace('Z', '+00:00')))
    except (ValueError, TypeError):
        return str(value or '')

def format_datetime(value):
    try:
        dt=value if isinstance(value,datetime) else datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if dt.tzinfo is not None:dt=dt.astimezone()
        return format_date(dt)+dt.strftime(" %H:%M:%S")
    except (ValueError,TypeError):
        return str(value or '')

def parse_date(value):
    """Accept Ukrainian input and existing ISO saved data."""
    for fmt in (DATE_FORMAT, '%Y-%m-%d'):
        try: return datetime.strptime(str(value).strip(), fmt).date()
        except ValueError: pass
    raise ValueError('Введіть дату у форматі дд.мм.рррр')

