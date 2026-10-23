"""Bounded HTTP/1.1 setup UI, reachable only through Supervisor Ingress.

Supervisor enforces panel_admin before proxying and supplies the user ID.
No forwarded-address header, client role header or anonymous session is trusted.
No request URL, body, exception text or access log is emitted.
"""
import asyncio
from collections import OrderedDict, deque
from datetime import datetime, timezone
from html import escape
import json
import os
from pathlib import Path
import re
import secrets
import ssl
import time
from urllib.parse import parse_qsl

import commissioning as setup
from storage import private, validate_state

PROXY = "172.30.32.2"
PORT = 8099
MAX_HEADERS = 8192
MAX_BODY = 8192
PAGES = {"/": "Overview", "/mqtt": "MQTT configuration", "/pairing": "Danfoss pairing", "/diagnostics": "Connection diagnostics", "/heating": "Heating control"}
FIELDS = {
    "/heating/on": {"csrf_token", "approval"},
    "/heating/off": {"csrf_token"},
    "/mqtt/save": {"csrf_token", "mqtt_host", "mqtt_port", "mqtt_username", "password", "confirmation"},
    "/mqtt/import-ca": {"csrf_token", "ca_pem", "approval"},
    "/mqtt/verify-tls": {"csrf_token"},
    "/mqtt/test": {"csrf_token"},
    "/mqtt/defaults": {"csrf_token"},
    "/pairing/pair": {"csrf_token", "code", "approval"},
    "/pairing/verify": {"csrf_token"},
}
MESSAGES = {
    "saved": "MQTT connection settings, private password and CA saved. No connection was opened.",
    "defaults": "Supervisor broker settings selected. Your private password and CA are retained.",
    "tls_ok": "TLS chain and broker name/IP identity verified using the selected public CA trust. No MQTT login was sent.",
    "mqtt_ok": "Verified TLS login accepted and anonymous login rejected. No topics were published or subscribed.",
    "paired": "Saved application identity and CC certificate pin verified locally. Pairing is complete; do not pair again.",
    "pair_running": "Pairing request accepted. Completion is not yet confirmed. Refresh diagnostics; do not submit another code.",
    "identity_ok": "Saved application identity, private permissions and CC certificate pin verified locally.",
    "setup_required": "Choose setup in the App configuration and restart this App before commissioning.",
    "busy": "Another commissioning operation or the monitoring process holds the state lock. Wait and refresh.",
    "input_invalid": "Input was rejected. Check the fields and enter secrets again.",
    "password_mismatch": "Passwords do not match. Nothing was saved.",
    "ca_invalid": "The public CA is missing or invalid. Import a current public CA in PEM format or check the mqtt-ca.crt configuration file. Never supply a private key.",
    "ca_saved": "Public CA saved privately. No connection was opened. Verify MQTT TLS and test the login again; saved pairing is unchanged.",
    "ca_approval_required": "Import requires explicit confirmation that you trust this public CA. Nothing was imported.",
    "mqtt_incomplete": "MQTT configuration is incomplete or invalid. Check the broker address, username, private password and public CA before testing.",
    "approval_required": "Pairing requires the explicit approval checkbox and a fresh physical CC cloud code.",
    "local_code": "Local codes beginning 0000 are unsupported. Use the CC cloud App pairing flow.",
    "already_paired": "Saved pairing exists. It will not be overwritten or regenerated.",
    "identity_invalid": "Private identity state needs investigation. No replacement identity will be generated.",
    "broker_tls": "TLS verification failed. Check the trusted CA, broker address, certificate validity and IP/name identity.",
    "broker_auth": "The broker rejected the dedicated MQTT login. Check the saved username and password.",
    "broker_anonymous": "The broker did not explicitly reject anonymous login. Stop and review broker authentication.",
    "broker_protocol": "The broker returned an unexpected authentication response. No topics were used.",
    "connection_failed": "The requested connection could not be completed. Check network access and broker settings.",
    "pair_unconfirmed": "Pairing completion is unconfirmed. The CC may have accepted it. Inspect saved status and verify identity before any retry; preserve all state.",
    "timeout": "The requested operation timed out. Inspect status before retrying; no identity is automatically replaced.",
    "failed": "The operation stopped safely. Check configuration and private state. Secret details are suppressed.",
}
PAIR_LABELS = {"not_paired": "Not paired — no identity initialized", "pending": "Pending identity — preserved for an explicit retry",
               "stored": "Stored pairing present — use Verify saved identity to validate", "invalid": "Incomplete or invalid identity — investigate"}


