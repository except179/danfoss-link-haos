# Installation

> **Do not add this repository through HACS. This is a Home Assistant OS App, not a HACS integration.**
> HACS Custom Repositories cannot install it. Use Home Assistant's App repository screen below.

**v0.3.1 Experimental Preview · amd64 only · Home Assistant OS/Supervisor.**

1. Open Home Assistant.
2. Navigate to **Settings → Apps**.
3. Open **App Store / Install app**.
4. Open the **three-dot menu → Repositories**.
5. Add `https://github.com/except179/danfoss-link-haos`.
6. Find **Danfoss Link for HAOS — by P.K. Except**.
7. Select **Install** and follow the [setup instructions](../danfoss_link/DOCS.md).

Keep setup mode, TLS enabled and heating permission disabled. Start the App
and select **Open Web UI** as an administrator. Older frontends may call Apps
**Add-ons** and the App Store **Add-on Store**; neither route uses HACS.

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
