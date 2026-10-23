# Help and FAQ

These steps use Home Assistant and the App Web UI. They do not require SSH or
Docker. This is an Experimental Preview; use the repository’s GitHub Issues for public support. Keep private data out of reports; see [security guidance](../SECURITY.md).

| What you see | Safe next step |
| --- | --- |
| App does not start | In v0.3.1, blank host/username are valid only in setup; monitoring requires complete broker settings, identity, credentials and CA. Keep TLS true and refresh interval 60–3600. v0.3.0 still requires nonempty fields. A generic startup error is not proof identity is lost; do not delete state. |
| MQTT cannot connect | Check your own broker availability/address/TLS port and **Connection diagnostics**. In Setup, use **Verify MQTT TLS**, then **Test MQTT connection**. Do not change the shared broker or restart other Apps as a first response. |
| Username/password rejected | Confirm your dedicated broker account privately with its administrator. Re-enter it through the masked Web UI fields. Web UI address/port/username override Configuration-tab values when saved. Do not post credentials or automatically create accounts. |
| TLS verification fails | Check the trusted public CA chain, certificate validity, HAOS clock and that the configured broker address matches the certificate's DNS/IP identity. In setup, check the selected saved CA and import the correct public CA only after verifying its source; the file-manager fallback is named `mqtt-ca.crt`. Never disable verification or copy private keys. |
| Pairing does not finish | Wait for **Connection diagnostics**; refresh status rather than resubmitting. Check **Danfoss pairing** for stored/pending state. Verify saved identity locally while in Setup when appropriate. Keep uncertain state; a rejected form does not establish remote pairing failure. Never reset/unpair the controller or delete identity files. |
| Pairing form is rejected | Refresh the form after a stale session/token. Pairing is rate-limited. Preserve any already running/saved attempt and inspect its result before deciding on a retry with the owner. |
| CC temporarily unavailable | Check internet/cloud and MQTT status; later read-only polls can recover. Control returns OFF on cloud failure. Do not re-pair or restart the CC because of a transient outage. |
| Some thermostats are missing | Check HA MQTT discovery and unavailable/disabled entities, then compare room presence privately with the original phone app. Your room count need not match the pilot's 11 Climate entities. Avoid broad discovery deletion or changing prefixes. |
| Temperatures do not refresh | Inspect last successful CC read and entity availability. Polling defaults to 60 seconds but is not a continuity guarantee. Separate a successful CC snapshot from each thermostat's radio freshness; no per-device radio age is established. |
| Climate controls appear but do nothing | While OFF, standard Climate widgets may still appear although new writes are blocked. Use separate temperature sensors for display-only views. Do not enable writes just to hide a UI limitation. |
| Supervisor permission disabled | This is the safe default. Monitoring can work. Only the owner should opt into permission after reviewing HA/MQTT access; save/restart loads it, but does not turn control ON. |
| Heating control remains OFF | Check monitor mode, loaded permission, MQTT/cloud readiness and whether a previous operation is settling/unconfirmed. Explicit Web UI approval/ON is still required. Investigate readiness; do not repeatedly issue target commands. |
| Target later changes back | The CC's own schedule can override a manually requested target. The App cannot edit schedule or override duration. |
| Restart/reconnect returns control OFF | Expected safety behavior. Activation is memory-only; deliberate re-enabling is needed after readiness returns. |
| Write outcome is uncertain | Do not assume failure means no physical change. Check actual target in HA/the original phone app, request OFF and inspect settling. No automatic PATCH retry occurs; OFF cannot reverse an earlier target. |
| Upgrade or rollback question | Read [updates and rollback](UPDATES.md). Keep the installed identity/private state and verified off-device backup; never uninstall or regenerate pairing as a downgrade shortcut. |

## Frequently asked questions

**Does the App need Debian or another running server?** No. The supported
runtime is a container managed by HAOS/Supervisor. Developer build scripts are
not part of the ordinary user's setup.

**Can I use Home Assistant Container or HACS?** This package requires Supervisor
and its App lifecycle. Those installation methods are not supported by this App.

**Do I need a maintainer account or subscription?** No. The project is free and
open-source. MQTT authentication and Danfoss cloud connectivity remain dependencies.

**Does the original phone app remain paired?** The App uses a separate client
identity. Preserve existing phone pairing and confirm its operation after changes.

**Are all HA temperature commands restricted to administrators?** No. Ingress
setup/activation and HA/MQTT command authorization are separate boundaries. When
ON, HA permissions and broker ACLs determine command senders.

**Does OFF restore an earlier target?** No. It prevents new local admission.
Admitted work may finish; schedules may later replace the target. Restoration
is a separate physical action requiring the owner's decision.

**How do I configure the CA without a terminal?** Use an already authorized
Web UI session in setup: **MQTT configuration → Public CA PEM → Import public CA**
with explicit trust approval. This v0.3.1 feature accepts public CA-only
PEM, not files/paths, private keys or server leaf certificates. A restricted
file-manager `app_configs` route remains a fallback when no saved CA exists.
Saving credentials preserves saved trust; intentional replacement uses Import.

**Is a downloaded backup proven recoverable?** No. Contents/identity retention
and a separate isolated restore need validation; an App restart is not a restore test.

## Report a bug safely

Use [GitHub issue templates](https://github.com/except179/danfoss-link-haos/issues/new/choose) for versions, architecture, general
symptom, expected behavior and a short sanitized result. Remove broker/account
details, HA URLs, room names/readings, entity/controller IDs, codes, credentials,
certificates/fingerprints, backups and raw logs. Review screenshot pixels and
metadata. Do not publish a vulnerability in a public bug issue; follow [SECURITY.md](../SECURITY.md) to check private reporting availability before disclosing details.
