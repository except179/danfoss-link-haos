# Compatibility

| Requirement | Scope |
| --- | --- |
| Host | Home Assistant OS with Supervisor |
| CPU | amd64 only; no ARM/Raspberry Pi compatibility claim |
| Controller | Danfoss Link CC with cloud App pairing |
| Network | Danfoss cloud/internet and authenticated MQTT with verified TLS |
| HA integration | MQTT discovery enabled |
| Other Danfoss products | Not claimed compatible |
| Firmware | One owner environment; exact supported firmware matrix not yet established |

v0.3.0 has owner-confirmed monitoring and limited physical-control evidence on
one installation. v0.3.1 has local regression evidence, not an independent real
HAOS installation. Entity counts depend on the rooms in your installation.
HACS, HA Container/Core without Supervisor and standalone runtime installation
are outside this App's supported installation path. [Testing scope](TESTING.md).
