# Experimental Preview: evidence and limitations

The owner chose to publish an **Experimental Preview**, with remaining gaps
disclosed, rather than wait for Stable/Public Beta acceptance. This is not a
security certification or a claim that those tests have passed.

## Owner-confirmed real v0.3.0 installation

On 2026-10-23, an in-place v0.2.2 → v0.3.0 Supervisor update showed Running,
retained independent pairing, 11 Climate entities and 22 temperature sensors
with current/target readings. Watts Live electricity and L1/L2/L3 continued.
Supervisor write permission true loaded while control initially remained OFF.

With ON, one room target was changed through HA. The original Danfoss phone
app independently showed that setpoint; HA state inspection confirmed it.
The original target was restored and confirmed through HA. With OFF, a subsequent
new effective change was blocked while monitoring continued. These observations
do not establish measured room warming, exact timing, raw traces, all command
races, seven-day availability or recovery.

## Local v0.3.1 regression evidence before public snapshot

| Suite | Passed |
| --- | ---: |
| Offline Python | 178 |
| Final isolated main container | 144 |
| Bootstrap container | 5 |
| Retained v0.3.0 rollback runtime | 2 |
| Preparation safeguards | 12 |
| Unchanged upstream vendor hashes | 57 |

Suites overlap and are not independent additive coverage. The candidate build
exited 0. Tests used synthetic identities, temporary state, mock controllers and
loopback TLS brokers in network-none containers. They covered first install,
legacy state/discovery, CA import/wrong trust, Ingress/CSRF, TLS, MQTT commands,
default OFF, reconnect, freshness, readback and uncertain-write behavior.
No new physical command or production acceptance occurred for v0.3.1.

Public files are an allowlisted snapshot with new user documentation and public
metadata. Private reports, household data and original Git history are excluded.
The original private-history/branding-only test modules are not shipped as
public-runtime CI tests. Retained totals above describe the pre-snapshot runs;
no complete public-snapshot retest or hosted CI pass is claimed at launch.

## Still unverified

- Independent new-user HAOS install, fresh-controller pairing and exact firmware matrix.
- Historical post-pairing UI rejection and read-only Climate-widget presentation.
- Installed administrator/non-admin/copied-path enforcement and effective HA/MQTT ACLs.
- Every physical race/retained/in-flight case, network/cloud recovery and measured multi-day continuity.
- Host reboot/Start on Boot, watchdog, verified backup contents and paired/full restore.
- Migration from a local/private App to this repository and actual Supervisor rollback.
- Complete dependency vulnerability/license inventory, reproducible release build and clean installed-image provenance.

Use [Issues](https://github.com/except179/danfoss-link-haos/issues/new/choose) for
sanitized observations and suggestions. Never alter heating, pair/reset a
controller or interrupt a shared broker merely to collect a bug report.
