# Installation

[Українська](INSTALLATION_UK.md) · [English](INSTALLATION_EN.md)

## Requirements

Android Server requires Android 8.0/API26 or later, Wi-Fi access to an EyBond
logger, storage for history and a stable power supply. Server APKs include
ARMv7, ARM64, x86 and x86_64. Android Client requires Android8+ with ARM64 or
x86_64; this build does not contain a 32-bit client. Windows Client requires
Windows10/11 x64. Running the source requires Python with Tk.

The targeted emulator checks use Android11 for Server and Android13 for Client.
They do not certify every Android release or inverter firmware.

## Android Server

1. Download the Server APK from a trusted release, or build it yourself. Compare
   its SHA256 with the checksum supplied with that release.
2. Open the APK, allow installation from that source and confirm installation.
   The application is named **Duck Solar Server b2**.
3. Open it and grant notification permission when requested by Android.
4. For continuous operation, allow unrestricted battery use. Also enable
   background operation in any manufacturer-specific power settings.
5. Initially keep **Without equipment connection** enabled, then start the
   server. An empty history is expected on a new installation.
6. Note the LAN addresses and server fingerprint displayed on the phone, then
   follow [Configuration](CONFIGURATION_EN.md).

English is the default, regardless of the phone's system language. Use
**Language** on the Server main screen to choose English or Ukrainian. The
selection is saved for this application. The screen reloads; server collection
is not restarted. Choose the language before entering an unsaved form.

b2 has a different application ID, storage and API port from b1. Do not uninstall
b1 to install b2. While b1 controls your real logger, keep b2 in equipment-free
mode: two active servers must not control the same logger.

## Android Client

Install the Client APK in the same way. Its application name is **Duck Solar b2**.
Enter the Server HTTPS address with port28766. Create an account on that server
or sign into an existing one; enter its logger PN and pairing code when needed.
Compare the fingerprint with the one shown on the Server phone.

Choose the interface language under **More → Language**. It is independent of
the Server language and persists across restarts. Configure notifications and
background operation as needed. Android force-stop prevents background delivery
until the app is opened again. Operating-system dialogs follow OS settings.

## Windows Client

Extract the complete ZIP. Keep `_internal` beside `DuckSolar_PC_Client.exe`.
Run the EXE or `Start.cmd` and enter your own connection settings. A language
selector in the top bar switches English/Ukrainian without changing the profile.
The default is English. Preferences are stored separately from b1.

`Install.cmd` can install a signed package into
`%LOCALAPPDATA%\Programs\DuckSolarB2PC\b2.0.0` and create separate b2 shortcuts.
The installer rejects an unsigned build unless explicitly allowed. After
checking its origin and release SHA256, an unsigned package can be installed with:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Install.ps1 -AllowUnsigned
```

Alternatively, use the portable EXE. Windows may warn about an unsigned or new
application. A checksum proves file consistency, not publisher identity.
See [Building](BUILD_EN.md) for source execution and optional signing.

## PC Helper — optional

Helper distributes local updates, receives log copies and prepares history. It
does not poll the inverter or replace Android Server. Extract the portable
Helper ZIP and open `DuckSolar_B2_Helper.exe`, or run the Python source after
installing `pc-helper/requirements.txt` in a separate Python3.11 environment:

```powershell
python pc-helper/update_server.py --headless
```

The default listener is `127.0.0.1:28765`, accessible only on this computer.
For phones on a trusted LAN, explicitly enable LAN listening:

```powershell
python pc-helper/update_server.py --headless --host 0.0.0.0 --port 28765 --root .\runtime\helper
```

Allow TCP28765 only on the private network in Windows Firewall. Enter
`http://<your-PC-LAN-address>:28765` in the phone's Helper settings and verify
the Helper identity before transferring data. Never expose this HTTP service
to the public internet. The GUI has its own saved English/Ukrainian selector.

History preparation needs a separate Python worker. With the portable EXE, set
`DS_WORKER_PYTHON` to your Python3.11 interpreter with Helper requirements
installed. Source execution normally uses the current interpreter.

## Updates and removal

A normal b2 update requires the same application ID and signing key, plus a
higher version code. **Check for updates** reads metadata; **Install update**
downloads and verifies a package, then opens Android's installer. Server creates
a checkpoint before installing. Keep the release key for future compatible APKs.

This bilingual rebuild intentionally retains **b2.0.0/code20000**. The automatic
updater will not offer it over another b2.0.0 build. To replace a previously
installed b2.0.0, open the new APK manually; it must use the same signing key.
For Windows, close b2 and replace the complete portable package or run its
installer. b1 is separate and must not be overwritten.

Back up anything you need before uninstalling. Android uninstall removes that
application's private storage. Deleting the Windows program folder does not
delete `%LOCALAPPDATA%\DuckSolarB2\PCClient`. Disable autostart and exit the tray
application before removing its executable files.

