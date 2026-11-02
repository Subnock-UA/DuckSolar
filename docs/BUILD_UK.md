# Збірка і перевірки

[English](BUILD_EN.md) · [Українська](BUILD_UK.md)

Усі команди нижче виконуються з кореня цього репозиторію, крім явно зазначених
переходів. Не збирайте поверх каталогу робочої установки. Не копіюйте у
репозиторій її конфігурації, APK/EXE, архіви даних чи ключі.

## Android

Потрібні JDK17, Android SDK із platform35/build-tools36.0.0, Python3.11 на
машині збірки та інтернет/кеш залежностей. Gradle8.11.1, AGP8.9.2, Kotlin2.1.20,
Chaquopy17.0.0 закріплені у вихідних файлах. Pythonзалежності Android закріплені
в `app/build.gradle.kts`; не підміняйте їх випадковим runtime із ПКпакета.

Вкажіть встановлені інструменти через змінні середовища. `JAVA_HOME` — каталог
JDK17, `ANDROID_HOME` — ваш SDK. Якщо задано `ANDROID_SDK_ROOT`, він має
збігатися з `ANDROID_HOME`. `DS_BUILD_PYTHON` — шлях до вашого Python3.11;
без нього використовується команда `python3.11`.
Альтернатива для SDK — локальний `local.properties`, який не комітиться.

```powershell
cd android-server
.\gradlew.bat --no-daemon assembleDebug
cd ..\android-client
.\gradlew.bat --no-daemon assembleDebug
cd ..
```

Результати: `android-*/app/build/outputs/apk/debug/app-debug.apk`.
Debugпідпис генерує Androidtoolchain; він не є приватним ключем попереднього
випуску й не призначений для стабільних публічних оновлень.

Для підписаного release створіть власний ключ поза репозиторієм. Задайте:

| Змінна | Значення |
|---|---|
| DS_ANDROID_KEYSTORE | Шлях до власного keystore |
| DS_ANDROID_STORE_PASSWORD | Пароль сховища |
| DS_ANDROID_KEY_ALIAS | Alias ключа |
| DS_ANDROID_KEY_PASSWORD | Пароль ключа |

Виконайте `assembleRelease` замість `assembleDebug`. Без цих змінних release
буде непідписаний. Не передавайте паролі через коміт або файл workflow.
Зберігайте ключ резервно: наступні APK для оновлення мають бути підписані ним.
Не використовуйте ключі/сертифікати сторонньої установки.

## Windows Client

Потрібні Windows x64, Python3.11+ із Tk; наявна перевірена packagedзбірка
використовує Python3.14. Створіть окремий venv:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r pc-client/requirements-build.txt
.\.venv\Scripts\python.exe pc-client/client_main.py
.\.venv\Scripts\python.exe pc-client/build_exe.py
```

`pc-client/dist/DuckSolar_PC_Client/` містить portableпакет, залежності,
установник і `PAYLOAD_SHA256.json`. Відсутній підпис позначений порожнім
`signing_thumbprint`. Для підпису явно задайте власний
`DS_WINDOWS_SIGNING_THUMBPRINT` із `Cert:\CurrentUser\My` і виконайте
`build_exe.py --require-signature`. Скрипт не шукає автоматично сертифікат
за назвою і не створює довіру у Windows за вас.

## PC Helper

Для запуску з коду встановіть `pc-helper/requirements.txt` у власний Pythonvenv.
Для portableEXE встановіть `requirements-build.txt`, виконайте
`python pc-helper/build_exe.py`. Результат: `pc-helper/dist/DuckSolar_B2_Helper/`.
Ця збірка непідписана. Залежності Pythonworker мають бути встановлені також
у Python, зазначеному в `DS_WORKER_PYTHON`; це може бути той самий venv.
Helper не містить персонального каталогу Python чи старих утиліт установки.

Задавайте `--root` окремо від дерева коду та своїх робочих даних.
`--release-dir` — окремий каталог із публічними пакетами та `release.json`:

```powershell
python pc-helper/update_server.py --host 0.0.0.0 --port 28765 --root .\runtime\helper --release-dir .\Releases
```

Опис кожного артефакту містить `component`, `file` (відносне ім’я), `version`,
`version_code`, `sha256`; для Android також `package`. Підтримуються
`server`, `client`, `desktop_client`; Helperзв’язок залишається LANконтрактомv1.
Файли повинні бути всередині releaseкаталогу. Приклад структури:

```json
{"artifacts": [{"component": "server", "file": "DS_Server_ver.b2.0.0.apk", "version": "b2.0.0", "version_code": 20000, "package": "ua.ducksolar.b2.server", "sha256": "<SHA256 вашого APK>"}]}
```

## Перевірки перед випуском

```powershell
python tools/audit_public.py
python -m unittest discover -s tests -v
python -m unittest discover -s pc-client/tests -v
```

Публічні hostтести не під’єднуються до реального логера: тимчасові сховища,
loopback і mock. Вони перевіряють порожні defaults/ізоляцію, справжній TLS,
парування/сесію, відновлення завантаження, сповіщення та охоплення меню.
`client_main.py --self-check <тимчасова-папка>` перевіряє UI/графіки/адаптер на
синтетичних даних; створює лише вікна самої програми й результати у вибраній папці.

Androidinstrumentationпопередніх патчів міститься у `app/src/androidTest`;
частина інтеграційних сценаріїв потребує ізольованого fixtureсервера та
ADBпереадресації loopbackпортів. Не запускайте весь набір на робочому телефоні.
Для нового патча оберіть релевантні тести й окремі емулятори Server11/Client13.
Збірка APK сама по собі не є перевіркою встановлення або роботи обладнання.

Перед пакуванням перегляньте вміст, ліцензії залежностей і SHA256. Вихідний
архів не повинен містити build/dist/runtime, ключів, локального SDKшляху,
звітів із приватними даними або `.git`. Контроль приватних значень для
власника підтримує `--denylist-file` із зовнішнім JSONсписком; цей файл
ніколи не додається до публічного дерева.


Перед збіркою після правок перекладів виконайте `python tools/sync_locales.py`.
Основний каталог — localization/en.json, перевірені правки — overrides_en.json.
Модель перекладу й мережевий перекладач для роботи чи звичайної збірки не потрібні.
Номер b2.0.0/code20000 збережено за прямою командою користувача.
