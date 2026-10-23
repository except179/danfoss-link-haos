# Set up Danfoss Link for HAOS

Maintained by **Povilas Kucinskas (P.K. Except)** · [https://povilas.dk](https://povilas.dk).
Original MQTT bridge by **Leif Neland**, [leifnel/danfoss-link-mqtt](https://github.com/leifnel/danfoss-link-mqtt), MIT.
Unofficial; not affiliated with or endorsed by Danfoss, Home Assistant or Nabu Casa.

**v0.3.1 Experimental Preview.** Local regressions passed; independent fresh
installation on another real HAOS system, prolonged reliability, installed
authorization and backup restore remain unverified. Real monitoring and a limited
single-room control test were owner-confirmed on v0.3.0. This preview welcomes
bug reports and improvement suggestions; it is not Stable or certified.

## Before you begin

Use Home Assistant OS with Supervisor on **amd64**, a Danfoss Link CC offering
cloud App pairing, internet connectivity and an existing MQTT integration/broker.
Other Danfoss systems and firmware combinations are not claimed compatible.
You need a Home Assistant administrator for setup and the broker's TLS endpoint,
dedicated account and **public CA certificate**. Do not use a shared default password.

Keep Protection mode enabled. Begin in **Setup** with heating permission OFF.
Do not enable automatic updates or rely on untested startup/watchdog recovery.
Preserve an off-device backup; its contents and restore need separate verification.

## Install through Home Assistant

Use **Settings → Apps → Install app → top-right menu → Repositories**.
Add `https://github.com/except179/danfoss-link-haos`, select **Danfoss Link for
HAOS — by P.K. Except** and choose **Install**. Supervisor builds the included
Dockerfile on amd64; internet access to the pinned upstream base is required. This is a Supervisor App, not HACS. Do not add the
upstream bridge repository as if it were this App. No terminal commands are
required for this installation flow.

An existing local App must not be uninstalled or silently switched to another
repository. The repository contributes to its identity and private data location.
Use a separately reviewed migration preserving pairing and MQTT identifiers.

## 1. Prepare MQTT authentication and trust

Use a dedicated per-install MQTT account. For the official Mosquitto App,
the documented route is **Settings → People → Users**; `homeassistant` and
`addons` are reserved names. A separately configured local broker login is
another supported option. Do not grant HA administrator rights merely for MQTT.
This App never creates users, changes ACLs or restarts the broker.

Obtain the broker's public CA certificate or CA chain from its administrator
through a trusted route. Do not fetch and blindly trust a certificate from an
unverified endpoint. The broker address must match its certificate's DNS name
or IP identity. Use the broker's configured TLS port; 8883 is only a common default.

In v0.3.1, open **MQTT configuration**, paste the trusted public CA PEM into
**Public CA PEM**, check the explicit trust/replacement confirmation and select
**Import public CA**. It accepts a current CA-only PEM certificate/chain, at most
16 KiB and eight certificates. DER, private keys, mixed text, non-CA, expired and
not-yet-valid certificates are rejected. No filename or server path is accepted.
Import stores only this App's fixed private CA file, opens no connection and
does not change pairing. It is setup-only and protected by Ingress/POST/CSRF.

Alternatively place **mqtt-ca.crt** in the App configuration folder, mounted
read-only at `/config`, using an authorized file manager such as a restricted
`app_configs` Samba share (legacy name `addon_configs`). It is used only when
no saved private CA exists. Saved CA trust takes precedence and is not replaced
by saving a password; use explicit Import public CA for intentional trust changes.
Never supply a private key, backup or pairing file. Do not broaden shares or
change broker settings merely for setup.

Blank host/username are allowed only in idle setup. Enter your own broker and
account before saving/verifying connections or selecting monitoring. Existing
saved nonempty options and Web UI overrides retain their precedence.

## 2. Configure and verify MQTT

Start the App in Setup and select **Open Web UI** while signed in as an
administrator. Use trusted HTTPS access to Home Assistant when entering secrets.

1. Open **MQTT configuration**.
2. Enter your broker address, TLS port, dedicated username and password twice.
3. Import the public CA if needed, then select **Save MQTT configuration**.
   Saving preserves selected trust, stores private credentials and opens no connection.
4. Select **Verify MQTT TLS**. It checks certificate trust and broker identity
   without sending an MQTT login.
5. Select **Test MQTT connection**. It checks the saved login and anonymous
   rejection without publishing or subscribing to topics.
6. Inspect **Connection diagnostics** for the result.

These checks do not prove topic ACL isolation. Review who can publish command
and discovery topics before enabling control. Never disable TLS or hostname
verification to bypass an error.

The passive Overview guides connection, trust/authentication, pairing, local
identity verification, monitoring and optional control. **Not configured** means
local setup is incomplete; **Invalid configuration** needs correction. **Ready
for pairing** means an explicit MQTT authentication test passed this process,
not continuous network monitoring. Verification indicators reset on restart or
relevant file changes. **Paired and monitoring** and **Temporarily disconnected**
use the active bridge status. GET pages never probe services or read key/password bodies.

Web UI broker settings override only address, port and username from the App
Configuration tab. **Use Supervisor broker settings** removes that override;
it does not discover a broker or create an account. Password, CA and pairing
remain saved. Configuration and verification actions are disabled in monitoring.

## 3. Pair a new independent client

**Only for an approved fresh installation. Existing paired installations must
not pair again.** The controller owner must approve the physical interaction.

1. At the CC, open **House Control → Settings → Wi-Fi and Apps**.
2. Choose **App options → Add App → Connect App**, then generate a fresh cloud
   App code. Labels may differ by language/firmware.
3. In **Danfoss pairing**, enter the code in the masked field, check the physical
   approval box and select **Pair independent client**.
4. Follow **Connection diagnostics** while pairing completes. Refreshing status
   is safe; do not resubmit a running request or blindly retry an uncertain result.
5. Still in Setup, select **Verify saved identity** to check saved private state locally.

The App creates a separate client identity. Keep the original phone paired.
Never reset the controller, delete identity files, remove a phone or change
schedules to make pairing succeed. Local codes beginning `0000` are unsupported.
Pending identity is preserved for investigation; it is not regenerated on startup.

Forms are single-use and expire after ten minutes. After a rejected/stale form,
refresh the page. Pairing is rate-limited; wait and inspect diagnostics before
considering a deliberate retry. A post-pairing UI issue remains under investigation
for the fresh-controller flow; successful existing monitoring is not proof of that flow.

## 4. Start monitoring

In the App **Configuration** tab, choose **monitor** (monitoring),
keep **Allow heating control** OFF, save and restart **only this App**. Confirm
Connection diagnostics reports ready and the last successful controller read advances.
The existing HA MQTT integration must have discovery enabled.

Look under **Settings → Devices & services → MQTT** for **Danfoss Link CC**.
Each room supplies a Climate entity and separate measured/target sensors.
Assign room entities to HA areas as desired; the whole controller is one device.
The private pilot has 11 Climate entities and 22 sensors; your room count may differ.

Compare current/target data with the original phone app. A setpoint is a requested
target, not measured air temperature. A successful CC read does not prove each
thermostat has just sent a new radio measurement. Polling defaults to 60 seconds;
cloud/network failures may delay readings and mark entities unavailable.

Standard Climate dialogs may show adjustment buttons while writes are OFF.
Use separate sensors in display-only cards when you want an unambiguous monitor.
The App cannot edit CC schedules, modes, vacation, installer settings or firmware.

## 5. Optional heating control

Keep monitoring-only operation unless the owner deliberately chooses control.
Review HA user/automation permissions and effective MQTT topic ACLs first.

1. In the App Configuration tab, enable **Allow heating control**
   (`danfoss_allow_writes: true`) while in Monitoring, save and restart only this App.
2. Control must still start OFF. Open **Heating control**, check the authorization
   box and select **ON — enable heating control**.
3. HA Climate may now request room targets within controller/software bounds.
   The App checks readback; broker delivery alone is not physical success.
4. Use **OFF — monitoring only** to stop admitting new changes without a restart.

ON is never saved across restart. MQTT reconnect, cloud failure or uncertain
write returns control OFF. OFF invalidates unadmitted work; an already admitted
operation may finish. OFF cannot undo a previous target, and CC schedules may
later replace it. There is no automatic retry after an uncertain write. Check
HA/the original phone app before deciding whether another action is appropriate.

Ingress setup and activation are administrator-only by design. Enabled Climate
commands may originate from other authorized HA users/automations or MQTT
publishers. Their access depends on HA permissions and broker ACLs, not the
Ingress checkbox. Installed authorization still needs independent validation; do not assume synthetic tests prove it.

## Configuration options

English labels are provided in `translations/en.yaml`; technical keys remain unchanged.

| Label / key | Guidance |
| --- | --- |
| Operating mode / `operation` | Setup permits deliberate commissioning only. Monitoring requires saved identity and verified MQTT configuration. Changing mode needs an App restart. |
| MQTT broker address / `mqtt_host` | Blank/unconfigured by default in setup; your certificate-matching host/address is required for connection/monitoring. Saved Web UI override takes precedence. |
| MQTT TLS port / `mqtt_port` | Your verified broker TLS port; no plaintext fallback. |
| MQTT username / `mqtt_username` | Blank/unconfigured by default in setup. Use your own dedicated account; password belongs only in the Web UI, not App options. |
| Require verified MQTT TLS / `mqtt_tls` | Must remain true; false stops the App. |
| Allow heating control / `danfoss_allow_writes` | Defaults false. Permission only; separate confirmed Web UI ON is required. Option changes need restart. |
| Refresh interval / `poll_interval` | 60–3600 seconds; default 60. This is a configured interval, not an availability guarantee. |
| MQTT topic prefix / `topic_prefix` | Advanced; default `danfoss_link`. Keep unchanged after discovery. |
| MQTT discovery prefix / `discovery_prefix` | Advanced; default `homeassistant`. Must agree with HA MQTT discovery. |

## Help, updates and privacy

If startup fails, check mode/options and the CA/credentials without revealing
secrets. Monitoring needs complete saved identity; do not regenerate it. If
TLS fails, check trust, address identity and certificate validity. If pairing
is uncertain, inspect saved status and wait. If data is stale, check diagnostics,
MQTT availability and internet/cloud service before assuming pairing is lost.

Read each future release's changelog and preserve verified off-device backups
before updating. Keep installed repository/slug/private state. Do not uninstall
to roll back. v0.2.2 rejects write permission true; a separately planned rollback
must restore false first and preserve all paired data. A rollback does not undo
a physical target. Backup restore and full HAOS recovery are not yet validated.

Report bugs and installation problems through
[GitHub Issues](https://github.com/except179/danfoss-link-haos/issues/new/choose).
Follow [SECURITY.md](https://github.com/except179/danfoss-link-haos/blob/main/SECURITY.md)
for vulnerability reporting. Before any public report, remove room names/readings, broker addresses,
usernames, credentials, pairing codes/identities, certificate bodies/fingerprints,
backups and raw logs. Report generic symptoms, versions and sanitized outcomes.
Never post a secret or private screenshot to obtain help.
