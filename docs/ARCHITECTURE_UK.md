# Архітектура й контракти

[English](ARCHITECTURE_EN.md) · [Українська](ARCHITECTURE_UK.md)

## Компоненти

Android Server: Kotlinкерує Activity/Service, життєвим циклом, ресурсами,
Androidдозволами й інсталятором. Через Chaquopy викликається Pythonядро
`android-server/app/src/main/python/android_bridge.py` та пакет `ducksolar`.
Тільки сервер спілкується з EyBond і володіє історією/розрахунками/командами.

Android Client: KotlinUI та `android_client.py` — транспорт/сесія/стан,
асинхронні запити, клієнтський адаптер аналітики. Windows Client:
`client_main.py`, `desktop_client.py`, `desktop/controller.py`, `pages.py`,
`widgets.py`; tkinter/matplotlib, DPAPI, трей та окремий віджет.

PC Helper: `update_server.py` та `ducksolar/pc_support.py` — LANHTTP,
каталог оновлень, resumableприймання журналів. `sync_service.py`,
`migration_service.py`, `preparation_service.py` керують окремими workers;
їх код і узгоджені розрахунки містяться у `history_tools/`.

## Основні Pythonмодулі сервера

| Каталог/модуль | Відповідальність |
|---|---|
| config.py, core/models.py | Налаштування/модель пристроїв |
| adapters/, protocol/, drivers/ | Транспорт EyBond, framing/CRC, семантика моделі |
| server_runtime.py | Власник runtime та сервісів |
| api.py, accounts.py, pairing.py, client_sessions.py | API3, права, парування й сесії |
| storage.py, history_reader.py | Первинні дані, CSV+schema/SQLite, читання історії |
| energy_streaming.py, energy_accounting.py | Енергетичні розрахунки/покриття |
| history_views.py, graph_projection.py | Проєкції й обмежені графічні вибірки |
| prepared_history.py, history_sync.py | Підготовлені історії, синхронізація/активація |
| insights.py, battery_ledger.py, night_charge.py | Аналітика, оцінка АКБ, нічний режим |
| weather.py, pv_profiles.py | Погода/прогноз, профіль панелей |

Назви перевіряйте в поточному дереві: не створюйте дубль сервісу тільки через
приблизну назву в документації. Деякі модулі присутні також у клієнті/Helper;
це платформні копії, а не дозвіл сліпо перезаписувати одну іншою.

## Незмінні вимоги

- APIконтракт3, HTTPS/TLS1.3, pinідентичність, SPAKE2парування, прив’язка
  акаунта до дозволених пристроїв. Невідомий pin не дозволяє надсилати секрети.
- Сервер авторизує кожен запис; перевіряє модель/поточне значення/ревізію,
  журналює результат і виконує readback. Клієнт не обходить ці перевірки.
- Один власник записів і атомарна публікація. Історія зберігає походження,
  схему й часові межі; DST/прогалини не замінюються штучними вимірами.
- Кеш залежить від моделі/джерела/алгоритму/знімка даних. Зміна файлового
  шляху не повинна спричиняти повне повторне передавання незміненої історії.
- Sync: CASблоки, staging/перевірка/атомарна активація та live-tail.
  Готовність на ПК не означає успішну активацію на телефоні.
- Forecast: `forecast_analysis_version >= 2` проходить клієнтський адаптер
  без legacyперезапису. Перевіряти повний шлях API→Python→bridge→renderer.
- Перевірка оновлення читає metadata. Встановлення перевіряє повний файл,
  package/version/ABI/підпис; зупинка збору/checkpoint лише після готового APK.
- Новий профіль має порожні персональні поля, нові випадкові ідентифікатори
  та окремий runtime. Немає вбудованих акаунтів/паролів/показів лічильника.

## Ідентичності b2

Випуск усіх компонентів b2.0.0; APKversionCode20000, PCversioncode20000.
Версії внутрішнього PythonAPI залишені для сумісності (Server1.4.61,
AndroidClient1.6.44); це інша шкала, ніж назва публічного випуску.
Протокольний LANконтракт Helper не змінено наv2, бо формат сумісний.
Не змішуйте номер продукту, wireконтракт, номер схеми кешу та APKversionCode.

