<p align="center">
  <img src="danfoss_link/logo.png" width="250" height="100" alt="Danfoss Link for HAOS — by P.K. Except">
</p>

# Danfoss Link for HAOS

**Bring your Danfoss Link CC heating system into Home Assistant.**

> **Do not add this repository through HACS. This is a Home Assistant OS App, not a HACS integration.**
> Install it through **Settings → Apps → App Store / Install app → three-dot menu → Repositories**.

Monitor room temperatures and optionally change room targets through a Home
Assistant OS App. Your Danfoss Link CC continues to manage its own heating schedules.

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

Real sanitized screenshots are not yet available. The approved logo above is
original artwork, not a simulated App view. The [owner capture checklist](docs/images/README.md)
covers Overview, MQTT, pairing, diagnostics, control OFF/ON, thermostat and discovered entities.
Reviewed real captures will be added here; no fictional UI or broken placeholders are included.

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
