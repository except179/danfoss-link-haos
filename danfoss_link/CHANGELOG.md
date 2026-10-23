# Changelog

## 0.3.1 — Experimental Preview

- First public source distribution of the HAOS App, with a Supervisor Dockerfile
  build for amd64, original icon/logo and English configuration labels.
- New installs start offline in setup with blank MQTT host/username, no bundled
  credentials/pairing/household trust and heating permission disabled.
- Add explicit public CA PEM import, bounded format/CA/validity validation and
  fixed private storage. Credential saves preserve saved CA trust; runtime and
  TLS preflight use the same saved trust.
- Add sequential setup guidance and passive readiness status, without automatic
  pairing, account creation, monitoring transition or control activation.
- Preserve pairing/storage layout, MQTT settings, discovery identifiers, polling
  and Heating Control safeguards. Local legacy and retained-v0.3.0 tests passed.
- Independent real HAOS fresh installation, recovery, sustained availability,
  installed authorization and broader firmware support remain unverified.
- Public source starts a new sanitized history; private development evidence
  and household configuration are excluded. See [testing scope](../docs/TESTING.md).

## Earlier private milestones

| Version | Historical milestone |
| --- | --- |
| 0.3.0 | Optional room-target control with separate Supervisor permission and Ingress ON/OFF. One real HAOS installation confirmed update/pairing/entity continuity, a setpoint change seen in the original phone app, restoration in HA and practical OFF blocking. |
| 0.2.2 | Maintainer branding, povilas.dk links and upstream attribution/documentation. |
| 0.2.1 | Pairing lifecycle stabilization, read-only Climate limitation documentation and owner upgrade/restart observations. |
| 0.2.0 | Ingress setup, MQTT TLS, pairing and diagnostics. |
| 0.1.0 | Initial HAOS App packaging. |

These are sanitized milestone summaries. Historical private commits and raw
deployment reports are not part of this public repository.
