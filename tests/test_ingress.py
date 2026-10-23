"""Offline HTTP routing/security and shared commissioning regressions.

Requests use in-memory streams, synthetic credentials and mocked network/CC
operations. They never contact the installed HAOS App, broker or controller.
"""
import asyncio
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import ssl
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import urlencode

import commissioning as setup
import ingress
import monitor
from storage import atomic_json, identity_hashes
from test_app import OPTIONS, synthetic_state
from danfoss_mdg import __file__ as mdg_path

PREFIX = "/api/hassio_ingress/synthetic-session"
CA = Path(mdg_path).with_name("trusted-CAs.pem").read_text()


class Writer:
    def __init__(self, peer=ingress.PROXY):
        self.peer = peer
        self.buffer = bytearray()
        self.closed = False

    def get_extra_info(self, name):
        return (self.peer, 12345) if name == "peername" else None

    def write(self, data):
        self.buffer.extend(data)

    async def drain(self):
        pass

    def close(self):
        self.closed = True

    async def wait_closed(self):
        pass


class IngressTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = Path(self.temp.name)
        atomic_json(self.state / "settings.json", dict(OPTIONS, operation="setup"))
        self.server = ingress.IngressServer(self.state)

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def request(self, method="GET", route="/", fields=None, headers=None, peer=ingress.PROXY, raw=None):
        if raw is None:
            body = urlencode(fields or {}).encode()
            values = {"Host": "app:8099", "X-Remote-User-Id": "admin-user", "X-Ingress-Path": PREFIX}
            if method == "POST":
                values.update({"Content-Length": str(len(body)), "Content-Type": "application/x-www-form-urlencoded"})
            for key, value in (headers or {}).items():
                if value is None:
                    values.pop(key, None)
                else:
                    values[key] = value
            raw = (f"{method} {route} HTTP/1.1\r\n" + "".join(f"{k}: {v}\r\n" for k, v in values.items()) + "\r\n").encode() + (body if method == "POST" else b"")
        reader = asyncio.StreamReader(limit=ingress.MAX_HEADERS + 1)
        reader.feed_data(raw)
        reader.feed_eof()
        writer = Writer(peer)
        await self.server.handle(reader, writer)
        self.assertTrue(writer.closed)
        header, body = bytes(writer.buffer).split(b"\r\n\r\n", 1)
        return int(header.split(b" ")[1]), body.decode(), header.decode()

    async def token(self, action, page="/mqtt", prefix=PREFIX):
        status, body, _ = await self.request(route=page, headers={"X-Ingress-Path": prefix})
        self.assertEqual(status, 200)
        match = re.search(r'action="' + re.escape(prefix + action) + r'"[^>]*><input type="hidden" name="csrf_token" value="([^"]+)"', body)
        self.assertIsNotNone(match)
        return match.group(1)

    async def test_get_pages_are_passive_and_contain_no_secret_values(self):
        (self.state / "mqtt_password").write_text("synthetic-secret-password")
        (self.state / "mqtt_password").chmod(0o600)
        with patch("commissioning.verify_tls", new=AsyncMock()) as tls, \
                patch("commissioning.check_mqtt", new=AsyncMock()) as mqtt, \
                patch("commissioning.pair_code", new=AsyncMock()) as pair, \
                patch("commissioning.save_mqtt") as save:
            for route in ingress.PAGES:
                status, body, headers = await self.request(route=route)
                self.assertEqual(status, 200)
                self.assertNotIn("synthetic-secret-password", body)
                self.assertIn("Cache-Control: no-store", headers)
                self.assertIn("Content-Security-Policy:", headers)
                self.assertIn("Referrer-Policy: no-referrer", headers)
            for operation in (tls, mqtt, pair, save):
                operation.assert_not_called()
        self.assertFalse((self.state / "identity-created.json").exists())

    async def test_reject_direct_peer_even_with_spoofed_forwarded_headers(self):
        status, _, _ = await self.request(peer="192.0.2.17", headers={"X-Forwarded-For": ingress.PROXY})
        self.assertEqual(status, 403)
        status, _, _ = await self.request(peer="127.0.0.1")
        self.assertEqual(status, 403)

    async def test_missing_identity_or_ingress_prefix_is_denied(self):
        for headers in ({"X-Remote-User-Id": None}, {"X-Ingress-Path": None},
                        {"X-Ingress-Path": "//evil.invalid"}, {"X-Remote-User-Id": "<admin>"}):
            status, _, _ = await self.request(headers=headers)
            self.assertEqual(status, 403)

    async def test_dynamic_ingress_path_and_csrf_binding(self):
        token = await self.token("/mqtt/test")
        new_prefix = "/api/hassio_ingress/changed-session"
        with patch("commissioning.check_mqtt", new=AsyncMock()) as mqtt:
            for headers in ({"X-Ingress-Path": new_prefix}, {"X-Remote-User-Id": "other-user"}):
                status, _, _ = await self.request("POST", "/mqtt/test", {"csrf_token": token}, headers)
                self.assertEqual(status, 403)
            mqtt.assert_not_called()
        fresh = await self.token("/mqtt/test", prefix=new_prefix)
        with patch("commissioning.check_mqtt", new=AsyncMock()) as mqtt:
            status, body, _ = await self.request("POST", "/mqtt/test", {"csrf_token": fresh}, {"X-Ingress-Path": new_prefix})
            self.assertEqual(status, 200)
            self.assertIn("Verified TLS login accepted", body)
            self.assertIn(new_prefix + "/mqtt", body)
            mqtt.assert_awaited_once()

    async def test_csrf_required_single_use_and_action_bound(self):
        with patch("commissioning.check_mqtt", new=AsyncMock()) as mqtt:
            status, _, _ = await self.request("POST", "/mqtt/test", {"csrf_token": "forged"})
            self.assertEqual(status, 403)
            token = await self.token("/mqtt/verify-tls")
            status, _, _ = await self.request("POST", "/mqtt/test", {"csrf_token": token})
            self.assertEqual(status, 403)
            token = await self.token("/mqtt/test")
            self.assertEqual((await self.request("POST", "/mqtt/test", {"csrf_token": token}))[0], 200)
            self.assertEqual((await self.request("POST", "/mqtt/test", {"csrf_token": token}))[0], 403)
            mqtt.assert_awaited_once()

    async def test_cross_site_post_rejected(self):
        token = await self.token("/mqtt/test")
        with patch("commissioning.check_mqtt", new=AsyncMock()) as operation:
            status, _, _ = await self.request("POST", "/mqtt/test", {"csrf_token": token}, {"Sec-Fetch-Site": "cross-site"})
            self.assertEqual(status, 403)
            operation.assert_not_called()

    async def test_no_secret_get_query_or_file_routes(self):
        for route in ("/mqtt?password=synthetic-secret", "/pairing?code=123456789", "/data/state/app_key.pem", "/debug", "/../state", "/mqtt/%2e%2e"):
            status, body, _ = await self.request(route=route)
            self.assertIn(status, (400, 404))
            self.assertNotIn("synthetic-secret", body)
            self.assertNotIn("123456789", body)

    async def test_protocol_limits_and_ambiguous_framing(self):
        base = f"Host: app\r\nX-Remote-User-Id: admin\r\nX-Ingress-Path: {PREFIX}\r\n"
        cases = [
            (f"POST /mqtt/test HTTP/1.1\r\n{base}Content-Length: 8193\r\n\r\n", 413),
            (f"POST /mqtt/test HTTP/1.1\r\n{base}Content-Length: 0\r\nContent-Length: 0\r\n\r\n", 400),
            (f"POST /mqtt/test HTTP/1.1\r\n{base}Transfer-Encoding: chunked\r\n\r\n", 400),
            (f"POST /mqtt/test HTTP/1.1\r\n{base}Content-Length: 0\r\nContent-Type: application/json\r\n\r\n", 415),
            (f"PUT /mqtt/test HTTP/1.1\r\n{base}\r\n", 405),
            (f"GET / HTTP/1.1\r\n{base}X-Pad: " + "a" * 8192 + "\r\n\r\n", 431),
        ]
        for raw, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual((await self.request(raw=raw.encode()))[0], expected)

    async def test_unknown_duplicate_and_malformed_fields_rejected(self):
        for body in ("csrf_token=a&csrf_token=b", "csrf_token=%ZZ", "csrf_token=a&extra=b", "csrf_token=%00"):
            raw = (f"POST /mqtt/test HTTP/1.1\r\nHost: app\r\nX-Remote-User-Id: admin\r\nX-Ingress-Path: {PREFIX}\r\nContent-Type: application/x-www-form-urlencoded\r\nContent-Length: {len(body)}\r\n\r\n{body}").encode()
            self.assertEqual((await self.request(raw=raw))[0], 400)

    async def test_pairing_requires_explicit_approved_post_and_never_echoes_code(self):
        token = await self.token("/pairing/pair", page="/pairing")
        code = "123456789"
        with patch("commissioning.pair_code", new=AsyncMock()) as pair:
            status, body, _ = await self.request("POST", "/pairing/pair", {"csrf_token": token, "code": code, "approval": "yes"})
            self.assertEqual(status, 303)
            await self.server.pair_task
            pair.assert_awaited_once_with(self.state, code, approved=True)
            self.assertNotIn(code, body)
            # A fresh token still cannot bypass pairing rate limits.
            token = await self.token("/pairing/pair", page="/pairing")
            self.assertEqual((await self.request("POST", "/pairing/pair", {"csrf_token": token, "code": code, "approval": "yes"}))[0], 429)

    async def test_unchecked_pairing_approval_never_creates_identity(self):
        token = await self.token("/pairing/pair", page="/pairing")
        with patch("danfoss_mdg.identity.ensure_identity") as create:
            status, body, _ = await self.request("POST", "/pairing/pair", {"csrf_token": token, "code": "123456789", "approval": "no"})
            await self.server.pair_task
            status, body, _ = await self.request(route="/diagnostics")
        self.assertEqual(status, 200)
        self.assertIn("explicit approval checkbox", body)
        create.assert_not_called()
        self.assertFalse((self.state / "identity-created.json").exists())

    async def test_get_pairing_status_does_not_read_keys_or_password(self):
        state = synthetic_state(self.state / "paired")
        atomic_json(state / "settings.json", dict(OPTIONS, operation="setup"))
        self.server = ingress.IngressServer(state)
        original = Path.read_text
        def safe_read(path, *args, **kwargs):
            if path.name in ("app_key.pem", "app_cert.pem", "mqtt_password", "paired_cc.json"):
                raise AssertionError("GET tried to read credential material")
            return original(path, *args, **kwargs)
        with patch.object(Path, "read_text", new=safe_read):
            status, body, _ = await self.request(route="/pairing")
        self.assertEqual(status, 200)
        self.assertIn("Stored pairing present", body)
        self.assertNotIn('action="' + PREFIX + '/pairing/pair"', body)

    async def test_pairing_failure_and_generic_errors_do_not_leak(self):
        token = await self.token("/pairing/pair", page="/pairing")
        logs = io.StringIO()
        with patch("commissioning.pair_code", new=AsyncMock(side_effect=ValueError("secret-code-and-private-material"))), redirect_stdout(logs), redirect_stderr(logs):
            status, body, _ = await self.request("POST", "/pairing/pair", {"csrf_token": token, "code": "123456789", "approval": "yes"})
            await self.server.pair_task
            status, body, _ = await self.request(route="/diagnostics")
        self.assertEqual(status, 200)
        self.assertIn("Pairing completion is unconfirmed", body)
        self.assertNotIn("secret-code-and-private-material", body + logs.getvalue())

    async def test_monitor_mode_and_cli_lock_block_mutations(self):
        atomic_json(self.state / "settings.json", OPTIONS)
        with patch("commissioning.verify_tls", new=AsyncMock()) as tls:
            self.assertEqual(await self.server.perform("/mqtt/verify-tls", {}), "setup_required")
            tls.assert_not_called()
            atomic_json(self.state / "settings.json", dict(OPTIONS, operation="setup"))
            lock = monitor.operation_lock(self.state)
            try:
                self.assertEqual(await self.server.perform("/mqtt/verify-tls", {}), "busy")
                tls.assert_not_called()
            finally:
                os.close(lock)

    async def test_save_mqtt_private_permissions_and_no_identity_generation(self):
        source = self.state / "public-test-ca.crt"
        source.write_text(CA)
        real_save = setup.save_mqtt
        token = await self.token("/mqtt/save")
        fields = dict(csrf_token=token, mqtt_host="broker.example.invalid", mqtt_port="8883", mqtt_username="synthetic", password="synthetic-private-secret", confirmation="synthetic-private-secret")
        with patch("commissioning.save_mqtt", side_effect=lambda state, options, values: real_save(state, options, values, source)):
            status, body, _ = await self.request("POST", "/mqtt/save", fields)
        self.assertEqual(status, 200)
        self.assertNotIn(fields["password"], body)
        for name in ("mqtt_password", "mqtt-ca.crt", "mqtt-settings.json"):
            self.assertEqual((self.state / name).stat().st_mode & 0o777, 0o600)
        self.assertFalse((self.state / "app_key.pem").exists())
        self.assertNotIn("password", (self.state / "mqtt-settings.json").read_text())
        effective = monitor.options_from_file(self.state)
        self.assertFalse(effective["danfoss_allow_writes"])
        self.assertTrue(effective["mqtt_tls"])

    async def test_hostile_overlay_cannot_enable_writes_or_disable_tls(self):
        atomic_json(self.state / "mqtt-settings.json", {"danfoss_allow_writes": True})
        with self.assertRaises(ValueError):
            monitor.options_from_file(self.state)

    async def test_escaped_configuration_and_empty_secret_fields(self):
        options = dict(OPTIONS, operation="setup", mqtt_username='<script>alert("synthetic")</script>')
        atomic_json(self.state / "settings.json", options)
        status, body, _ = await self.request(route="/mqtt")
        self.assertEqual(status, 200)
        self.assertNotIn(options["mqtt_username"], body)
        self.assertIn("&lt;script&gt;", body)
        self.assertIn('name="password" type="password" value=""', body)

    async def test_cancelled_operation_releases_state_lock(self):
        started = asyncio.Event()
        async def operation(*args, **kwargs):
            started.set()
            await asyncio.Event().wait()
        with patch("commissioning.verify_tls", side_effect=operation):
            task = asyncio.create_task(self.server.perform("/mqtt/verify-tls", {}))
            await asyncio.wait_for(started.wait(), 2)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertFalse(self.server.busy)
        os.close(monitor.operation_lock(self.state))


