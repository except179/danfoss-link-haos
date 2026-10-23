# Danfoss Link for HAOS — by P.K. Except

**v0.3.1 Experimental Preview · amd64 · Home Assistant OS/Supervisor**

> **Do not add this repository through HACS. This is a Home Assistant OS App, not a HACS integration.**
> Use **Settings → Apps → App Store / Install app → three-dot menu → Repositories**.

Bring your Danfoss Link CC heating system into Home Assistant. Monitor room
temperatures through MQTT discovery and optionally change room targets.
Free and open-source; no subscription, paid activation or maintainer account.

Start in Setup, import your broker's trusted public CA, save your dedicated MQTT
credentials and explicitly verify TLS/authentication. Pair a separate client
with physical CC approval, verify saved identity, then select monitoring.
Keep existing phone pairing. No SSH or Docker commands are needed for user setup.

Heating writes are disabled by default. Supervisor permission and confirmed
Web UI ON are separate requirements. Restart/reconnection resets control OFF;
OFF cannot undo a previously applied target. CC schedules remain authoritative.
HA permissions and MQTT ACLs govern command senders while ON.

The App is built from its included Dockerfile by Supervisor; amd64 only.
One real installation validated monitoring/control on v0.3.0. v0.3.1 has local
regression evidence; independent fresh installation, recovery, long-term
stability and broader firmware support remain unverified.

[Setup guide](https://github.com/except179/danfoss-link-haos/blob/main/danfoss_link/DOCS.md)
· [Project and screenshots plan](https://github.com/except179/danfoss-link-haos)
· [Issues](https://github.com/except179/danfoss-link-haos/issues)

Maintained by **Povilas Kucinskas (P.K. Except)** · [povilas.dk](https://povilas.dk).
Original MQTT bridge: **Leif Neland**,
[leifnel/danfoss-link-mqtt](https://github.com/leifnel/danfoss-link-mqtt), MIT.
Unofficial; not affiliated with or endorsed by Danfoss, Home Assistant or Nabu Casa.
