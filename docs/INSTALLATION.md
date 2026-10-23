# Installation

**v0.3.1 Experimental Preview · amd64 only · Home Assistant OS/Supervisor.**

1. Open **Settings → Apps → Install app → top-right menu → Repositories**.
2. Add `https://github.com/except179/danfoss-link-haos`.
3. Select **Danfoss Link for HAOS — by P.K. Except** and **Install**.
4. Keep setup mode, TLS enabled and heating permission disabled. Start the App
   and select **Open Web UI** as an administrator.
5. Follow the [full first-time setup guide](../danfoss_link/DOCS.md).

Supervisor discovers `repository.yaml` and `danfoss_link/config.yaml`, then
builds the included Dockerfile on the HAOS host because no `image` field is
configured. It retrieves a pinned public upstream base image. No project GHCR
image or paid activation is required. Install time depends on the host/network.
This uses the [official custom repository mechanism](https://contributors.home-assistant.io/apps/guides/repository/)
and [source-build option](https://contributors.home-assistant.io/apps/reference/configuration/#image).
Older frontends may use the term add-on. This is not HACS and does not support
Home Assistant Container/Core without Supervisor.

You need a Link CC with cloud App pairing, internet access, a TLS-authenticated
MQTT broker, the existing HA MQTT integration and the broker administrator's
public CA. Initial setup requires no SSH or Docker commands. Firmware coverage
and end-to-end independent fresh HAOS installation are not yet verified.

Existing local/private-App users: changing the repository can change the App
identity and private data volume. Do not uninstall or create a second live
paired instance; read [updates and migration](UPDATES.md).