class SharedCommissioningTests(unittest.IsolatedAsyncioTestCase):
    async def test_tls_identity_failure_never_falls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "ca.crt"
            source.write_text(CA)
            with patch("commissioning.asyncio.open_connection", new=AsyncMock(side_effect=ssl.SSLCertVerificationError())) as connect:
                with self.assertRaises(ssl.SSLCertVerificationError):
                    await setup.verify_tls(dict(OPTIONS), source)
            connect.assert_awaited_once()
            self.assertIsInstance(connect.call_args.kwargs["ssl"], ssl.SSLContext)
    async def test_tls_verification_checks_identity_without_sending_mqtt_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "ca.crt"
            source.write_text(CA)
            writer = Mock(wait_closed=AsyncMock())
            with patch("commissioning.asyncio.open_connection", new=AsyncMock(return_value=(Mock(), writer))) as connect:
                await setup.verify_tls(dict(OPTIONS), source)
            context = connect.call_args.kwargs["ssl"]
            self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
            self.assertTrue(context.check_hostname)
            self.assertEqual(connect.call_args.kwargs["server_hostname"], OPTIONS["mqtt_host"])
            writer.write.assert_not_called()
            writer.close.assert_called_once()

    async def test_mqtt_exchange_has_verified_tls_and_bounded_connack(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "ca.crt"
            source.write_text(CA)
            reader = Mock(readexactly=AsyncMock(return_value=b"\x20\x02\x00\x00"))
            writer = Mock(wait_closed=AsyncMock(), drain=AsyncMock())
            config = Mock(host="broker.example.invalid", port=8883, ca_file=str(source), username="synthetic", password="synthetic-secret")
            with patch("commissioning.asyncio.open_connection", new=AsyncMock(return_value=(reader, writer))) as connect:
                self.assertEqual(await setup.broker_connack(config), 0)
            self.assertTrue(connect.call_args.kwargs["ssl"].check_hostname)
            self.assertEqual(connect.call_args.kwargs["server_hostname"], config.host)
            reader.readexactly.assert_awaited_once_with(4)
            self.assertEqual(writer.write.call_args_list[-1].args, (b"\xe0\x00",))
            writer.close.assert_called_once()

    async def test_pairing_without_approval_or_with_local_code_never_initializes(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            with patch("danfoss_mdg.identity.ensure_identity") as create:
                with self.assertRaises(setup.SetupError):
                    await setup.pair_code(state, "123456789", approved=False)
                with self.assertRaises(setup.LocalCodeError):
                    await setup.pair_code(state, "000012345", approved=True)
                create.assert_not_called()
            self.assertEqual(list(state.iterdir()), [])

    async def test_failed_pairing_preserves_pending_identity_and_retry_reuses_it(self):
        from danfoss_mdg.readonly_transport import certificate_peer_id
        import base64
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            with patch("pair_cc.pair", new=AsyncMock(side_effect=ValueError("synthetic failure"))):
                with self.assertRaises(ValueError):
                    await setup.pair_code(state, "123456789", approved=True)
            key_before = (state / "app_key.pem").read_bytes()
            self.assertEqual(setup.pairing_status(state), "pending")
            async def finish(state, *args, **kwargs):
                der = ssl.PEM_cert_to_DER_cert((state / "app_cert.pem").read_text())
                atomic_json(state / "paired_cc.json", {"format": 1, "peer_name": certificate_peer_id(der), "certificate_der": base64.b64encode(der).decode()})
            with patch("pair_cc.pair", side_effect=finish):
                await setup.pair_code(state, "987654321", approved=True)
            self.assertEqual((state / "app_key.pem").read_bytes(), key_before)
            before = identity_hashes(state)
            self.assertEqual(setup.pairing_status(state), "stored")
            with self.assertRaises(setup.SetupError):
                await setup.pair_code(state, "123456789", approved=True)
            self.assertEqual(identity_hashes(state), before)

    async def test_broker_test_uses_saved_tls_identity_and_checks_anonymous_rejection(self):
        config = Mock()
        with patch("monitor.settings", return_value=config), patch("commissioning.broker_connack", new=AsyncMock(side_effect=[0, 5])) as conn:
            await setup.check_mqtt(dict(OPTIONS), Path("/synthetic"))
            self.assertEqual(conn.await_args_list[0].args, (config,))
            self.assertEqual(conn.await_args_list[1].kwargs, {"anonymous": True})
        for replies in ([5], [0, 0]):
            with patch("monitor.settings", return_value=config), patch("commissioning.broker_connack", new=AsyncMock(side_effect=replies)), self.assertRaises(setup.SetupError):
                await setup.check_mqtt(dict(OPTIONS), Path("/synthetic"))

    async def test_invalid_password_or_ca_does_not_write_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            for password, confirmation in (("one", "two"), ("", ""), ("x\n", "x\n")):
                with self.assertRaises(setup.SetupError):
                    setup.save_password(state, password, confirmation)
            self.assertEqual(list(state.iterdir()), [])
            ca = state / "invalid-ca.crt"
            ca.write_text("not a certificate")
            with self.assertRaises(setup.SetupError):
                setup.save_password(state, "synthetic", "synthetic", ca)
            self.assertFalse((state / "mqtt_password").exists())
            ca.write_text(CA + "\n-----BEGIN PRIVATE KEY-----\nsynthetic-key\n-----END PRIVATE KEY-----\n")
            with self.assertRaises(setup.SetupError):
                setup.public_ca(ca)

    async def test_overlay_survives_settings_refresh_and_can_be_removed_without_identity_loss(self):
        with tempfile.TemporaryDirectory() as directory:
            state = synthetic_state(Path(directory) / "state")
            before = identity_hashes(state)
            atomic_json(state / "settings.json", OPTIONS)
            connection = {"mqtt_host": "broker.invalid", "mqtt_port": 8883, "mqtt_username": "synthetic"}
            atomic_json(state / "mqtt-settings.json", connection)
            self.assertEqual(monitor.options_from_file(state)["mqtt_host"], "broker.invalid")
            atomic_json(state / "settings.json", OPTIONS)
            self.assertEqual(monitor.options_from_file(state)["mqtt_username"], "synthetic")
            setup.use_supervisor_mqtt(state)
            self.assertEqual(monitor.options_from_file(state)["mqtt_host"], OPTIONS["mqtt_host"])
            self.assertEqual(identity_hashes(state), before)


class IngressPolicyTests(unittest.TestCase):
    def test_csrf_expiry_and_bounded_store(self):
        csrf = ingress.CSRF()
        token = csrf.issue("admin", PREFIX, "/mqtt/test", 0)
        self.assertFalse(csrf.consume(token, "admin", PREFIX, "/mqtt/test", 601))
        for i in range(600):
            csrf.issue("admin", PREFIX, "/mqtt/test", 0)
        self.assertEqual(len(csrf.tokens), 512)

    def test_rate_limit_and_bucket_bounds(self):
        limits = ingress.Limits()
        self.assertTrue(limits.allow("test", 1, 60, 0))
        self.assertFalse(limits.allow("test", 1, 60, 1))
        self.assertTrue(limits.allow("test", 1, 60, 61))
        for i in range(600):
            limits.allow(("user", i), 1, 60, 61)
        self.assertLessEqual(len(limits.buckets), 512)

    def test_packaged_ingress_is_admin_only_without_host_ports_or_extra_apis(self):
        # Configuration-file check is offline; actual Supervisor enforcement
        # must additionally be tested with an administrator and non-admin user.
        root = Path(__file__).resolve().parents[1]
        source = root / "danfoss_link/config.yaml"
        if not source.is_file():
            source = Path("/verification-config.yaml")  # Read-only Docker test input.
        config = source.read_text()
        self.assertIn('version: "0.3.1"', config)
        self.assertIn("ingress: true", config)
        self.assertIn("ingress_port: 8099", config)
        self.assertIn("panel_admin: true", config)
        self.assertNotRegex(config, r"(?m)^ports:")
        for key in ("host_network", "hassio_api", "homeassistant_api", "auth_api", "docker_api"):
            self.assertIn(key + ": false", config)
