# Architecture and contracts

[Українська](ARCHITECTURE_UK.md) · [English](ARCHITECTURE_EN.md)

Android Server owns equipment communication, history, calculations and verified
commands. Kotlin provides Activity/Service lifecycle, permissions, resource
monitoring and installation; Chaquopy connects it to `android_bridge.py` and
the `ducksolar` Python package.

Android Client uses Kotlin views and `android_client.py` for sessions, transport,
state and asynchronous analytics. Windows Client uses `client_main.py`,
`desktop_client.py` and `desktop/` for tkinter/matplotlib, DPAPI, tray and widget.
PC Helper uses `update_server.py`/`pc_support.py` for LAN updates/log reception,
with preparation/migration/sync services launching `history_tools/` workers.

| Server module | Responsibility |
|---|---|
| config.py, core/models.py | Configuration and device definitions |
| adapters/, protocol/, drivers/ | EyBond transport, framing/CRC, model semantics |
| server_runtime.py | Runtime/service ownership |
| api.py, accounts.py, pairing.py, client_sessions.py | API3, permissions, pairing and sessions |
| storage.py, history_reader.py | Primary CSV/schema/SQLite data and history reading |
| energy_streaming.py, energy_accounting.py | Energy accounting and coverage |
| history_views.py, graph_projection.py | Projections and bounded chart results |
| prepared_history.py, history_sync.py | Prepared history, staging and activation |
| insights.py, battery_ledger.py, night_charge.py | Analytics, battery estimates and night mode |
| weather.py, pv_profiles.py | Weather, forecasts and device-bound PV settings |

Verify names against the current tree. Platform copies can contain extra methods;
do not overwrite one with another without checking their contracts.

## Invariants

- API3, TLS1.3/pinning, SPAKE2 pairing and device-scoped account access remain
  enforced. An unknown identity must not receive credentials.
- Server authorizes writes, checks model/current value/revision, obtains user
  confirmation, journals results and performs readback.
- One writer and atomic publication own data changes. Provenance, schemas, time
  boundaries, DST and gaps remain explicit; missing data is not synthetic zero.
- Cache identity includes model/source/algorithm/snapshot. A path change alone
  must not retransmit or recalculate unchanged history.
- Sync retains CAS, staging, validation, atomic activation and live tail.
  PC readiness does not prove successful phone activation.
- Server forecast analysis versions2+ pass through client adapters unchanged.
  Test API→Python→bridge→renderer, not only a preconstructed render fixture.
- Update checking reads metadata. Installation verifies full file/package/
  version/ABI/signature before collection quiescence and checkpoint.
- New installations have blank private fields, random identities and separate
  runtime roots. No bundled accounts, readings or automatic b1 import.
- Localization changes presentation only. Canonical API/enum keys and user
  input are not rewritten. No global process locale change may alter accounting.

## Languages and versions

The shared catalog is synchronized by `tools/sync_locales.py`. Android's
`UiLanguage` handles Activity contexts/views and explicit external render sinks.
Windows `ui_language.py`/`tk_language.py` translate display values while keeping
source variables and selection values canonical. Language preferences are
component-local and default to English, not to the operating-system language.

Product release remains b2.0.0; APK and PC code20000. Internal Python API
versions remain Server1.4.61/AndroidClient1.6.44 for compatibility. Product,
wire-contract, cache-schema and APK code versions are separate concepts.
Android IDs remain `ua.ducksolar.b2.server` and `ua.ducksolar.b2.client`, API
port28766, Helper28765; Windows uses separate DuckSolarB2 storage and startup.

