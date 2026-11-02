# User guide

[Українська](USER_GUIDE_UK.md) · [English](USER_GUIDE_EN.md)

## Home and connection status

Home shows PV, grid, load and battery. Flow directions depend on fresh available
measurements. A dash means missing/stale data, not zero. Zero is a valid reading.
Open Monitoring details to inspect units, source, quality and age. An estimated
value is not a direct measurement. An unconfirmed interpretation is not enough
to justify changing hardware settings.

If readings disappear, inspect connection status, Server, LAN/remote routing
and equipment status. A connected Client–Server link does not prove that Server
is receiving fresh inverter measurements.

## Charts and history

Choose the day/month/year, Local/SmartESS/Auto source, fields and mode. Power is
measured in W/kW; energy is measured in kWh. Auto selects sources using provenance
rules rather than adding duplicate readings from both sources. Partial coverage
is shown separately.

Use zoom and fullscreen to inspect intervals. Windows supports PNG/PDF/CSV
export. Large queries run as background jobs with progress/cancellation. Do not
clear history to reopen a chart; compatible cached results are reused.

## Balance, finances, calendar and reports

Energy balance summarizes the period; financial results use the house meter
and configured rates. Compare matching periods and coverage. The calendar opens
daily charts. Outage reports distinguish known and uncertain intervals:
missing communication alone does not prove that the external grid was absent.

## Forecast and actual

Configure location/panels, load weather and train when enough history is
available. Forecast comparisons show measured actual hours without filling
missing readings artificially. A stored issued forecast keeps its issue time;
an updated remaining-day forecast must not replace it for accuracy assessment.
A fresh installation has no accuracy statistics until sufficient data exists.

## Parameters and profiles

Read a parameter's description, current value and bounds. Check that writing is
supported for the detected model/firmware. Confirm the change, then inspect
readback in the command log. After an ambiguous response, inspect current state
before retrying. Preview a profile's changes before applying it; mismatched
model/firmware profiles must be rejected.

## Background operation, notifications and widget

On Android enable the notification types/thresholds you need, OS permission
and background access. Reliable background operation can use more battery.
On Windows the Client must remain running in the tray; a sleeping/off PC does
not deliver new notifications. The widget shows the latest available snapshot
and does not directly poll the inverter. Widget freshness and Server collection
status are different things.

Use the saved Language selector to switch English/Ukrainian independently in
each program. On Android this recreates the current screen; finish unsaved
edits first. On Windows captions update without changing enum/profile values.
Diagnostic log contents and raw identifiers remain unchanged.

## Troubleshooting

| Symptom | Check |
|---|---|
| Client cannot connect | Your address, port28766, running Server, network/route |
| Fingerprint changed | Reinstallation/identity change; compare on Server phone |
| Server runs without readings | Equipment-free switch, logger IP/PN, Wi-Fi, profile support |
| Helper unreachable from phone | Explicit LAN bind, port28765, private Firewall rule, PC LAN address |
| Forecast is empty | Location, coordinates, PV settings, weather access, history coverage |
| Balance/training is slow | Job progress, history size, Server power/memory; avoid duplicate jobs |
| Update will not install | Newer code, same package/key, free space, installer permission |
| Battery estimate unknown | Your usable capacity and a justified full-charge reference |

When reporting a problem, include versions, OS, steps, expected result and a
redacted example. Do not publish raw logs, pairing codes/tokens or screenshots
containing your identifiers. See [SECURITY.md](../SECURITY.md).

