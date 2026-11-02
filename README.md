# Duck Solar b2.0.0

[English](README.md) · [Українська](README_UK.md)

Monitor a Daxtromn solar inverter through EyBond: live measurements, charts and
history, energy balance, house meters, generation forecasts, notifications and
verified control of supported parameters.

Public beta for self-installation. Support depends on model and firmware;
EyBond support alone does not imply compatibility with every command.
**English and Ukrainian are available; English is the default.** Own code and
documentation are MIT; dependencies retain their licenses.

## Components

| Program | Role | Required? |
|---|---|---|
| Android Server | Logger connection, collection, storage, calculations and HTTPS API | Main server |
| Android Client | Monitor/control from a phone | One Client option |
| Windows Client | Monitor/control from a PC | Alternative/additional Client |
| PC Helper | LAN updates, log copies and history preparation | Optional |

**EyBond ↔ Android Server ↔ Android/Windows Client**. Helper does not poll the
inverter or replace Server. Closing Client does not stop Server collection.

## Get started

1. Follow [Installation](docs/INSTALLATION_EN.md).
2. Initially start Server in equipment-free mode.
3. Enter your own addresses, logger PN and account using [Configuration](docs/CONFIGURATION_EN.md).
4. Pair Client and verify Server's fingerprint.
5. Before using real equipment, ensure another server is not controlling the same logger.
6. Read the [User guide](docs/USER_GUIDE_EN.md) for routine operation.

No ready-made accounts, passwords, PN/MAC, home addresses, coordinates or old
inverter history are included. Supply your own settings. `192.0.2.x` and
`198.51.100.x` in fixtures are documentation-only examples, not device defaults.

## Language

Android Server: **Language** on the main screen. Android Client:
**More → Language**. Windows Client and Helper: the selector at the top of the
window. Choose **English** or **Українська**. Each program saves its preference;
English is used even when the operating-system language is Ukrainian.

Android reloads the screen without restarting collection; finish unsaved edits
first. Windows translates display values while preserving source selections
and entered text. Raw logs keep their original contents, and system dialogs
may follow OS settings. Runtime translation is offline; no model or service is required.

## Separate b2 installation

Android IDs: `ua.ducksolar.b2.server` and `ua.ducksolar.b2.client`. Server HTTPS
port: **28766**; Helper: **28765**. Windows Client data:
`%LOCALAPPDATA%\DuckSolarB2\PCClient`, with separate shortcuts, autostart and mutex.
Helper defaults to `%USERPROFILE%\.ducksolar-b2-helper` and loopback only;
LAN access requires an explicit `--host`.

b2 installs alongside b1, not over it. Profiles/history are not imported
automatically. Do not run two active servers against one logger. Leave b2 in
equipment-free mode while b1 serves that installation.

This bilingual replacement deliberately retains **b2.0.0/code20000**. New
checksums replace the earlier b2 checksums. An installed b2.0.0 requires manual
APK/package replacement; automatic update version guards stay intact.
APKs use the same public b2 key. Windows packages are unsigned.

## Development and publication

- [Build/test](docs/BUILD_EN.md), [Architecture](docs/ARCHITECTURE_EN.md)
- [Separate AI instructions](docs/AI_MAINTENANCE_EN.md), [AGENTS.md](AGENTS.md)
- [GitHub preparation](docs/PUBLICATION_EN.md), [Security](SECURITY.md)
- [Changelog](CHANGELOG.md), [Validation](docs/VALIDATION_EN.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md)

Sources are in `android-server/`, `android-client/`, `pc-client/`, `pc-helper/`.
Own documentation has English/Ukrainian counterparts. Standard third-party
licenses remain in their original form. No GitHub publication or physical-device
installation has been performed as part of this preparation.
