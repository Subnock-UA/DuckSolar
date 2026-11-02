# Third-party notices

[English](THIRD_PARTY_NOTICES.md) · [Українська](THIRD_PARTY_NOTICES_UK.md)

The root MIT license covers Duck Solar's own code/documentation. Dependencies,
SDKs, brands and external data retain their respective terms.

| Component | Purpose | License information |
|---|---|---|
| Gradle wrapper | Build launcher | third_party/Gradle-LICENSE.txt and wrapper headers |
| Kotlin, AGP, AndroidX | Android shell/build/tests | Licenses of their Maven artifacts |
| Chaquopy | Android Python runtime | third_party/Chaquopy-LICENSE.txt and runtime notices |
| Python | Interpreter/standard library | third_party/Python-LICENSE.txt and distribution notices |
| cryptography, cffi, spake2 | Cryptography/pairing | License files under third_party/ and wheel metadata |
| matplotlib, NumPy, Pillow, pystray and transitives | Windows charts/images/tray | third_party/DEPENDENCIES.json and included licenses |
| PyInstaller/build dependencies | Windows packaging | Included licenses, including PyInstaller's application exception |
| tzdata | Time zones | Package/IANA notices in third_party/ |
| mpp-solar | PI30 field/event reference | MIT, Copyright2017 jblance; included license |
| Open-Meteo | Weather/geocoding | CC BY4.0 data attribution and upstream terms |
| NEURC | Official tariff publications | The specific official publication/source |

mpp-solar reference commit: eafdd4328c77f516cf82430c5bcb6fa042c45d3a. It is not a
runtime dependency or a claim of support for all its drivers. No decompiled
third-party APKs, private research archives/photos or full reference repositories
are distributed here.

The dependency inventory describes the verified Windows build; Android Python
versions are separately pinned in Gradle. Preserve the appropriate wheel/runtime
notices when updating dependencies. Legal notices remain in their upstream
original form; own documentation is available in English and Ukrainian.

Translation drafts were prepared locally with an OPUS-MT Ukrainian–English model
(authors Jörg Tiedemann and Santhosh Thottingal; upstream model CC BY4.0), with
reviewed domain overrides. No translation model is distributed or needed at
runtime. See localization/ for catalog maintenance.

References: [Chaquopy](https://github.com/chaquo/chaquopy),
[Open-Meteo terms](https://open-meteo.com/en/terms),
[Argos Translate](https://github.com/argosopentech/argos-translate).
