# Community announcement draft — not posted

**Danfoss Link for HAOS: Experimental Preview**

I’m sharing a free, open-source Home Assistant OS App for Danfoss Link CC.
It discovers room Climate entities and temperature sensors over authenticated
MQTT/TLS, with an Ingress setup UI, independent controller pairing, diagnostics
and optional room-target control behind two explicit activation gates.

Project, installation and feedback:
https://github.com/except179/danfoss-link-haos

Install through **Settings → Apps → Install app → Repositories**, add that URL
and select Danfoss Link for HAOS. amd64 HAOS/Supervisor only; an existing TLS
MQTT broker, Danfoss cloud access and physical CC pairing approval are required.
It is an App, not HACS. No subscription or maintainer registration is required.

One real v0.3.0 installation confirmed monitoring and a single-room ON/OFF
scenario, including confirmation in the original phone app. v0.3.1 has local
regression evidence; external fresh installation, long-term reliability,
broader firmware and recovery remain unverified. This is an Experimental
Preview, not Stable or certified. Controller schedules remain authoritative;
HA permissions and broker ACLs matter when control is ON.

The README shows the original logo. Real sanitized App screenshots are pending;
add reviewed captures before a later visual announcement if available.
Please use GitHub Issues for bugs, installation feedback and suggestions.
Never post credentials, pairing state, certificates, backups or household data.
For vulnerabilities, follow SECURITY.md.

Maintained by Povilas Kucinskas (P.K. Except), https://povilas.dk.
Original MQTT bridge by Leif Neland, MIT. Unofficial; not affiliated with or
endorsed by Danfoss, Home Assistant or Nabu Casa.

Suggested future venues: Home Assistant Community Forum / Share your Projects,
and Reddit r/homeassistant. This file does not post to either service.
