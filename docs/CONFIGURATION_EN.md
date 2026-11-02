# Configuration

[Українська](CONFIGURATION_UK.md) · [English](CONFIGURATION_EN.md)

## Interface language

Every component starts in English. Android Server has a **Language** button on
its main screen; Android Client uses **More → Language**. Windows Client has a
selector in the top bar, and PC Helper has one at the top of its window.
Choose **English** or **Українська**. Each application saves its own preference.

Language changes only presentation: API keys, enum values, units used by
calculations, profile identity, addresses, credentials and history are not
rewritten. On Android the screen is recreated; save or finish an edited form
first. The Server service continues running. Raw diagnostic logs retain their
original technical contents. Native OS dialogs may follow the system language.

## Equipment and Server

| Setting | Meaning |
|---|---|
| EyBond IP address | Your logger's local IPv4 address from the router's device list |
| EyBond logger PN | The serial/PN of your own logger, without extra spaces |
| Without equipment connection | HTTPS API works without polling or redirecting the logger |
| Normal mode | Local polling and cloud exchange through Server |
| Local polling without cloud | Local reading without SmartESS forwarding |
| Cloud forwarding without local polling | Forward cloud traffic without generating local reads |
| Start / Stop | Control collection; stopping attempts to restore the logger's direct ESS route |

IP and PN fields are initially empty; equipment-free mode is enabled. Reserve
the logger's address in DHCP if necessary. Server phone and logger must be able
to reach one another: guest-network isolation can prevent this. Equipment mode
changes take effect after stopping and starting Server.

Read and write support depends on the detected model and firmware. A profile
for another model must not be substituted. A supported setting must pass its
range/profile checks, confirmation and readback before a write is considered
successful. No old inverter readings, accounts or personal settings are bundled.
Technical PI30/model tables describe compatibility, not a saved installation.

## Client addresses, pairing and account

1. LAN HTTPS address: `https://<server-phone-address>:28766`.
2. Remote HTTPS is optional. Leave it empty for LAN-only use. The installation
   owner provides remote networking and must still verify TLS identity. Helper
   is not the remote monitoring API. Do not replace HTTPS with HTTP.
3. Create your own username/password on your server. There is no default account.
4. Obtain a pairing code using Server's pairing controls. Compare the server
   fingerprint and enter the logger PN. PN and pairing code are different values;
   PN is not a password.
5. Select account creation on first use; use sign-in for subsequent connections.
6. If a fingerprint changes, verify why on the actual Server phone before trusting
   it again. Do not automatically accept an unexplained identity change.

Clients choose an available route and reconnect. Manual LAN/remote controls set
a temporary preference and retain fallback behavior. Passwords are not stored
in the profile; the saved token is private. Windows protects tokens using the
current user's DPAPI, so moving a profile to another computer may require sign-in.

## Panels, location and forecast

Enter your own location or coordinates, installed PV power, tilt0–90° and
azimuth0–360° (south180°). The initial1kW is a neutral placeholder, not your
installation's rating. Configure the location before relying on a forecast.
Geocoding is oriented toward Ukraine; for another country enter coordinates
and verify the resolved location.

PV correction defaults to1.0, night-noise threshold to0W and inverter
self-consumption to0W. Enter values justified by your own measurements.
Changing the calculation model can invalidate derived caches; raw readings
remain preserved. Training requires sufficient history coverage and does not
invent missing measurements.

## Battery and off-peak charging

Usable battery capacity starts unset. Enter your capacity in kWh, reserve
percentage and efficiencies. Estimated energy/autonomy differs from SOC received
from the inverter/BMS. Set a100% reference only after a genuine full charge.

Before enabling off-peak charging, verify your inverter/battery current limits.
Set the schedule, current limits and charge source. While enabled, the mode
controls its related parameters and blocks conflicting manual writes. Disabling
it restores the managed values saved before enabling it. Adaptive application
is initially disabled; insufficient evidence falls back to the fixed schedule.

## House meter and tariffs

Enter cumulative import day/night and export day/night registers with their
date/time. Do not enter a monthly increment in place of a cumulative register.
Use the meter replacement workflow to preserve continuity when replacing a meter.

Initial financial amounts/taxes are0, the night factor is1 and commissioning
year0 means unset. Configure your own rates and commissioning date before
interpreting financial results. Feed-in tariff checks need the correct
installation category/date; download failures must not erase manual rates.
House-meter figures and calculated inverter energy have different origins.

## Helper and private files

Phone Helper addresses are initially empty. Enter your PC's LAN address and
port28765, verify its identity, then transfer data when needed. Logs may contain
your own addresses, PN and timestamps; redact them before publishing.

Low-level Server settings live under its private files directory at
`Server/DS_Server_Beta_2/config.json`, not in the repository. Do not edit them
while Server is running. Use validated UI/API settings for routine changes.
Build/worker environment variables are documented in [BUILD_EN.md](BUILD_EN.md).
The language preference is separate: Android app-private preferences or
`ui-language.json` inside the selected Windows data root.

