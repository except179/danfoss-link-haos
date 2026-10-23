# MQTT authentication and TLS

Use an existing authenticated broker and a dedicated account for this App.
The App supplies no shared username/password and does not create accounts,
change ACLs or restart the broker. With the official Mosquitto App, follow its
[account and TLS documentation](https://github.com/home-assistant/apps/blob/master/mosquitto/DOCS.md).
Do not grant HA administrator privileges merely to obtain MQTT access.

In **MQTT configuration**, import the public CA-only PEM obtained through a
trusted route, explicitly approve trust, then enter your certificate-matching
broker address, TLS port, username and password twice. Use **Save MQTT
configuration → Verify MQTT TLS → Test MQTT connection**. The tests verify
TLS/name identity, authenticated login and anonymous rejection; they do not
publish/subscribe or prove topic ACL isolation. TLS cannot be disabled.

CA import permits at most 16 KiB/eight current CA certificates, rejects private
keys/leaf certificates/malformed or mixed material, and writes only the App's
fixed private CA path. No filenames or URLs are accepted. Saved CA takes
precedence and survives credential saves. File-manager `mqtt-ca.crt` fallback
is supported only when no private CA is saved. See [full setup](../danfoss_link/DOCS.md).

Review effective MQTT permissions before enabling control. ON may admit
commands from HA or any permitted MQTT publisher; administrator-only Ingress
does not enforce all broker authorization. Keep topic prefixes stable after
discovery and avoid broad retained-message deletion. Never share private
broker/account details, certificates or raw production logs in an issue.
