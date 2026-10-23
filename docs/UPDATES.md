# Updates, migration and rollback

Use Supervisor's update flow for this same repository and App slug. Read the
changelog, retain the working source/version and preserve an off-device backup
before an update. Leave automatic updates disabled until you accept a policy.
Confirm version/Running, fresh monitoring, existing entities and phone app
afterward. Heating activation starts OFF even when permission was previously true.

## Existing private/local App installations

The repository URL contributes to Supervisor's App ID and data volume. Adding
this public repository beside an existing local App is **not** automatically
an in-place migration. Do not uninstall the working App, copy pairing into Git
or run two copies of one identity against live services. Migration needs a
protected backup, version/state mapping, an isolated rehearsal and one active
paired identity. This migration has not been validated.

v0.3.1 retains v0.3.0 state filenames, identity format, MQTT overrides/password/CA,
poll interval and discovery IDs. Local regressions passed; installed upgrade
acceptance remains incomplete. Never paste new-install example options over
saved configuration or pair again solely for an upgrade.

## Rollback

Disable control and let admitted work settle before any owner-approved rollback;
an uncertain physical result needs inspection. Keep identity, trust, credentials,
prefixes, polling and discovery IDs. A rollback does not undo a setpoint.
Supervisor does not necessarily offer arbitrary older tags; retain a reviewed
artifact/procedure rather than uninstalling or deleting state.

Still-unconfigured blank v0.3.1 setup cannot start on v0.3.0 until the user's own
valid nonempty broker options exist. The old UI's TLS/password-save path uses
its file-manager CA source, while monitoring uses saved trust; keep sources
consistent before deliberately saving credentials there. v0.2.2 additionally
requires write permission false. Retained-v0.3.0 compatibility tests were local,
not a real Supervisor rollback.

## Recovery limits

Backup contents, paired/full restore, host reboot/Start on Boot and watchdog
recovery are unverified. Downloading a backup does not prove recoverability.
Keep private backups protected/off-device; do not start a restored duplicate
identity against live services. Never reset/unpair the CC, broadly clear
discovery or restore a pre-pairing backup as a troubleshooting shortcut.
