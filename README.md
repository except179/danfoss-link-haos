<p align="center">
  <img src="danfoss_link/logo.png" width="250" height="100" alt="Danfoss Link for HAOS — by P.K. Except">
</p>

# Danfoss Link for HAOS

**Bring your Danfoss Link CC heating system into Home Assistant.**

> **Do not add this repository through HACS. This is a Home Assistant OS App, not a HACS integration.**
> Install it through **Settings → Apps → App Store / Install app → three-dot menu → Repositories**.

Bring room temperatures, target setpoints and available heating status into
Home Assistant with Climate entities and separate sensors. Configure MQTT,
independent controller pairing and diagnostics through the App Web UI. Room-target
control is optional and explicitly enabled; your Danfoss Link CC keeps its own schedules.

![Experimental Preview](https://img.shields.io/badge/status-Experimental_Preview-f59e0b)
![Version 0.3.1](https://img.shields.io/badge/version-0.3.1-0891b2)
![HAOS amd64](https://img.shields.io/badge/HAOS-amd64-164e63)
[![MIT license](https://img.shields.io/badge/license-MIT-334155)](LICENSE)

Maintained by **Povilas Kucinskas (P.K. Except)** · **[povilas.dk](https://povilas.dk)**

**Free and open-source.** No subscriptions, paid activation or account registration
with the maintainer. An authenticated MQTT broker and Danfoss cloud connectivity
are required.

> **Experimental Preview — v0.3.1.** One real installation validated monitoring and
> single-room control on v0.3.0. v0.3.1 passed local regressions, but has not been
> independently installed on another real HAOS system. Fresh installation,
> long-term stability, recovery and broader firmware compatibility remain unverified.
> [Read the testing scope and limitations](docs/TESTING.md).

[![Real Home Assistant Climate device overview with original room names and current/target temperatures](docs/images/climate-devices-overview.png)](docs/images/climate-devices-overview.png)

*Real Home Assistant device overview with owner-approved room names and actual
captured current/target temperatures. Visible widgets do not establish that
Heating Control is enabled. [Explore the screenshot gallery](docs/images/README.md).*

## What you get

| Feature | What it means for you |
| --- | --- |
| Room monitoring | Climate entities plus separate measured and target-temperature sensors through MQTT discovery. |
| Guided Web UI | Broker setup, public CA import, independent Danfoss pairing and connection diagnostics inside Home Assistant. |
| Optional room control | Explicit Supervisor permission and a separate confirmed ON switch; disabled by default. |
| Verified connections | Authenticated MQTT with certificate/name verification and saved controller trust. |
| Existing phone app | A separate client identity; keep your original Danfoss phone pairing. |

This App does not edit schedules, whole-house modes, holidays, installer settings
or firmware. It depends on Danfoss cloud services; it is not a local-only integration.

## Requirements

- **Home Assistant OS with Supervisor, amd64** (x86-64). ARM is not supported.
- **Danfoss Link CC** with the cloud App-pairing feature and internet access.
- An existing MQTT broker with **authentication and verified TLS**, plus the HA MQTT integration.
- Administrator access for setup, your broker's public CA certificate/chain and
  physical controller approval for a new independent pairing.

Other Danfoss product families and all firmware versions are **not** claimed
compatible. See [compatibility](docs/COMPATIBILITY.md).

## Install in Home Assistant

[![Add repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fexcept179%2Fdanfoss-link-haos)

1. Open Home Assistant.
2. Navigate to **Settings → Apps**.
3. Open **App Store / Install app**.
4. Open the **three-dot menu → Repositories**.
5. Add **`https://github.com/except179/danfoss-link-haos`**.
6. Find **Danfoss Link for HAOS — by P.K. Except**.
7. Select **Install** and follow the [setup instructions](danfoss_link/DOCS.md).

Keep **Setup**, verified TLS and heating permission OFF. Start the App and
select **Open Web UI** as an administrator. HACS Custom Repositories is the
wrong installation screen for this App.

Supervisor builds this App from the included Dockerfile on your amd64 HAOS host,
using a pinned upstream base image. Internet access to retrieve it is required;
the first build can take a few minutes. No project GHCR image is required or
advertised. This is a **Supervisor App, not a HACS integration**. Ordinary setup
requires no SSH, Docker commands or Linux terminal.

The repository follows the [official App repository mechanism](https://contributors.home-assistant.io/apps/guides/repository/).
End-to-end fresh installation remains experimental. Existing private/local-App
users should read [migration and updates](docs/UPDATES.md) before changing repositories.

## First-time setup

1. **Prepare your broker.** Use a dedicated account for this installation and
   obtain its public CA certificate through a trusted route.
2. **Import trust.** In **MQTT configuration**, paste CA-only PEM, confirm that
   you trust it and select **Import public CA**. Never import a private key.
3. **Save the connection.** Enter the certificate-matching broker address, TLS
   port, username and password twice. Run **Verify MQTT TLS**, then **Test MQTT connection**.
4. **Pair your own client.** In **Danfoss pairing**, use a fresh cloud App code
   from the physical CC and approve **Pair independent client**. Keep the phone paired.
5. **Verify and monitor.** Select **Verify saved identity**, then choose **monitor**
   in the App Configuration tab and restart only this App. Keep heating permission OFF.
6. **Find your rooms.** Open **Settings → Devices & services → MQTT → Danfoss Link CC**.

Setup starts offline with blank broker/username fields and no bundled password,
pairing identity or household CA. The App does not create broker users, pair
automatically or activate heating. Certificate verification cannot be bypassed.
Saving credentials/importing CA needs no restart; changing Supervisor mode or
permission does. [Full setup guide](danfoss_link/DOCS.md).

## Monitoring and optional heating control

Use Climate entities or the separate temperature sensors to monitor rooms.
The default refresh interval is 60 seconds; network/cloud failures can delay
readings. A target is a setpoint, not measured room-air temperature.

Heating control requires **both**:

1. **Allow heating control** in the App Configuration tab, followed by an App restart.
2. The authorization checkbox and **ON — enable heating control** in the Web UI.

Permission alone does not activate control. Activation resets after restart,
MQTT reconnection or cloud failure. **OFF blocks admission of new changes**;
already admitted work may finish, and OFF cannot undo an applied target.
Controller schedules remain authoritative and can replace a manual target.
Readback is checked; uncertain physical writes are not automatically retried.

Administrator-only Ingress protects setup and activation. While ON, commands may
also come from HA users, automations and MQTT publishers, governed by **HA
permissions and broker ACLs**. Ingress does not make every command administrator-only.
Standard Climate widgets may remain visible while control is OFF.
[Control guide and safety details](docs/HEATING-CONTROL.md).

## Screenshots

These are **real owner-supplied screenshots**, with the owner's approval to
show room names, actual temperatures, heating states and normal sensor values.
Only the MQTT broker address and username are masked; image metadata is removed.
No AI-generated screenshots, reconstructed measurements or simulated UI are used.
Select any image for full resolution; the [full gallery](docs/images/README.md)
explains each view and the remaining captures.

### Home Assistant: Controls, Sensors and thermostat

<table>
  <tr><th>Controls</th><th>Sensors</th><th>Thermostat</th></tr>
  <tr>
    <td valign="top"><a href="docs/images/device-controls.png"><img src="docs/images/device-controls.png" height="340" alt="Real HA Controls section with room names, heating states and actual current/target temperatures"></a></td>
    <td valign="top"><a href="docs/images/device-sensors.png"><img src="docs/images/device-sensors.png" height="340" alt="Real HA Sensors section with original names, measurements, alarm values and system status"></a></td>
    <td valign="top"><a href="docs/images/thermostat-detail.png"><img src="docs/images/thermostat-detail.png" height="340" alt="Real HA thermostat dialog with its original room name and actual measured/target temperatures"></a></td>
  </tr>
</table>

Climate widgets can appear even while Heating Control is OFF. These captures
show the actual HA presentation, not proof that a visible button can write.
HA frontend versions were not supplied.

### App Web UI: all five Ingress pages — v0.3.0

**Every Ingress capture below is from App v0.3.0**, in an existing monitoring
installation. They do not show the v0.3.1 first-run workflow or its public CA import.
The pairing page shows stored pairing, and the Heating control page shows OFF.

<details>
<summary>View all five real Ingress pages — v0.3.0</summary>

**Overview — App v0.3.0.** Monitoring mode and saved pairing status.

[![Overview — App v0.3.0](docs/images/ingress-overview.png)](docs/images/ingress-overview.png)

**MQTT configuration — App v0.3.0.** Only the broker address and username are
hidden. Field labels, TLS port and explanatory text remain visible; forms are
disabled in monitoring mode. This is the older file-based CA interface.

[![MQTT configuration — App v0.3.0; only broker address and username hidden](docs/images/mqtt-configuration.png)](docs/images/mqtt-configuration.png)

**Danfoss pairing — App v0.3.0.** An existing stored pairing; no pairing code or identity is shown.

[![Danfoss pairing — App v0.3.0; existing stored pairing](docs/images/danfoss-pairing.png)](docs/images/danfoss-pairing.png)

**Connection diagnostics — App v0.3.0.** Original runtime status and last-successful-read timestamp.

[![Connection diagnostics — App v0.3.0; original status and timestamp visible](docs/images/connection-diagnostics.png)](docs/images/connection-diagnostics.png)

**Heating control — App v0.3.0, OFF.** The actual permission/activation safety
messages and disabled ON form. No ON screenshot was supplied.

[![Heating control — App v0.3.0, OFF](docs/images/heating-control-off.png)](docs/images/heating-control-off.png)

</details>

## Help and feedback

- [Installation and setup](docs/INSTALLATION.md) · [MQTT and TLS](docs/MQTT.md) · [Pairing](docs/PAIRING.md)
- [Troubleshooting and FAQ](docs/TROUBLESHOOTING.md) · [Updates and rollback](docs/UPDATES.md)
- [Report a bug or installation problem](https://github.com/except179/danfoss-link-haos/issues/new/choose)
- [Suggest an improvement](https://github.com/except179/danfoss-link-haos/issues)

Please include versions, controller model/firmware if known, safe reproduction
steps and expected/actual behavior. Share only short **sanitized** logs or screenshots.
Never upload passwords, MQTT credentials, pairing identities/codes, certificates,
private keys, backups, household readings or private network configuration.
For vulnerabilities, follow [SECURITY.md](SECURITY.md), not a public issue.

## Version, updates and evidence

Current release line: **v0.3.1 Experimental Preview**. Read the [changelog](CHANGELOG.md)
and use Supervisor's update flow for this same repository/App identity. Retain
an off-device backup; a downloaded backup is not proof that restore works.

On one real v0.3.0 installation, pairing, **11 Climate entities and 22 temperature
sensors** remained usable after update. A room setpoint change appeared in HA
and the original Danfoss phone app; the original target was restored and checked
in HA. OFF blocked a subsequent new effective change. Watts Live telemetry
continued. These are limited owner-confirmed observations, not an exhaustive
security, stability or recovery certification. [Detailed scope](docs/TESTING.md).

Contributions are welcome: [contributing](CONTRIBUTING.md) and
[developer notes](docs/DEVELOPMENT.md). This preview is community-supported;
there is no response-time or uptime guarantee.

## Credits and license

HAOS packaging, Web UI and maintenance: **Povilas Kucinskas (P.K. Except)**,
[https://povilas.dk](https://povilas.dk).

Original MQTT bridge: **Leif Neland**,
[leifnel/danfoss-link-mqtt](https://github.com/leifnel/danfoss-link-mqtt), **MIT License**.
[Project license](LICENSE), [upstream license](danfoss_link/vendor/LICENSE) and
[third-party notices](danfoss_link/vendor/THIRD_PARTY_NOTICES.md) are preserved.
The physical MQTT device name remains **Danfoss Link CC**.

**Unofficial community project. Not affiliated with or endorsed by Danfoss.
Not an official Home Assistant or Nabu Casa product.**
