"""Service-owned pairing jobs: only synthetic identities, no sockets or cloud."""
import asyncio
import base64
import os
from pathlib import Path
import shutil
import ssl
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

import commissioning as setup
import ingress
import monitor
from storage import atomic_json, identity_hashes, validate_state
from test_app import OPTIONS, synthetic_state
import test_ingress as ingress_tests
from test_ingress import PREFIX, Writer
from danfoss_mdg.readonly_transport import certificate_peer_id


async def save_peer(state, *args, **kwargs):
    """Fake authenticated native pairing completion using a generated test cert."""
    der = ssl.PEM_cert_to_DER_cert((state / "app_cert.pem").read_text())
    atomic_json(state / "paired_cc.json", {"format": 1,
                "peer_name": certificate_peer_id(der),
                "certificate_der": base64.b64encode(der).decode()})


class PairingLifecycleTests(unittest.IsolatedAsyncioTestCase):
    request = ingress_tests.IngressTests.request
    token = ingress_tests.IngressTests.token

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.state = self.root / "state"
        self.state.mkdir(mode=0o700)
        atomic_json(self.state / "settings.json", dict(OPTIONS, operation="setup",
                    mqtt_host="broker.invalid", mqtt_username="synthetic"))
        self.server = ingress.IngressServer(self.state)

    async def asyncTearDown(self):
        if self.server.pairing_running():
            self.server.pair_task.cancel()
            await asyncio.gather(self.server.pair_task, return_exceptions=True)
        self.temp.cleanup()

    async def submit(self, *, stale_form=False):
        token = (self.server.csrf.issue("admin-user", PREFIX, "/pairing/pair", ingress.time.monotonic())
                 if stale_form else await self.token("/pairing/pair", page="/pairing"))
        fields = {"csrf_token": token, "code": "123456789", "approval": "yes"}
        return await self.request("POST", "/pairing/pair", fields)

    def save_complete_fixture(self):
        fixture = synthetic_state(self.root / "finished")
        for path in fixture.iterdir():
            shutil.copy2(path, self.state / path.name)

    async def test_long_pair_redirects_immediately_refresh_is_passive_and_replay_cannot_restart(self):
        started, finish = asyncio.Event(), asyncio.Event()
        async def pair(*args, **kwargs):
            started.set()
            await finish.wait()
            self.save_complete_fixture()
        token = await self.token("/pairing/pair", page="/pairing")
        fields = {"csrf_token": token, "code": "123456789", "approval": "yes"}
        with patch("commissioning.pair_code", side_effect=pair) as operation:
            status, body, headers = await self.request("POST", "/pairing/pair", fields)
            self.assertEqual(status, 303)
            self.assertIn("Location: " + PREFIX + "/diagnostics", headers)
            await asyncio.wait_for(started.wait(), 5)
            self.assertFalse(self.server.pair_task.done())
            for prefix in (PREFIX, "/api/hassio_ingress/new-synthetic-session"):
                status, body, _ = await self.request(route="/diagnostics", headers={"X-Ingress-Path": prefix})
                self.assertEqual(status, 200)
                self.assertIn('http-equiv="refresh"', body)
                self.assertIn(prefix + "/diagnostics", body)
                self.assertIn("Completion is not yet confirmed", body)
                self.assertNotIn(fields["code"], body)
            # Reproduce the old rejection mechanism without starting a second job.
            status, body, _ = await self.request("POST", "/pairing/pair", fields)
            self.assertEqual(status, 403)
            self.assertIn("earlier pairing may still be running or saved", body)
            self.assertNotIn("Pairing did not complete", body)
            finish.set()
            await self.server.pair_task
            operation.assert_awaited_once()
        status, body, _ = await self.request(route="/diagnostics")
        self.assertEqual(status, 200)
        self.assertIn("Pairing is complete", body)
        self.assertNotIn('http-equiv="refresh"', body)
        self.assertEqual(self.server.last["result"], "paired")
        self.assertFalse(self.server.busy)

    async def test_disconnect_after_pairing_saved_does_not_change_outcome(self):
        server = self.server
        class DisconnectedWriter(Writer):
            async def drain(self):
                await server.pair_task
                raise ConnectionResetError("synthetic disconnect")
            async def wait_closed(self):
                raise ConnectionResetError("synthetic disconnect")
        async def pair(*args, **kwargs):
            self.save_complete_fixture()
        token = await self.token("/pairing/pair", page="/pairing")
        with patch("commissioning.pair_code", side_effect=pair), patch("test_ingress.Writer", DisconnectedWriter):
            status, _, _ = await self.request("POST", "/pairing/pair", {"csrf_token": token, "code": "123456789", "approval": "yes"})
        self.assertEqual(status, 303)
        self.assertEqual(self.server.last["result"], "paired")
        validate_state(self.state)
        self.assertIn("Pairing is complete", (await self.request(route="/diagnostics"))[1])

    async def test_disconnect_before_completion_leaves_service_job_running(self):
        finish = asyncio.Event()
        async def pair(*args, **kwargs):
            await finish.wait()
            self.save_complete_fixture()
        class DisconnectedWriter(Writer):
            async def drain(self):
                raise BrokenPipeError()
        token = await self.token("/pairing/pair", page="/pairing")
        with patch("commissioning.pair_code", side_effect=pair), patch("test_ingress.Writer", DisconnectedWriter):
            await self.request("POST", "/pairing/pair", {"csrf_token": token, "code": "123456789", "approval": "yes"})
            self.assertTrue(self.server.pairing_running())
            finish.set()
            await self.server.pair_task
        self.assertEqual(self.server.last["result"], "paired")

    async def test_timeout_preserves_pending_identity_then_explicit_retry_reuses_it(self):
        async def hang(*args, **kwargs):
            await asyncio.Event().wait()
        with patch("pair_cc.pair", side_effect=hang), patch("commissioning.PAIR_TIMEOUT", 0.01):
            await self.submit()
            await self.server.pair_task
        self.assertEqual(self.server.last["result"], "timeout")
        self.assertEqual(setup.pairing_status(self.state), "pending")
        key = (self.state / "app_key.pem").read_bytes()
        body = (await self.request(route="/diagnostics"))[1]
        self.assertIn("timed out", body)
        self.assertIn("Pending identity", body)
        # Simulate waiting out the rate window; production limits stay unchanged.
        self.server.limits = ingress.Limits()
        with patch("pair_cc.pair", side_effect=save_peer):
            await self.submit()
            await self.server.pair_task
        self.assertEqual(self.server.last["result"], "paired")
        self.assertEqual((self.state / "app_key.pem").read_bytes(), key)
        validate_state(self.state)

    async def test_post_commit_timeout_or_cleanup_error_reports_valid_saved_state(self):
        self.save_complete_fixture()
        before = identity_hashes(self.state)
        for error in (TimeoutError(), OSError("synthetic secret")):
            with patch("commissioning.pair_code", new=AsyncMock(side_effect=error)):
                self.assertEqual(await self.server.perform("/pairing/pair", {"code": "123456789", "approval": "yes"}), "paired")
            self.assertEqual(identity_hashes(self.state), before)

    async def test_existing_pair_is_verified_without_cloud_or_identity_replacement(self):
        self.save_complete_fixture()
        before = identity_hashes(self.state)
        def verify_while_locked(state):
            with self.assertRaises(BlockingIOError):
                monitor.operation_lock(state)
            return validate_state(state)
        with patch("pair_cc.pair", new=AsyncMock()) as pair, patch("danfoss_mdg.identity.ensure_identity") as create, \
                patch("ingress.validate_state", side_effect=verify_while_locked) as verify:
            await self.submit(stale_form=True)
            await self.server.pair_task
        pair.assert_not_called()
        create.assert_not_called()
        verify.assert_called_once_with(self.state)
        self.assertEqual(self.server.last["result"], "paired")
        self.assertEqual(identity_hashes(self.state), before)

    async def test_incomplete_saved_pin_is_not_blessed_repaired_or_repaired_remotely(self):
        self.save_complete_fixture()
        (self.state / "identity_manifest.json").unlink()
        before = identity_hashes(self.state)
        with patch("pair_cc.pair", new=AsyncMock()) as pair, patch("danfoss_mdg.identity.ensure_identity") as create:
            await self.submit(stale_form=True)
            await self.server.pair_task
        pair.assert_not_called()
        create.assert_not_called()
        self.assertFalse((self.state / "identity_manifest.json").exists())
        self.assertEqual(identity_hashes(self.state), before)
        self.assertEqual(self.server.last["result"], "identity_invalid")
        body = (await self.request(route="/pairing"))[1]
        self.assertIn("Incomplete or invalid identity", body)
        self.assertNotIn('action="' + PREFIX + '/pairing/pair"', body)

    async def test_concurrent_actions_and_second_admin_cannot_start_a_second_operation(self):
        started, finish = asyncio.Event(), asyncio.Event()
        async def pair(*args, **kwargs):
            started.set()
            await finish.wait()
        with patch("commissioning.pair_code", side_effect=pair) as operation:
            await self.submit()
            await asyncio.wait_for(started.wait(), 5)
            other_token = self.server.csrf.issue("other-admin", PREFIX, "/pairing/pair", ingress.time.monotonic())
            status, body, _ = await self.request("POST", "/pairing/pair",
                        {"csrf_token": other_token, "code": "987654321", "approval": "yes"},
                        {"X-Remote-User-Id": "other-admin"})
            self.assertEqual(status, 200)
            self.assertIn("holds the state lock", body)
            self.assertEqual(await self.server.perform("/mqtt/defaults", {}), "busy")
            with self.assertRaises(BlockingIOError):
                monitor.operation_lock(self.state)
            finish.set()
            await self.server.pair_task
            operation.assert_awaited_once()
        self.assertEqual(self.server.last["result"], "pair_unconfirmed")

    async def test_shutdown_cancels_job_releases_lock_and_restart_shows_pending_state(self):
        started = asyncio.Event()
        async def hang(*args, **kwargs):
            started.set()
            await asyncio.Event().wait()
        with patch("pair_cc.pair", side_effect=hang):
            await self.submit()
            await asyncio.wait_for(started.wait(), 5)
            self.server.server = Mock(wait_closed=AsyncMock())
            await self.server.__aexit__(None, None, None)
        self.assertFalse(self.server.busy)
        os.close(monitor.operation_lock(self.state))
        before = (self.state / "app_key.pem").read_bytes()
        self.server = ingress.IngressServer(self.state)
        with patch("pair_cc.pair", new=AsyncMock()) as pair:
            body = (await self.request(route="/diagnostics"))[1]
        pair.assert_not_called()
        self.assertIn("Pending identity", body)
        self.assertEqual((self.state / "app_key.pem").read_bytes(), before)

    async def test_monitor_mode_acknowledgement_cannot_start_pairing_or_leave_running_status(self):
        atomic_json(self.state / "settings.json", OPTIONS)
        with patch("commissioning.pair_code", new=AsyncMock()) as pair:
            await self.submit()
            await self.server.pair_task
        pair.assert_not_called()
        self.assertEqual(self.server.last["result"], "setup_required")
        self.assertFalse(self.server.pairing_running())
