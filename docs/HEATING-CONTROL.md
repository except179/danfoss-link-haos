# Optional room-target control

Monitoring is the default. Heating needs two independent gates:

1. Supervisor **Allow heating control** (`danfoss_allow_writes`) enabled, saved
   and loaded by an App restart.
2. Explicit authorization checkbox and **ON — enable heating control** in Ingress.

Supervisor permission alone does not activate control. ON allows supported
room setpoint requests through HA Climate/MQTT within controller/software bounds.
No schedule, mode, holiday, installer or firmware mutation is offered.

Activation is process-local and resets on restart, MQTT reconnection, cloud
failure or uncertain writes. OFF blocks admission of new changes and invalidates
unadmitted work; an admitted operation may still finish. OFF cannot undo an
applied setpoint. The CC's own schedule may later replace a manual target.
Readback is checked; uncertain PATCH results are never automatically retried.
Inspect HA/the original phone app before deciding on another action.

Ingress protects setup/activation for administrators by design. While ON, HA
users/automations and MQTT publishers are governed by HA permissions and broker
ACLs. A fresh generation/timestamp is not an authentication credential.
Installed non-admin/ACL enforcement still needs independent validation.

Standard HA Climate dialogs may show target controls while OFF; visible controls
do not prove physical write permission. Use separate sensors in display-only
cards when monitoring only.

One real v0.3.0 installation confirmed a single-room setpoint change through
HA, independent display in the original Danfoss app, restoration confirmed in
HA and subsequent OFF blocking. These were setpoints, not measured air warming.
No raw transport trace or exhaustive physical race coverage is claimed.
v0.3.1 has local regression evidence only. [Testing details](TESTING.md).