class RequestError(ValueError):
    def __init__(self, status=400):
        self.status = status


class Limits:
    def __init__(self):
        self.buckets = {}

    def allow(self, key, count, window, now):
        for old in list(self.buckets):
            queue, lifetime = self.buckets[old]
            while queue and queue[0] <= now - lifetime:
                queue.popleft()
            if not queue:
                del self.buckets[old]
        if key not in self.buckets:
            if len(self.buckets) >= 512:
                return False
            self.buckets[key] = (deque(), window)
        queue, _ = self.buckets[key]
        if len(queue) >= count:
            return False
        queue.append(now)
        return True


class CSRF:
    def __init__(self):
        self.tokens = OrderedDict()

    def issue(self, user, prefix, action, now):
        while self.tokens and next(iter(self.tokens.values()))[3] <= now:
            self.tokens.popitem(last=False)
        while len(self.tokens) >= 512:
            self.tokens.popitem(last=False)
        token = secrets.token_urlsafe(32)
        self.tokens[token] = (user, prefix, action, now + 600)
        return token

    def consume(self, token, user, prefix, action, now):
        record = self.tokens.pop(token, None) if isinstance(token, str) and len(token) <= 64 else None
        return record is not None and record[:3] == (user, prefix, action) and now < record[3]


def identity_headers(headers):
    user = headers.get("x-remote-user-id", "")
    prefix = headers.get("x-ingress-path", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", user):
        raise RequestError(403)
    if not re.fullmatch(r"/api/hassio_ingress/[A-Za-z0-9_-]{1,256}", prefix):
        raise RequestError(403)
    return user, prefix


async def read_request(reader):
    try:
        async with asyncio.timeout(5):
            raw = await reader.readuntil(b"\r\n\r\n")
    except asyncio.LimitOverrunError:
        raise RequestError(431) from None
    if len(raw) > MAX_HEADERS or b"\x00" in raw:
        raise RequestError(431)
    try:
        lines = raw.decode("ascii").split("\r\n")
        method, route, version = lines[0].split(" ")
    except (ValueError, UnicodeError):
        raise RequestError() from None
    if method not in ("GET", "POST"):
        raise RequestError(405)
    if version not in ("HTTP/1.0", "HTTP/1.1") or len(route) > 256 or not re.fullmatch(r"/[a-z/-]*", route):
        raise RequestError()
    if len(lines) > 35:
        raise RequestError(431)
    headers = {}
    for line in lines[1:-2]:
        name, colon, value = line.partition(":")
        if not colon or not re.fullmatch(r"[A-Za-z0-9-]+", name) or any(ord(c) < 32 and c != "\t" for c in value):
            raise RequestError()
        name = name.lower()
        if name in headers:
            raise RequestError()
        headers[name] = value.strip()
    if version == "HTTP/1.1" and not headers.get("host"):
        raise RequestError()
    if "transfer-encoding" in headers or "expect" in headers:
        raise RequestError()
    user, prefix = identity_headers(headers)
    if method == "POST" and headers.get("sec-fetch-site") not in (None, "same-origin", "none"):
        raise RequestError(403)
    length_text = headers.get("content-length", "0")
    if not re.fullmatch(r"[0-9]{1,8}", length_text):
        raise RequestError()
    length = int(length_text)
    body_limit = 3 * setup.IMPORT_CA_LIMIT + 1024 if route == "/mqtt/import-ca" else MAX_BODY
    if length > body_limit:
        raise RequestError(413)
    if method == "GET":
        if length:
            raise RequestError()
        return method, route, user, prefix, {}
    if "content-length" not in headers:
        raise RequestError(411)
    if headers.get("content-type", "").lower() not in ("application/x-www-form-urlencoded", "application/x-www-form-urlencoded; charset=utf-8"):
        raise RequestError(415)
    async with asyncio.timeout(5):
        body = await reader.readexactly(length)
    try:
        text = body.decode("utf-8")
        if re.search(r"%(?![A-Fa-f0-9]{2})", text) or "\x00" in text:
            raise ValueError()
        pairs = parse_qsl(text, keep_blank_values=True, strict_parsing=True, max_num_fields=8,
                          encoding="utf-8", errors="strict")
    except (ValueError, UnicodeError):
        raise RequestError() from None
    fields = dict(pairs)
    if len(fields) != len(pairs) or any(len(key) > 32 or len(value.encode()) >
            (setup.IMPORT_CA_LIMIT if route == "/mqtt/import-ca" and key == "ca_pem" else 2048)
            or "\x00" in value for key, value in pairs):
        raise RequestError()
    return method, route, user, prefix, fields


class IngressServer:
    def __init__(self, state, heating=None):
        self.state = Path(state)
        self.heating = heating
        self.csrf = CSRF()
        self.limits = Limits()
        self.active = 0
        self.server = None
        self.tasks = set()
        self.last = None
        self.busy = False
        self.pair_task = None
        self.mqtt_verified = None
        self.identity_verified = None

    async def __aenter__(self):
        self.server = await asyncio.start_server(self.handle, "0.0.0.0", PORT, limit=MAX_HEADERS + 1)
        return self

    async def __aexit__(self, *args):
        self.server.close()
        await self.server.wait_closed()
        pending = set(self.tasks)
        if self.pair_task is not None:
            pending.add(self.pair_task)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    def pairing_running(self):
        return self.pair_task is not None and not self.pair_task.done()

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        accepted = False
        prefix = None
        try:
            peer = writer.get_extra_info("peername")
            if not peer or peer[0] != PROXY:
                await self.respond(writer, 403, "Access denied")
                return
            if self.active >= 8:
                await self.respond(writer, 503, "Busy")
                return
            self.active += 1
            accepted = True
            method, route, user, prefix, fields = await read_request(reader)
            now = time.monotonic()
            if not self.limits.allow("all", 120, 60, now) or not self.limits.allow(("user", user), 60, 60, now):
                raise RequestError(429)
            if method == "GET":
                if route not in PAGES:
                    raise RequestError(404)
                await self.respond(writer, 200, self.page(route, user, prefix, now))
            else:
                if route not in FIELDS:
                    raise RequestError(404)
                if set(fields) != FIELDS[route]:
                    raise RequestError()
                if not self.csrf.consume(fields.pop("csrf_token"), user, prefix, route, now):
                    raise RequestError(403)
                if route != "/heating/off" and not self.limits.allow(("actions", user), 10, 60, now):
                    raise RequestError(429)
                if route in ("/heating/on", "/heating/off"):
                    if self.heating is None:
                        raise RequestError(403)
                    try:
                        self.heating.set_enabled(route == "/heating/on", approved=fields.get("approval") == "yes")
                    except ValueError:
                        raise RequestError(403) from None
                    await self.respond(writer, 303, "Heating control state updated. Open Heating control.", location=prefix + "/heating")
                    return
                if route == "/pairing/pair" and (not self.limits.allow(("pair", user), 1, 120, now)
                                                 or not self.limits.allow("pair_global", 3, 3600, now)):
                    raise RequestError(429)
                if route == "/pairing/pair":
                    # The one bounded pairing task belongs to the service, not
                    # to the HTTP connection. POST/Redirect/GET makes refresh
                    # passive and avoids holding a proxy request for minutes.
                    if self.pairing_running() or self.busy:
                        result = "busy"
                    else:
                        self.last = {"action": route, "result": "pair_running",
                                     "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
                        self.pair_task = asyncio.create_task(self.perform(route, fields))
                        result = None
                    if result is None:
                        await self.respond(writer, 303, "Pairing request accepted. Open Connection diagnostics.",
                                           location=prefix + "/diagnostics")
                    else:
                        await self.respond(writer, 200, self.page("/diagnostics", user, prefix, time.monotonic(), result))
                else:
                    result = await self.perform(route, fields)
                    await self.respond(writer, 200, self.page("/diagnostics", user, prefix, time.monotonic(), result))
        except RequestError as error:
            recovery = f' <a href="{prefix}/diagnostics">Open Connection diagnostics</a>.' if prefix is not None else ""
            await self.respond(writer, error.status, "Request not accepted. An earlier pairing may still be running or saved. Open Connection diagnostics before retrying." + recovery)
        except (asyncio.IncompleteReadError, TimeoutError, UnicodeError, ValueError):
            await self.respond(writer, 400, "Request rejected. No secret details are returned.")
        except Exception:
            await self.respond(writer, 500, "Request stopped safely. Check App configuration and private state.")
        finally:
            if accepted:
                self.active -= 1
            self.tasks.discard(task)
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 2)
            except (ConnectionError, OSError, TimeoutError):
                pass

    async def respond(self, writer, status, body, *, location=None):
        data = body.encode("utf-8")
        redirect = f"Location: {location}\r\n" if location is not None else ""
        headers = (f"HTTP/1.1 {status} Response\r\n{redirect}Content-Type: text/html; charset=utf-8\r\n"
                   f"Content-Length: {len(data)}\r\nConnection: close\r\nCache-Control: no-store\r\n"
                   "Pragma: no-cache\r\nReferrer-Policy: no-referrer\r\nX-Content-Type-Options: nosniff\r\n"
                   "X-Frame-Options: SAMEORIGIN\r\n"
                   "Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'self'; base-uri 'none'\r\n\r\n")
        try:
            writer.write(headers.encode("ascii") + data)
            async with asyncio.timeout(5):
                await writer.drain()
        except (ConnectionError, OSError, TimeoutError):
            pass

    async def perform(self, route, fields):
        from monitor import operation_lock, options_from_file
        descriptor = None
        result = "failed"
        if self.busy or (self.pairing_running() and asyncio.current_task() is not self.pair_task):
            return "busy"
        try:
            options = options_from_file(self.state)
            if options["operation"] != "setup":
                raise setup.SetupError("setup_required")
            descriptor = operation_lock(self.state)
            self.busy = True
            if route == "/mqtt/save":
                self.mqtt_verified = None
                values = dict(fields)
                if not re.fullmatch(r"[0-9]{1,5}", values["mqtt_port"]):
                    raise setup.SetupError("input_invalid")
                values["mqtt_port"] = int(values["mqtt_port"])
                setup.save_mqtt(self.state, options, values)
                result = "saved"
            elif route == "/mqtt/defaults":
                self.mqtt_verified = None
                setup.use_supervisor_mqtt(self.state)
                result = "defaults"
            elif route == "/mqtt/import-ca":
                self.mqtt_verified = None
                setup.import_ca(self.state, fields["ca_pem"], approved=fields["approval"] == "yes")
                result = "ca_saved"
            elif route == "/mqtt/verify-tls":
                self.mqtt_verified = None
                await setup.verify_tls(options, state=self.state)
                result = "tls_ok"
            elif route == "/mqtt/test":
                self.mqtt_verified = None
                await setup.check_mqtt(options, self.state)
                self.mqtt_verified = self.configuration_stamp()
                result = "mqtt_ok"
            elif route == "/pairing/pair":
                await setup.pair_code(self.state, fields["code"], approved=fields["approval"] == "yes")
                result = "paired"
            elif route == "/pairing/verify":
                self.identity_verified = None
                validate_state(self.state)
                self.identity_verified = self.identity_stamp()
                result = "identity_ok"
        except BlockingIOError:
            result = "busy"
        except setup.LocalCodeError:
            result = "local_code"
        except setup.SetupError as error:
            result = error.code if error.code in MESSAGES else "failed"
        except ssl.SSLCertVerificationError:
            result = "broker_tls"
        except TimeoutError:
            result = "timeout"
        except (OSError, asyncio.IncompleteReadError):
            result = "pair_unconfirmed" if route == "/pairing/pair" else "connection_failed"
        except Exception:
            result = "pair_unconfirmed" if route == "/pairing/pair" else "failed"
        except asyncio.CancelledError:
            if route == "/pairing/pair":
                result = "pair_unconfirmed"
            raise
        finally:
            try:
                if route == "/pairing/pair":
                    result = self.record_pairing_result(result)
            finally:
                if descriptor is not None:
                    os.close(descriptor)
                    self.busy = False
        if route == "/pairing/pair":
            return result
        self.last = {"action": route, "result": result, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        return result

    def record_pairing_result(self, result):
        # Explicit pairing completion (not GET): trust validated durable state
        # over a network/cleanup exception. Never create/repair a manifest or pin.
        if result in ("paired", "pair_unconfirmed", "timeout", "already_paired"):
            try:
                validate_state(self.state)
            except Exception:
                if result == "already_paired":
                    result = "identity_invalid"
                elif result == "paired":
                    result = "pair_unconfirmed"
            else:
                result = "paired"
                self.identity_verified = self.identity_stamp()
        self.last = {"action": "/pairing/pair", "result": result,
                     "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        return result

    def file_stamp(self, names):
        """Metadata only: a remembered check is invalidated by any state change."""
        try:
            result = []
            for name in names:
                path = self.state / name
                if not path.exists() and not path.is_symlink():
                    result.append(None)
                    continue
                info = private(path).stat()
                result.append((info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns))
            return tuple(result)
        except Exception:
            return None

    def configuration_stamp(self):
        return self.file_stamp(("settings.json", "mqtt-settings.json", "mqtt_password", "mqtt-ca.crt"))

    def identity_stamp(self):
        return self.file_stamp(("app_key.pem", "app_cert.pem", "paired_cc.json", "identity_manifest.json", "identity-created.json"))

    def workflow(self, options, pairing):
        """Passive local guidance; no secret reads, probes or implicit pairing."""
        if options["operation"] == "invalid":
            return "Invalid configuration", "Correct the App Configuration options in Supervisor. No connection or pairing is started."
        if options["operation"] == "monitor":
            report = self.heating.report() if self.heating is not None else {}
            if report.get("ready") is True:
                return "Paired and monitoring", "Current controller reads are available. Heating control still requires separate permission and explicit ON."
            return "Temporarily disconnected" if report.get("last_success") else "Connecting to services", "Check connection diagnostics. Do not re-pair because a connection is unavailable."
        if pairing == "invalid":
            return "Invalid saved pairing", "Preserve private state and investigate. No replacement identity will be generated."
        if self.pairing_running():
            return "Pairing in progress", "Refresh diagnostics without submitting another code."
        if pairing == "pending":
            return "Pairing outcome needs review", "Preserve the pending identity and inspect diagnostics before any deliberate retry."
        stamp = self.configuration_stamp()
        if stamp is None:
            return "Invalid configuration", "Private MQTT file permissions or configuration need review."
        if not options["mqtt_host"] or not options["mqtt_username"] or stamp[2] is None or stamp[3] is None:
            return "Not configured", "Configure your own broker and password, and import its trusted public CA. Setup makes no automatic connections."
        if self.mqtt_verified is None or self.mqtt_verified != stamp:
            return "Ready for connection checks", "Saved settings are not proof of connectivity. Verify MQTT TLS and test authentication explicitly."
        if pairing == "stored":
            if self.identity_verified is not None and self.identity_verified == self.identity_stamp():
                return "Ready for monitoring", "Select monitor in App Configuration, save and restart only this App. Heating control starts OFF."
            return "Saved pairing present", "Verify the saved identity locally before switching to monitoring; do not pair again."
        return "Ready for pairing", "MQTT login and anonymous rejection passed this process. Pair only with physical controller approval; this is not continuous connectivity monitoring."

    def page(self, route, user, prefix, now, notice=None):
        from monitor import options_from_file
        try:
            options = options_from_file(self.state)
        except Exception:
            options = {"operation": "invalid", "mqtt_host": "", "mqtt_username": "", "mqtt_port": 8883}
        try:
            pairing = setup.pairing_status(self.state)
        except Exception:
            pairing = "invalid"
        writable = options["operation"] == "setup" and not self.pairing_running() and not self.busy
        def form(action, fields, label, available=None):
            token = self.csrf.issue(user, prefix, action, now)
            disabled = "" if (writable if available is None else available) else " disabled"
            return (f'<form method="post" action="{prefix}{action}" autocomplete="off">'
                    f'<input type="hidden" name="csrf_token" value="{token}">'
                    f'<fieldset{disabled}>{fields}<button type="submit">{escape(label)}</button></fieldset></form>')
        def input_field(name, label, value="", kind="text", extra=""):
            return (f'<label>{escape(label)}<input name="{name}" type="{kind}" '
                    f'value="{escape(str(value), quote=True)}" {extra} required></label>')
        nav = "".join(f'<a href="{prefix}{path}">{label}</a>' for path, label in PAGES.items())
        warning = ""
        if options["operation"] != "setup":
            warning = '<p class="notice">Monitoring mode: commissioning actions are disabled. Choose setup in the App configuration and restart this App to make changes.</p>'
        elif self.pairing_running() or self.busy:
            warning = '<p class="notice" role="status">Commissioning in progress. Refresh diagnostics; do not submit another pairing code.</p>'
        control = self.heating.control_status() if self.heating is not None else {"enabled": False, "permitted": False, "settling": False, "off_confirmed": True, "changed_at": None, "outcome": "none", "ready": False}
        state_label = "heating control enabled" if control["enabled"] else "heating writes disabled"
        content = f'<p class="tag">{escape(options["operation"])} · {state_label}</p>{warning}'
        content += '<p>Home Assistant Climate dialogs may show adjustment buttons even when writes are OFF. With control OFF, those controls cannot change heating. Use the separate current/target sensors in a display-only card for monitoring-only dashboards.</p>'
        if notice in MESSAGES:
            content += f'<p class="notice" role="status">{MESSAGES[notice]}</p>'
        stage, guidance = self.workflow(options, pairing)
        content += f'<p class="notice" role="status"><strong>{escape(stage)}</strong> — {escape(guidance)}</p>'
        if route == "/":
            content += ('<h2>Connect your controller safely</h2><p>Configure MQTT, verify its secure connection, then pair an independent Danfoss client. '
                        'Your Link CC remains the autonomous heating controller.</p>'
                        f'<p><strong>Pairing:</strong> {PAIR_LABELS[pairing]}</p>'
                        f'<p><strong>MQTT password:</strong> {"Configured" if (self.state / "mqtt_password").exists() else "Not configured"}</p>'
                        '<p>Setup mode makes no automatic MQTT or Danfoss connections. Verification and pairing run only when you submit their forms.</p>')
            content += (f'<ol><li><a href="{prefix}/mqtt">Configure your own MQTT broker and dedicated account.</a></li>'
                        '<li>Import the trusted public CA, save the password, then verify TLS and test authentication.</li>'
                        f'<li><a href="{prefix}/pairing">Pair an independent CC client only with physical approval.</a></li>'
                        '<li>Verify saved identity locally; preserve existing phone pairing.</li>'
                        '<li>Select monitor in App Configuration and restart only this App to activate monitoring.</li>'
                        f'<li><a href="{prefix}/heating">Optionally review separate heating permission and confirmed ON.</a></li></ol>'
                        '<p>Saving broker settings or importing CA trust needs no restart. Changing Supervisor mode or write permission requires one App restart.</p>')
        elif route == "/heating":
            content += '<h2>Heating control</h2>'
            if control["enabled"]:
                content += '<p><strong>ON:</strong> Heating control enabled — Home Assistant may change room target temperatures.</p>'
            elif control["settling"]:
                content += '<p><strong>DISABLING:</strong> New commands are blocked. An admitted operation is still settling; OFF confirmation is pending.</p>'
            elif not control["off_confirmed"]:
                content += '<p><strong>OFF requested:</strong> New commands are blocked. Check permission and the last operation; a previous physical result may be unconfirmed.</p>'
            else:
                content += '<p><strong>OFF:</strong> Monitoring only — heating writes disabled. Local write admission OFF confirmed; this does not reverse any previous physical change.</p>'
            content += '<p>The original CC still controls schedules. A schedule may subsequently replace a requested target. This feature cannot edit schedules, whole-house modes, installer settings, alarms, pairing or firmware.</p>'
            content += '<p>Supervisor danfoss_allow_writes is a permission gate, not activation. It defaults to false. To permit activation, explicitly set it to true in Supervisor and restart only this App. Ingress ON then requires confirmation. Changing that Supervisor option requires restart; Ingress ON/OFF requires no restart. Every App restart, MQTT reconnect or cloud failure returns control to OFF.</p>'
            content += '<p>OFF invalidates pending commands immediately. A PATCH already admitted to the transport may still complete; OFF cannot undo a physical change. Never assume a timeout means no change, and never blindly retry. Only verified CC readback confirms the result.</p>'
            content += f'<p>Supervisor permission loaded and valid: {control["permitted"]}. Last change this process: {escape(control["changed_at"] or "None")}. Last operation: {escape(control["outcome"])}. Operation settling: {control["settling"]}.</p>'
            content += '<p>Commands use authenticated MQTT and a freshness template. Broker topic permissions determine which publishers can command heating; Ingress activation does not impose administrator-only HA Climate service access. A clock/template mismatch rejects the command.</p>'
            content += form("/heating/on", '<label class="check"><input type="checkbox" name="approval" value="yes" required>I explicitly authorize Home Assistant to change room target temperatures, and understand existing CC schedules may replace them.</label>', "ON — enable heating control", available=control["permitted"] and control["ready"] and not control["enabled"] and not control["settling"])
            content += form("/heating/off", '<p>Stop admitting new heating changes. No restart required.</p>', "OFF — monitoring only", available=self.heating is not None)
        elif route == "/mqtt":
            content += '<h2>MQTT configuration</h2><p>Use your existing broker. TLS verification and monitoring-only operation are mandatory. Enter the password twice; saved secrets are never shown.</p>'
            content += form("/mqtt/import-ca", '<p>Paste the public CA certificate or CA-only chain supplied by your broker administrator. PEM format only; at most 16 KiB and eight certificates. No private keys, URLs or filenames. Import saves only this App’s fixed private CA file and opens no connection.</p>'
                            f'<label>Public CA PEM<textarea name="ca_pem" rows="8" maxlength="{setup.IMPORT_CA_LIMIT}" spellcheck="false" autocomplete="off" required></textarea></label>'
                            '<label class="check"><input type="checkbox" name="approval" value="yes" required>I trust this public CA and approve replacing this App’s saved MQTT CA. Verify the broker again afterwards.</label>', "Import public CA")
            content += form("/mqtt/save", input_field("mqtt_host", "Broker address", options["mqtt_host"], extra='maxlength="253"')
                            + input_field("mqtt_port", "TLS port", options["mqtt_port"], "number", 'min="1" max="65535"')
                            + input_field("mqtt_username", "Dedicated username", options["mqtt_username"], extra='maxlength="253"')
                            + input_field("password", "MQTT password", kind="password", extra='maxlength="1024" autocomplete="new-password"')
                            + input_field("confirmation", "Repeat password", kind="password", extra='maxlength="1024" autocomplete="new-password"'), "Save MQTT configuration")
            content += '<p>A saved private CA takes precedence and is preserved when saving credentials. Alternatively place mqtt-ca.crt in this App’s configuration folder; /config is read-only and used only when no saved CA exists. Use explicit Import public CA to replace saved trust. Broker overrides change only address, port and username.</p><h2>Verify and test</h2>'
            content += form("/mqtt/verify-tls", '<p>Verify the selected public CA, broker chain and address identity. No MQTT password is sent.</p>', "Verify MQTT TLS")
            content += form("/mqtt/test", '<p>Test the saved dedicated login and anonymous rejection using the saved CA. No topic subscriptions or publications.</p>', "Test MQTT connection")
            content += form("/mqtt/defaults", '<p>Remove the Web UI broker address, port and username override. Keep the saved password, CA and pairing identity.</p>', "Use Supervisor broker settings")
        elif route == "/pairing":
            content += f'<h2>Danfoss Link CC pairing</h2><p><strong>Status:</strong> {PAIR_LABELS[pairing]}</p>'
            content += form("/pairing/verify", '<p>Validate saved identity, permissions and certificate pin locally. No cloud connection.</p>', "Verify saved identity")
            content += ('<h3>At the physical controller</h3><ol><li>Open House Control → Settings → Wi-Fi and Apps.</li>'
                        '<li>Choose App Options → Add App → Connect App.</li><li>Generate a fresh cloud App code. Keep existing phone clients paired.</li></ol>'
                        '<p>Never reset the CC, change heating schedules, or use installer device pairing. Local codes beginning 0000 are unsupported.</p>')
            if pairing in ("not_paired", "pending"):
                content += form("/pairing/pair", input_field("code", "Fresh cloud pairing code", kind="password", extra='maxlength="128" inputmode="numeric" autocomplete="off"')
                                + '<label class="check"><input type="checkbox" name="approval" value="yes" required>I am at the CC and explicitly approve pairing this independent application. Preserve existing phones and schedules.</label>'
                                + '<p>Pairing may take up to three minutes. Submission opens diagnostics immediately; refresh checks status without resubmitting the code. Preserve pending state after an uncertain outcome.</p>', "Pair independent client")
            else:
                content += '<p>Pairing is disabled for stored or invalid state. Credentials are never replaced automatically.</p>'
        else:
            content += f'<h2>Connection diagnostics</h2><p>Version 0.3.1 · Heating control is OFF by default</p><p>Pairing: {PAIR_LABELS[pairing]}</p>'
            content += f'<p>Commissioning operation: {"In progress" if self.busy or self.pairing_running() else "Idle"}</p>'
            try:
                runtime = json.loads(private(self.state / "runtime.json").read_text())
                phase = runtime.get("phase")
                if phase in ("setup", "connecting", "ready", "unavailable"):
                    content += f'<p>Runtime: {phase} · Ready: {runtime.get("ready") is True} · MQTT connected: {runtime.get("mqtt_connected") is True}</p>'
                stamp = runtime.get("last_success")
                if isinstance(stamp, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})", stamp):
                    content += f'<p>Last successful controller read: {escape(stamp)}</p>'
            except Exception:
                content += '<p>Runtime status has not been reported.</p>'
            if self.last:
                content += f'<p>Last action: {escape(self.last["action"])} at {self.last["at"]}</p><p>{MESSAGES[self.last["result"]]}</p>'
            content += '<p>Diagnostics contain status only. Passwords, pairing codes, private keys, certificate bodies and raw exceptions are never returned.</p>'
        refresh = f'<meta http-equiv="refresh" content="2;url={prefix}/diagnostics">' if route == "/diagnostics" and self.pairing_running() else ""
        return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                + refresh +
                '<title>Danfoss Link for HAOS — by P.K. Except</title><style>'
                ':root{color-scheme:light dark;font-family:system-ui,sans-serif;background:#14202b;color:#edf3f7}body{max-width:880px;margin:0 auto;padding:24px}'
                'header,main{background:#203140;border:1px solid #3e5362;border-radius:16px;padding:24px;margin-bottom:20px}'
                'h1{font-size:1.7rem;margin-top:0}h2{font-size:1.3rem}nav{display:flex;flex-wrap:wrap;gap:16px}a{color:#9cdaff}'
                'p,li{line-height:1.65}label{display:block;margin:14px 0}input,textarea{display:block;box-sizing:border-box;width:100%;padding:12px;margin-top:6px;border:1px solid #7893a6;border-radius:8px;background:#14202b;color:#fff}'
                'input[type=checkbox]{display:inline;width:auto;margin-right:10px}button{padding:12px 20px;border:0;border-radius:8px;background:#a2dafa;color:#112332;font-weight:650;cursor:pointer}'
                'fieldset{border:0;padding:0}fieldset:disabled{opacity:.55}form{border-top:1px solid #536574;margin-top:20px;padding-top:12px}'
                '.notice{padding:14px;border-left:4px solid #a2dafa;background:#14202b}.tag{color:#a2dafa}'
                '.byline{margin-bottom:4px}.context{margin-top:0;color:#c2d3df}footer{font-size:.85rem;line-height:1.6}footer p{margin:10px 0}footer a{overflow-wrap:anywhere}</style></head><body>'
                '<header><h1>Danfoss Link for HAOS</h1>'
                '<p class="byline" aria-label="Developed and maintained by Povilas Kucinskas (P.K. Except)">by P.K. Except · '
                '<a href="https://povilas.dk" target="_blank" rel="noopener noreferrer">povilas.dk</a></p>'
                f'<p class="context">Administrator setup</p><nav>{nav}</nav></header>'
                f'<main>{content}</main><footer aria-label="Project attribution">'
                '<p>Unofficial community project. Not affiliated with or endorsed by Danfoss.<br>'
                'Not an official Home Assistant or Nabu Casa product.</p>'
                '<p>Developed and maintained by Povilas Kucinskas (P.K. Except) · '
                '<a href="https://povilas.dk" target="_blank" rel="noopener noreferrer">povilas.dk</a><br>'
                'HAOS App packaging, Ingress setup and integration maintenance.</p>'
                '<p>Original MQTT bridge: Leif Neland — '
                '<a href="https://github.com/leifnel/danfoss-link-mqtt" target="_blank" rel="noopener noreferrer">leifnel/danfoss-link-mqtt</a> (MIT).</p>'
                '</footer></body></html>')
