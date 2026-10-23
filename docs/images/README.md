# Screenshot capture and gallery plan

**All captures PENDING.** No actual App screenshots are available in the
repository. This checklist reserves filenames and captions; it is not a gallery
of fictional images. The original icon/logo are artwork, not screenshots.

For v0.3.1, the MQTT view should also capture **Import public CA**, its trust
confirmation, empty PEM input and fixed size/format guidance. Overview should
show real new setup-step/readiness messages. Capture these only on a later
approved isolated HAOS test installation; the existing production App is v0.3.0.

## Capture rules

The owner can supply passive captures from an already available real UI after
review. The agent must not connect to production. Do not enable control, pair,
change settings or create errors solely for screenshots. Capture setup/error
states on a separately authorized isolated installation with synthetic data;
the screenshot must still show the actual running App, labeled as a test instance.
An ON capture needs an already authorized state or a later owner-approved test.

Use one desktop viewport, theme and browser zoom; keep text legible at about
1000 pixels wide. Export lossless PNG in sRGB. Prefer dark Ingress views and a
consistent HA theme. Crop browser chrome, address bars, sidebars and unrelated
entities. A 16:10 or 4:3 crop is suggested below, not mandatory if it cuts warnings.

Before sharing, permanently cover/crop all household room names/readings,
entity IDs, controller identities, MQTT hosts/usernames, network addresses,
HA URLs/session paths, pairing codes, certificate bodies/fingerprints and
credentials. Do not rely on masking a password field alone. Use opaque
redaction, flatten the image and remove EXIF/text/location/time metadata.
Never replace real values with invented values that appear observed. Caption
redacted areas honestly. Keep the unredacted original private, outside Git.

## Capture checklist

Menu/page names follow `IngressServer.PAGES` and the v0.3.1 form labels. HA outer menus can vary by version.
Every row is owner-captured; isolated rows can alternatively be captured by a
future authorized tester. No image files are promised by a link before they exist.

| View / purpose | Actual location | Reserved filename | Crop | Caption | Extra privacy / capture condition |
| --- | --- | --- | --- | --- | --- |
| App listing; installation discovery | Settings → Apps → Install app; project repository section | `app-store-listing.png` | 16:10 | Find Danfoss Link for HAOS in the approved custom repository. | Use this public repository on a test installation; hide other repository names/URLs. |
| App information and status | Settings → Apps → Danfoss Link for HAOS; Info | `app-information-running.png` | 4:3 | Version and Running status on the documented test installation. | No claim of a newer installed version; hide host/user context. |
| Overview; hero | Open Web UI → Overview | `ingress-overview.png` | 16:10 | Overview of MQTT and saved pairing readiness; private details redacted. | Hide connection details, identity and ingress URL. |
| MQTT setup | Open Web UI → MQTT configuration | `mqtt-configuration.png` | 4:3 | Configure your own authenticated TLS broker; saved passwords are not displayed. | Prefer real App with synthetic test endpoint/account; all secret inputs empty. |
| Independent pairing | Open Web UI → Danfoss pairing | `danfoss-pairing.png` | 4:3 | Pair an independent client with physical controller approval. | No code/client identity; unpaired setup only on separate test instance. Do not re-pair household. |
| Diagnostics | Open Web UI → Connection diagnostics | `connection-diagnostics.png` | 4:3 | Readiness and last-operation results without secret details. | Redact exact household timestamps/status context and any identifiers. |
| Heating control OFF | Open Web UI → Heating control | `heating-control-off.png` | 4:3 | Permission and activation are separate; control can remain OFF. | Keep warning/settling text; no new physical operation for capture. |
| Heating control ON | Open Web UI → Heating control | `heating-control-on.png` | 4:3 | Explicit ON permits room targets; schedules still belong to the CC. | Later authorized state/test only; do not activate solely for artwork. |
| Climate thermostat | HA room Climate more-info dialog | `climate-thermostat.png` | 4:3 | A room exposes measured and target temperatures; values redacted. | Redact room/entity names and every household value; do not imply warming. |
| Device and entities | Settings → Devices & services → MQTT → Danfoss Link CC | `mqtt-device-entities.png` | 16:10 | One controller device exposes room Climate entities and sensors. | Redact identifiers/room names/readings; actual count varies per installation. |
| Safety / settling | Heating control warning and operation status | `heating-control-safety.png` | 4:3 | OFF blocks new admission; an admitted operation can still settle. | Use later isolated in-flight test; never force household write for capture. |
| Setup and safe error | Connection diagnostics after a controlled setup check | `setup-error-state.png` | 4:3 | Actionable status with secret details suppressed. | Separate isolated instance only; no intentional production failure. |

## Overview

Reserved hero: `ingress-overview.png`. Place its image below the existing
README Screenshots section only after review. Caption: **Overview of connection
and pairing readiness. Private details are redacted.** Remove the pending notice
only when the actual approved image is tracked and its link resolves.

## Gallery acceptance

Insert approved captures at the README Screenshots section in a consistent order:
MQTT setup → pairing → diagnostics → monitoring → control OFF/ON. Keep each
caption tied to the actual screenshot version/environment. Prefer links to
larger images over unreadably small thumbnails. Listing/Info/error/safety
captures belong with the corresponding setup/troubleshooting explanations.

Record filename, App/HAOS/Core/Supervisor versions where known, actual versus
test instance, reviewer, crop/redaction/metadata checks and caption in a safe
capture manifest. Do not include a household fingerprint or raw original.
Check pixels manually at full resolution and verify metadata before staging.
Only add an image after its owner approves the sanitized capture; missing screenshots do not block this preview.
