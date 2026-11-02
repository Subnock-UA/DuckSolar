# Interface languages / Мови інтерфейсу

English (`en`) is the default. Ukrainian (`uk`) preserves the canonical source
messages. `en.json` maps canonical messages and `{#0#}` placeholders to English.
It is a presentation catalog: API keys, enum values, settings and stored user data
must never be translated. Run `python tools/sync_locales.py` after editing it.

Англійська (`en`) — типова мова. Українська (`uk`) використовує початкові
повідомлення. `en.json` містить переклади та підстановки `{#0#}`. Перекладати
можна лише відображення, а не ключі API, enum, налаштування чи дані користувача.
Після змін виконайте `python tools/sync_locales.py`.

