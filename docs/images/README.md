# Real screenshot gallery

These nine screenshots were supplied by the owner from the actual application
and Home Assistant. They are not AI-generated images or UI mockups. Only opaque
privacy masks and lossless PNG metadata removal were applied; retained pixels,
dimensions and UI layout are unchanged. No replacement room names, temperatures,
functions or logos were invented. The original files and archive remain outside Git.

**All five Ingress captures show App v0.3.0**, in an existing monitoring
installation. They do not document v0.3.1 first-run setup, CA import or new readiness
guidance. HA/Core/Supervisor versions and capture timestamps were not supplied
for this gallery and are not inferred from the images.

## Home Assistant overview

[![Climate devices overview; private names and temperatures redacted](climate-devices-overview.png)](climate-devices-overview.png)

The README hero is the owner's real **climate-devices-overview.png** capture.
Room names and measured/target temperatures are hidden. Visible widgets do not
establish permission to change heating; standard Climate controls may appear
while Heating Control is OFF.

## Controls

[![Home Assistant Controls; names and temperatures redacted](device-controls.png)](device-controls.png)

The actual device Controls section. Room names and numeric temperatures are
redacted; the existing heating-state labels and widget layout are retained.

## Sensors

[![Home Assistant Sensors; private names and values redacted](device-sensors.png)](device-sensors.png)

Separate current/target-temperature sensor labels and controller-status entries.
Room-name prefixes, temperature readings, status/alarm values and relative read
time are hidden. Sensor names retain the original UI language.

## Thermostat

[![Home Assistant thermostat; room name and measured/target values redacted](thermostat-detail.png)](thermostat-detail.png)

The real Climate more-info dialog, with its private room name and numeric
measured/target values redacted. Dial artwork and controls are unchanged; a
setpoint is not a measured room-air temperature or proof of physical warming.

## Overview — App v0.3.0

[![Ingress Overview — App v0.3.0](ingress-overview.png)](ingress-overview.png)

The actual monitoring-mode overview, with stored pairing status and commissioning
actions disabled. No identifying fields are visible in this supplied view.

## MQTT configuration — App v0.3.0

[![Ingress MQTT configuration — App v0.3.0; broker details redacted](mqtt-configuration.png)](mqtt-configuration.png)

Broker address, TLS port and username values are hidden. Password fields are empty;
configuration actions are disabled in monitoring mode. The screenshot shows
v0.3.0's file-based CA interface, not v0.3.1's public CA import form.

## Danfoss pairing — App v0.3.0

[![Ingress Danfoss pairing — App v0.3.0](danfoss-pairing.png)](danfoss-pairing.png)

Stored pairing is present; the page shows the saved-identity action and physical
controller instructions. No private identity, certificate or pairing code appears.
This is not a new-user pairing capture or another physical pairing validation.

## Connection diagnostics — App v0.3.0

[![Ingress Connection diagnostics — App v0.3.0; timestamp redacted](connection-diagnostics.png)](connection-diagnostics.png)

The version label, runtime readiness and MQTT status are retained. The private
last-successful-read timestamp is covered. A screenshot is a point-in-time view,
not polling-continuity or long-running stability evidence.

## Heating control — App v0.3.0, OFF

[![Ingress Heating control — App v0.3.0, OFF](heating-control-off.png)](heating-control-off.png)

The actual OFF/permission/settling safety messages and controls. The loaded
Supervisor permission is false in this capture. No activation, heating command
or production connection was performed to prepare this gallery.

## Privacy and review

Private room names, numeric temperatures, broker/account values, household
status values and timestamps are covered where present. No browser URLs,
credentials, private keys, certificate bodies/fingerprints or pairing codes
are published. The unredacted originals, unused alternative overview and ZIP
are excluded. Public output dimensions and checksums are in [manifest.json](manifest.json).

All nine outputs were inspected visually. A pixel comparison verified that
every retained pixel equals the original and every redaction pixel is opaque.
PNG outputs contain only IHDR, pHYs, IDAT and IEND chunks; no text/EXIF/time metadata.
The existing project icon and logo are unchanged.

## Remaining captures

- App Store listing and App information/Running status.
- An actual v0.3.1 setup/CA-import/readiness view, clearly labeled with its version.
- Heating Control ON, only from a separately authorized existing state or test.
- In-flight settling and safe setup/error states on an authorized test instance.

Do not pair, activate control, change settings or create a production failure
solely for a screenshot. Future captures must retain real UI, remove private
details and metadata, and identify the actual App version. No unavailable image
is represented by a broken link or fictional placeholder.
