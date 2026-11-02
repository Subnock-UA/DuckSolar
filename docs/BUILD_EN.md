# Build and test

[Українська](BUILD_UK.md) · [English](BUILD_EN.md)

Run commands from this repository root unless a directory change is shown.
Use a separate checkout/build directory, never a working installation. Do not
copy real profiles, data archives or signing keys into the repository.

## Android

Requirements: JDK17, Android SDK platform35/build-tools36.0.0, Python3.11 on
the build host, and dependency access/cache. Gradle8.11.1, AGP8.9.2,
Kotlin2.1.20 and Chaquopy17.0.0 are pinned. Android Python requirements are in
each `app/build.gradle.kts`; do not substitute the Windows runtime versions.

Set `JAVA_HOME` to your JDK17 directory and `ANDROID_HOME` to your SDK. If
`ANDROID_SDK_ROOT` is also set, it must identify the same SDK. Set
`DS_BUILD_PYTHON` to your Python3.11 executable; otherwise `python3.11` is used.
A local, untracked `local.properties` can also specify the SDK.

```powershell
python tools/sync_locales.py
cd android-server
.\gradlew.bat --no-daemon assembleDebug
cd ..\android-client
.\gradlew.bat --no-daemon assembleDebug
cd ..
```

Debug APKs are under `android-*/app/build/outputs/apk/debug/app-debug.apk`.
Their toolchain-generated debug key is for testing, not stable public updates.
For a signed release, create your own key outside the checkout and set:

| Variable | Value |
|---|---|
| DS_ANDROID_KEYSTORE | Your keystore path |
| DS_ANDROID_STORE_PASSWORD | Keystore password |
| DS_ANDROID_KEY_ALIAS | Signing key alias |
| DS_ANDROID_KEY_PASSWORD | Key password |

Run `assembleRelease`. Without signing variables, release output is unsigned.
Never commit passwords or keys. Keep a backup of the release key: compatible
future APKs must use it. Do not reuse another installation's private key.

## Windows Client

Use Windows x64 and Python3.11+ with Tk. The packaged Windows build was tested
with Python3.14. In a dedicated environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r pc-client/requirements-build.txt
.\.venv\Scripts\python.exe pc-client/client_main.py
.\.venv\Scripts\python.exe pc-client/build_exe.py
```

The portable directory is `pc-client/dist/DuckSolar_PC_Client/`. It includes
the EXE, dependencies, locale catalog, installer and `PAYLOAD_SHA256.json`.
An empty `signing_thumbprint` explicitly denotes an unsigned build.
To sign, select your own certificate from `Cert:\CurrentUser\My` using
`DS_WINDOWS_SIGNING_THUMBPRINT`, then run `build_exe.py --require-signature`.
The script does not automatically select a certificate by personal subject name.

## PC Helper

Install `pc-helper/requirements.txt` for source execution, or
`requirements-build.txt` for packaging. Run `python pc-helper/build_exe.py`.
Output is `pc-helper/dist/DuckSolar_B2_Helper/`; this build is unsigned.
For frozen Helper, `DS_WORKER_PYTHON` points to a separate Python3.11 environment
with Helper requirements installed. A source run normally uses its own Python.

Use a separate runtime root and an explicit public release directory:

```powershell
python pc-helper/update_server.py --host 0.0.0.0 --port 28765 --root .\runtime\helper --release-dir .\Releases
```

`release.json` contains an `artifacts` list. Every entry has `component`, a
relative `file`, `version`, `version_code` and `sha256`; Android also has
`package`. Components are `server`, `client` and `desktop_client`. Files must
remain inside the selected release directory. The compatible LAN contract isv1.

```json
{"artifacts": [{"component": "server", "file": "DS_Server_ver.b2.0.0.apk", "version": "b2.0.0", "version_code": 20000, "package": "ua.ducksolar.b2.server", "sha256": "<your APK SHA256>"}]}
```

## Languages

`localization/en.json` is the single presentation catalog. Source messages are
Ukrainian; English is the saved/default interface language. Reviewed overrides
are recorded in `localization/overrides_en.json`. Preserve every `{#0#}` marker
and technical value. Run `tools/sync_locales.py` to synchronize both Android
asset copies and both Windows copies. No translation model or network
translation service is required by the application or a normal build.

Android uses app-private preferences and localized Activity contexts. Canvas,
dialogs, notifications and RemoteViews have presentation adapters. Windows
stores `ui-language.json` under its runtime root and keeps canonical selection
variables separate from translated display variables. Do not translate API keys.

## Focused validation

```powershell
python tools/audit_public.py
python -m unittest discover -s tests -v
python -m unittest discover -s pc-client/tests -v
python pc-client/client_main.py --self-check <temporary-output-directory>
```

Tests use synthetic fixtures, temporary data and loopback listeners. They cover
empty defaults/isolation, language persistence and selection integrity, real
TLS/pairing, resumable transfer, notification delivery and menu coverage.
Self-check exercises the real UI, plots and forecast adapter without live writes.

Android instrumentation is under `app/src/androidTest`. Some historical tests
require a dedicated fixture server and ADB loopback forwarding. Never run the
entire suite on a working phone. Use separate Server11/Client13 emulators and
select relevant tests. A successful build alone is not device acceptance.

Before release, inspect members/licenses/checksums. Source archives must exclude
build/dist/runtime, local SDK paths, keys, private reports and `.git`. The
owner-specific `--denylist-file` is an external private JSON list and must never
be copied into the repository. Audit nested archive/bytecode contents too.

This user-requested bilingual replacement retains b2.0.0/code20000. Future
normal releases should increment versions; do not silently weaken updater
version checks to install this same-version replacement.

