# Security and privacy

Danfoss Link for HAOS v0.3.1 is an **Experimental Preview**, maintained by
**Povilas Kucinskas (P.K. Except)**, [povilas.dk](https://povilas.dk).
There is no promised security-maintenance window or response-time SLA.

## Vulnerability reporting

Do **not** post exploit details or production data in public Issues.
GitHub private vulnerability reporting is enabled for this repository. Use
**Security → Advisories → Report a vulnerability**, or
[start a private report](https://github.com/except179/danfoss-link-haos/security/advisories/new),
with a sanitized affected version, impact and non-production reproduction.
If GitHub does not offer the private form to your account, open only a public
request for a confidential contact, without vulnerability details, and wait
for a maintainer-provided route. No security email address is advertised.

Never attach passwords, broker credentials, pairing codes/identities, private
keys, household certificates/fingerprints, backups, private addresses or raw
production logs, even to an initial private report. Use synthetic reproduction
where possible. Do not test against another person's controller or broker.

## Trust and control boundaries

- Setup starts offline and makes no automatic pairing or MQTT connection.
- MQTT uses per-install authentication, verified TLS and matching certificate
  identity; disabling verification is not supported. Public CA import requires
  explicit trust confirmation, CA-only PEM validation and fixed private storage.
- Pairing creates an independent protocol-capable client; keep the phone paired.
  Monitoring restrictions are enforced by the adapter, not a Danfoss-issued
  read-only credential. Private state belongs in protected backups, never Git.
- Supervisor write permission and confirmed Web UI ON are independent. ON is
  memory-only and resets on restart/reconnect/cloud failure. OFF stops new
  admission; admitted work may finish. OFF cannot undo a previous target.
- Uncertain physical writes are not automatically retried. Readback is checked;
  the controller's schedules may subsequently replace a manual target.
- Administrator-only Ingress protects setup/activation. HA Climate users,
  automations and MQTT publishers can command while ON subject to HA permissions
  and effective broker ACLs. Freshness tokens are not authentication secrets.

Review command/discovery topic permissions before opting into control. This App
does not create broker users, adjust ACLs or expose schedule/mode/installer writes.
Do not expose its internal Ingress port directly to an untrusted network.

## Preview limitations

Synthetic proxy/CSRF/TLS/control tests do not prove installed non-admin denial,
effective ACLs, complete security or disaster recovery. Those areas, long-term
availability and dependency vulnerability clearance remain incomplete.
[Testing scope](docs/TESTING.md). Keep backups protected/off-device; do not run
a restored duplicate pairing against live services. Certificate failures must
fail closed; importing arbitrary trust is not a troubleshooting shortcut.

This public repository contains a selected clean snapshot, not private
development history. The unchanged upstream service CA bundle is interoperability
material, not household trust or a paired controller identity. Applicable
third-party notices remain in the source.
