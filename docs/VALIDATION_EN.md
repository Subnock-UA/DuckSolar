# Validation of the bilingual b2 replacement

[Українська](VALIDATION_UK.md) · [English](VALIDATION_EN.md)

The replacement retains b2.0.0, Android code20000 and Windows PE version
2.0.0.0. English is the default in all four applications; Ukrainian is selected
and saved per application. Only presentation is translated: API keys, entered
passwords/addresses/profile values and canonical selections remain unchanged.

| Check | Result |
|---|---|
| Public host contracts and language tests | 12 passed |
| Windows protocol/UI regressions | 5 passed |
| Android Server API30 | 2 passed: isolation and language selection |
| Android Client API33 | 3 passed: isolation, language and forecast adapter |
| Source Windows self-check | Passed, 30 sections, charts/widget and forecast |

Language tests cover English defaults, Ukrainian selection, persistence,
catalog consistency/placeholders and preservation of input. Android tests run
on isolated emulators. Windows tests exercise real Tk widgets, including a
translated combobox which preserves its canonical selection value.
Final build, frozen self-check and privacy results are in
[VALIDATION.json](../reports/VALIDATION.json),
[SOURCE_AUDIT.json](../reports/SOURCE_AUDIT.json) and
[ARTIFACT_AUDIT.json](../reports/ARTIFACT_AUDIT.json).

APKs retain the existing public b2 signing identity. Windows binaries remain
unsigned; installation instructions explain explicit unsigned consent. Install
this same-version replacement manually after closing the relevant application;
automatic updater version guards have not been weakened.

Source/artifact audits use an external private denylist, inspect nested APK,
ZIP and Chaquopy archives, and examine PyInstaller code constants/filenames.
The denylist, signing material, old inverter readings and private runtime data
are excluded. Automated checks cannot guarantee absence of every unknown
secret. Third-party PEM parser markers are not themselves private keys.

No physical device acceptance, live equipment polling/writes, history activation,
production updates or GitHub publication was performed. Focused emulator tests
do not prove compatibility with every model/firmware/device. Original b1 source
files and published binaries are checked against their existing baseline;
working b1 installations are not used as test roots.
