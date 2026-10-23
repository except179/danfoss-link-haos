"""Optional setpoint control; generated identity, mocked cloud, no real commands."""
import asyncio
import copy
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import heating
import ingress
import monitor
import test_ingress as ingress_tests
from test_app import OPTIONS, synthetic_state
from storage import atomic_json, identity_hashes
from danfoss_client import temperature_request
from danfoss_readonly import ProtocolError, read_request
from mqtt_bridge import Settings, clean_world

ROOM = {"id": 77, "name": "Synthetic room", "minSetpoint": 6, "maxSetpoint": 25,
        "ambientTemperature": 18, "setpoint": {"temperature": 17}, "regulationState": "Heating"}


class Transport:
    def __init__(self):
        self.room = copy.deepcopy(ROOM)
        self.requests = []
        self.fail_patch = False
        self.mismatch = False
        self.patch_entered = None
        self.patch_finish = None
        self.closed = False

    async def exchange(self, request):
        self.requests.append(copy.deepcopy(request))
        body = request["data"]["data"]
        if body["method"] == "PATCH":
            if self.patch_entered is not None:
                self.patch_entered.set()
                await self.patch_finish.wait()
            if self.fail_patch:
                raise TimeoutError("synthetic secret suppressed")
            if not self.mismatch:
                self.room["setpoint"]["temperature"] = body["content"]["setpoint"]["temperature"]
            content = {"id": 77}
        elif body["uri"] == "/api/world":
            content = {"allRooms": [self.room], "systemStatus": {"currentState": "Synthetic"}, "allUnresolvedAlarms": []}
        else:
            content = [self.room]
        return {"id": request["id"], "data": {"type": "JsonWebResponse", "data": {"status": 200, "content": content}}}

    async def close(self):
        self.closed = True

    def patches(self):
        return [r for r in self.requests if r["data"]["data"]["method"] == "PATCH"]


class HeatingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = synthetic_state(Path(self.temp.name) / "state")
        atomic_json(self.state / "settings.json", dict(OPTIONS, mqtt_host="broker.invalid", danfoss_allow_writes=True))
        self.sdk = Mock()
        self.config = Settings("broker.invalid", username="synthetic", password="synthetic", tls=True, allow_writes=False)
        self.bridge = heating.HeatingBridge(self.config, self.state, self.sdk, permitted=True)
        self.bridge.loop = asyncio.get_running_loop()
        self.bridge.refresh = asyncio.Event()
        self.bridge.stop = asyncio.Event()
        self.bridge._connected()
        self.bridge.publish_snapshot(clean_world({"allRooms": [ROOM], "systemStatus": {"currentState": "Synthetic"}, "allUnresolvedAlarms": []}))
        self.transport = Transport()
        self.connect_patch = patch("heating.PairedControlTransport.connect", new=AsyncMock(return_value=self.transport))
        self.connect = self.connect_patch.start()

    async def asyncTearDown(self):
        await self.bridge.stop_commands()
        self.connect_patch.stop()
        self.temp.cleanup()

    def frame(self, **changes):
        return json.dumps(dict(generation=self.bridge.generation, sent_at=time.time(), temperature=17.5) | changes).encode()

    def send(self, payload=None, *, room=77, retained=False, duplicate=False, topic=None):
        payload = self.frame() if payload is None else payload
        self.bridge.on_message(None, None, SimpleNamespace(topic=topic or self.bridge.base + f"/room/{room}/temperature/set", payload=payload, retain=retained, dup=duplicate))

    async def drain(self):
        await asyncio.sleep(0)
        if self.bridge.command_task is not None:
            await self.bridge.command_task

    def enable(self):
        self.bridge.set_enabled(True, approved=True)

    def climate_configs(self):
        return [(c.args[0], json.loads(c.args[1])) for c in self.sdk.publish.call_args_list if "/climate/" in c.args[0] and c.args[1]]

    async def test_default_off_even_with_supervisor_permission_no_commands(self):
        self.assertFalse(self.bridge.enabled)
        self.send(b"17.5")
        await self.drain()
        self.connect.assert_not_called()
        self.assertIsNone(self.bridge.queue)
        self.assertEqual(self.sdk.subscribe.call_args_list, [unittest.mock.call("homeassistant/status", qos=0)])
        self.assertTrue(all(not any("command" in k for k in c) for _, c in self.climate_configs()))
        with self.assertRaises(ValueError):
            self.bridge.set_enabled(True)

    async def test_enabled_setpoint_is_get_patch_get_then_snapshot_with_verified_readback(self):
        before = identity_hashes(self.state)
        self.enable(); self.send(); await self.drain()
        self.assertEqual([r["data"]["data"]["method"] for r in self.transport.requests], ["GET", "PATCH", "GET", "GET"])
        self.assertEqual(self.bridge.outcome, "verified")
        self.assertEqual(self.transport.room["setpoint"]["temperature"], 17.5)
        self.assertEqual(identity_hashes(self.state), before)
        self.assertTrue(self.transport.closed)
        self.connect.assert_awaited_once_with(self.state, allow_writes=True)

    async def test_general_limits_unknown_room_nonfinite_and_bad_envelopes_rejected(self):
        self.enable()
        for value in (True, None, "17.5", 5, 36, float("nan"), float("inf")):
            self.send(self.frame(temperature=value))
        for payload in (b"17.5", b"{}", b"[]", b'{"temperature":17,"temperature":18}', b"x" * 257):
            self.send(payload)
        self.send(room=78)
        self.send(self.frame(extra="forbidden"))
        self.send(topic="watts_live/synthetic/power")
        await self.drain()
        self.connect.assert_not_called()

    async def test_actual_room_limits_missing_malformed_or_exceeded_never_patch(self):
        self.enable()
        for low, high, value in ((6, 20, 21), (None, 25, 17.5), (6, None, 17.5), (float("nan"), 25, 17.5), (25, 6, 17.5)):
            self.transport.room.update(minSetpoint=low, maxSetpoint=high)
            self.bridge.last_admitted -= 2
            self.send(self.frame(temperature=value)); await self.drain()
            self.assertEqual(self.transport.patches(), [])
            self.assertFalse(self.bridge.enabled)
            self.bridge.cloud_ready = True
            self.enable()

    async def test_retained_duplicate_stale_future_old_generation_and_replay_rejected(self):
        self.enable()
        self.send(retained=True); self.send(duplicate=True)
        self.send(self.frame(sent_at=time.time() - 31))
        self.send(self.frame(sent_at=time.time() + 10))
        self.send(self.frame(generation="old"))
        await self.drain(); self.connect.assert_not_called()
        payload = self.frame(); self.send(payload); await self.drain()
        self.bridge.last_admitted -= 2
        self.send(payload); await self.drain()
        self.assertEqual(len(self.transport.patches()), 1)

    async def test_pending_command_discarded_by_off_before_cloud_lock(self):
        self.enable()
        await self.bridge.cloud_lock.acquire()
        self.send(); await asyncio.sleep(0)
        self.bridge.set_enabled(False)
        self.bridge.cloud_lock.release()
        await self.drain()
        self.connect.assert_not_called()
        self.assertEqual(self.bridge.outcome, "discarded")

    async def test_off_during_connect_blocks_patch(self):
        self.enable()
        started, finish = asyncio.Event(), asyncio.Event()
        async def connect(*args, **kwargs):
            started.set(); await finish.wait(); return self.transport
        self.connect.side_effect = connect
        self.send(); await started.wait()
        self.bridge.set_enabled(False); finish.set(); await self.drain()
        self.assertEqual(self.transport.patches(), [])

    async def test_off_during_admitted_patch_reports_settling_and_allows_readback(self):
        self.transport.patch_entered, self.transport.patch_finish = asyncio.Event(), asyncio.Event()
        self.enable(); self.send(); await self.transport.patch_entered.wait()
        self.bridge.set_enabled(False)
        status = self.bridge.control_status()
        self.assertFalse(status["enabled"]); self.assertTrue(status["settling"])
        self.assertFalse(status["off_confirmed"])
        self.transport.patch_finish.set(); await self.drain()
        self.assertEqual(len(self.transport.patches()), 1)
        self.assertEqual(self.bridge.outcome, "verified")
        self.assertFalse(self.bridge.enabled)
        self.assertTrue(self.bridge.control_status()["off_confirmed"])
        self.send(self.frame(generation=None)); await self.drain()
        self.assertEqual(len(self.transport.patches()), 1)

    async def test_timeout_or_mismatched_readback_never_retries_patch(self):
        for timeout in (True, False):
            self.transport = Transport()
            self.connect.return_value = self.transport
            self.transport.fail_patch = timeout; self.transport.mismatch = not timeout
            self.bridge.cloud_ready = True; self.bridge.last_admitted -= 2
            self.enable(); self.send(); await self.drain()
            self.assertEqual(len(self.transport.patches()), 1)
            self.assertEqual(self.bridge.outcome, "unconfirmed")
            self.assertFalse(self.bridge.enabled)
            self.assertFalse(self.bridge.control_status()["off_confirmed"])

    async def test_configuration_loss_revokes_pending_write(self):
        for value in (False, None, "true"):
            atomic_json(self.state / "settings.json", dict(OPTIONS, mqtt_host="broker.invalid", danfoss_allow_writes=True))
            self.bridge.cloud_ready = True; self.enable()
            atomic_json(self.state / "settings.json", dict(OPTIONS, mqtt_host="broker.invalid", danfoss_allow_writes=value))
            self.send(); await self.drain()
            self.assertFalse(self.bridge.control_status()["enabled"])
            self.bridge.set_enabled(False)
        (self.state / "settings.json").unlink()
        with self.assertRaises(ValueError): self.enable()
        self.connect.assert_not_called()

    async def test_reconnect_restart_and_discovery_preserve_ids_but_require_new_activation(self):
        self.enable()
        topic, enabled = self.climate_configs()[-1]
        self.assertIn("temperature_command_topic", enabled)
        self.assertIn("now().timestamp()", enabled["temperature_command_template"])
        self.assertFalse(enabled["retain"])
        old_frame = self.frame()
        self.bridge._disconnected(); self.bridge._connected()
        self.assertFalse(self.bridge.enabled)
        self.bridge.publish_rooms(list(self.bridge.rooms.values()), rediscover=True)
        off_topic, disabled = self.climate_configs()[-1]
        self.assertEqual(topic, off_topic)
        self.assertEqual(enabled["unique_id"], disabled["unique_id"])
        self.assertEqual(enabled["device"], disabled["device"])
        self.assertEqual(enabled["temperature_state_topic"], disabled["temperature_state_topic"])
        self.assertNotIn("temperature_command_topic", disabled)
        self.enable(); self.send(old_frame); await self.drain(); self.connect.assert_not_called()
        restarted = heating.HeatingBridge(self.config, self.state, Mock(), permitted=True)
        self.assertFalse(restarted.enabled)
        self.assertIsNone(restarted.generation)

    async def test_only_bound_canonical_patch_and_room_world_reads_permitted(self):
        self.enable()
        command = dict(generation=self.bridge.generation, sent_at=time.time(), temperature=17.5, room=77, received=time.monotonic())
        gate = heating.SetpointExchange(self.transport, self.bridge, command)
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            req = temperature_request(1, 77, 17.5)
            req["data"]["data"].update(method=method, uri="/api/schedules")
            with self.assertRaises(ProtocolError): await gate.exchange(req)
        with self.assertRaises(ProtocolError): await gate.exchange(read_request(1, "/api/system/info"))
        self.assertEqual(self.transport.requests, [])

    async def test_off_discovery_refresh_after_reconnect_preserves_unavailability(self):
        self.enable()
        self.bridge._disconnected()
        self.bridge._connected()
        self.sdk.reset_mock()
        self.bridge.set_enabled(False)
        self.assertFalse(self.bridge.cloud_ready)
        for call in self.sdk.publish.call_args_list:
            self.assertTrue(call.args[0].endswith("/config"))
            self.assertNotIn("temperature_command_topic", json.loads(call.args[1]))
        with self.assertRaises(ValueError): self.enable()

    async def test_failed_activation_publish_fails_closed_and_off_always_revokes(self):
        self.sdk.publish.side_effect = OSError("synthetic secret")
        with self.assertRaises(ValueError): self.enable()
        self.assertFalse(self.bridge.enabled)
        self.assertIsNone(self.bridge.generation)
        self.assertIn(unittest.mock.call(self.bridge.base + "/room/+/temperature/set"), self.sdk.unsubscribe.call_args_list)
        self.sdk.publish.side_effect = None; self.enable()
        self.sdk.publish.side_effect = OSError("synthetic secret")
        self.sdk.unsubscribe.side_effect = OSError("synthetic unsubscribe failure")
        self.bridge.set_enabled(False)
        self.assertFalse(self.bridge.enabled)
        self.assertIsNone(self.bridge.generation)
        self.send(); await self.drain()
        self.connect.assert_not_called()

    async def test_randomness_failure_never_commits_activation_or_subscribes(self):
        self.sdk.reset_mock()
        with patch("heating.secrets.token_hex", side_effect=OSError("synthetic randomness failure")):
            with self.assertRaises(OSError): self.enable()
        self.assertFalse(self.bridge.enabled)
        self.assertIsNone(self.bridge.generation)
        self.sdk.subscribe.assert_not_called()
        self.sdk.publish.assert_not_called()

    async def test_null_generation_and_permission_read_failure_never_admit_commands(self):
        command = dict(generation=None, sent_at=time.time(), temperature=17.5,
                       room=77, received=time.monotonic())
        self.bridge.enabled = True
        self.assertFalse(self.bridge.current(command))
        self.bridge.enabled = False
        with patch("heating.options_from_file", side_effect=ValueError("synthetic invalid configuration")):
            self.assertFalse(self.bridge.permission())
            with self.assertRaises(ValueError): self.enable()
        self.connect.assert_not_called()

    async def test_confirmed_off_discards_pending_and_rejects_later_frames(self):
        self.enable()
        old_frame = self.frame()
        await self.bridge.cloud_lock.acquire()
        self.send(old_frame); await asyncio.sleep(0)
        self.bridge.set_enabled(False)
        self.assertFalse(self.bridge.control_status()["off_confirmed"])
        self.bridge.cloud_lock.release()
        await self.drain()
        self.assertTrue(self.bridge.control_status()["off_confirmed"])
        self.send(old_frame)
        self.send(self.frame(generation=None))
        await self.drain()
        self.connect.assert_not_called()
        self.assertEqual(self.transport.patches(), [])

    async def test_off_publication_failure_does_not_clear_uncertain_outcome(self):
        self.enable()
        self.bridge.outcome = "unconfirmed"
        self.sdk.publish.side_effect = OSError("synthetic publication failure")
        self.bridge.set_enabled(False)
        self.assertFalse(self.bridge.enabled)
        self.assertEqual(self.bridge.outcome, "unconfirmed")
        self.assertFalse(self.bridge.control_status()["off_confirmed"])

    async def test_bare_upstream_default_is_never_used_and_permission_requires_restart(self):
        denied = heating.HeatingBridge(self.config, self.state, Mock(), permitted=False)
        denied.connected = denied.cloud_ready = True
        with self.assertRaises(ValueError): denied.set_enabled(True, approved=True)
        for options in ({}, dict(OPTIONS, danfoss_allow_writes="false")):
            with self.assertRaises(ValueError): monitor.validate_options(options)
        self.assertFalse(self.bridge.config.allow_writes)

    async def test_controller_limits_intersect_general_limits(self):
        self.transport.room.update(minSetpoint=5, maxSetpoint=40)
        self.enable(); self.send(); await self.drain()
        self.assertEqual(len(self.transport.patches()), 1)
        self.assertEqual(self.bridge.outcome, "verified")

    async def test_real_deadline_cancels_uncertain_patch_once_and_leaves_off(self):
        self.transport.patch_entered, self.transport.patch_finish = asyncio.Event(), asyncio.Event()
        self.enable()
        with patch("heating.COMMAND_TIMEOUT", 0.02):
            self.send(); await self.drain()
        self.assertEqual(len(self.transport.patches()), 1)
        self.assertEqual(self.bridge.outcome, "unconfirmed")
        self.assertFalse(self.bridge.enabled)

    async def test_command_expires_waiting_for_cloud_serialization(self):
        self.enable()
        await self.bridge.cloud_lock.acquire()
        stamp = time.time()
        self.send(self.frame(sent_at=stamp)); await asyncio.sleep(0)
        with patch("heating.time.time", return_value=stamp + 31):
            self.bridge.cloud_lock.release()
            await self.drain()
        self.connect.assert_not_called()
        self.assertEqual(self.bridge.outcome, "discarded")

    async def test_off_before_first_snapshot_preserves_existing_discovery_records(self):
        atomic_json(self.state / "mqtt_discovery_rooms.json", {"controller_id": self.bridge.controller_id, "room_ids": [77]})
        sdk = Mock()
        new_bridge = heating.HeatingBridge(self.config, self.state, sdk, permitted=True)
        new_bridge.connected = True
        new_bridge.set_enabled(False)
        sdk.publish.assert_not_called()
        self.assertEqual(new_bridge.known_ids, {77})

    async def test_cleanup_remains_inside_cloud_serialization_lock(self):
        started, finish = asyncio.Event(), asyncio.Event()
        async def close():
            started.set(); await finish.wait()
        self.transport.close = close
        self.enable(); self.send(); await started.wait()
        self.assertTrue(self.bridge.cloud_lock.locked())
        finish.set(); await self.drain()
        self.assertFalse(self.bridge.cloud_lock.locked())

    async def test_settings_clamp_upstream_write_default_even_when_permission_true(self):
        for name, value in (("mqtt_password", "synthetic"), ("mqtt-ca.crt", (self.state / "app_cert.pem").read_text())):
            (self.state / name).write_text(value)
            (self.state / name).chmod(0o600)
        options = monitor.options_from_file(self.state)
        self.assertTrue(options["danfoss_allow_writes"])
        self.assertFalse(monitor.settings(options, self.state).allow_writes)


class HeatingIngressTests(unittest.IsolatedAsyncioTestCase):
    request = ingress_tests.IngressTests.request
    token = ingress_tests.IngressTests.token

    async def asyncSetUp(self):
        await HeatingTests.asyncSetUp(self)
        self.server = ingress.IngressServer(self.state, heating=self.bridge)

    async def asyncTearDown(self):
        await HeatingTests.asyncTearDown(self)

    async def test_admin_confirmation_on_and_off_post_redirect_no_restart(self):
        _, body, _ = await self.request(route="/heating")
        self.assertIn("Monitoring only — heating writes disabled", body)
        token = await self.token("/heating/on", page="/heating")
        status, _, headers = await self.request("POST", "/heating/on", {"csrf_token": token, "approval": "yes"})
        self.assertEqual(status, 303)
        self.assertIn(ingress_tests.PREFIX + "/heating", headers)
        self.assertTrue(self.bridge.enabled)
        _, body, _ = await self.request(route="/heating")
        self.assertIn("Heating control enabled — Home Assistant may change room target temperatures", body)
        self.assertIn("may still complete", body)
        token = await self.token("/heating/off", page="/heating")
        self.assertEqual((await self.request("POST", "/heating/off", {"csrf_token": token}))[0], 303)
        self.assertFalse(self.bridge.enabled)
        self.connect.assert_not_called()

    async def test_no_csrf_no_confirmation_replay_and_state_changing_get_denied(self):
        self.assertEqual((await self.request(route="/heating/on"))[0], 404)
        self.assertEqual((await self.request("POST", "/heating/on", {"csrf_token": "forged", "approval": "yes"}))[0], 403)
        token = await self.token("/heating/on", page="/heating")
        self.assertEqual((await self.request("POST", "/heating/on", {"csrf_token": token, "approval": "no"}))[0], 403)
        self.assertEqual((await self.request("POST", "/heating/on", {"csrf_token": token, "approval": "yes"}))[0], 403)
        self.assertFalse(self.bridge.enabled)

    async def test_off_ui_does_not_confirm_while_admitted_operation_is_settling(self):
        self.transport.patch_entered, self.transport.patch_finish = asyncio.Event(), asyncio.Event()
        self.bridge.set_enabled(True, approved=True)
        self.bridge.accept(self.bridge.base + "/room/77/temperature/set",
                           HeatingTests.frame(self), time.monotonic())
        await self.transport.patch_entered.wait()
        token = await self.token("/heating/off", page="/heating")
        self.assertEqual((await self.request("POST", "/heating/off", {"csrf_token": token}))[0], 303)
        _, body, _ = await self.request(route="/heating")
        self.assertIn("<strong>DISABLING:</strong>", body)
        self.assertNotIn("Local write admission OFF confirmed", body)
        self.transport.patch_finish.set()
        await self.bridge.command_task
        _, body, _ = await self.request(route="/heating")
        self.assertIn("Local write admission OFF confirmed", body)
        self.assertEqual(len(self.transport.patches()), 1)
        self.bridge.outcome = "unconfirmed"
        _, body, _ = await self.request(route="/heating")
        self.assertNotIn("Local write admission OFF confirmed", body)
        self.assertIn("previous physical result may be unconfirmed", body)

    async def test_untrusted_non_admin_cannot_spoof_supervisor_identity(self):
        # Supervisor itself denies non-admin users before proxying. The App
        # cannot infer roles from a user ID; no client role header is trusted.
        token = await self.token("/heating/on", page="/heating")
        fields = {"csrf_token": token, "approval": "yes"}
        status, _, _ = await self.request("POST", "/heating/on", fields, {"X-Remote-User-Id": "non-admin", "X-Remote-User-Role": "admin"}, peer="127.0.0.1")
        self.assertEqual(status, 403)
        self.assertEqual((await self.request("POST", "/heating/on", fields, {"X-Remote-User-Id": None}))[0], 403)
        self.assertFalse(self.bridge.enabled)

    async def test_off_remains_available_after_action_rate_limit(self):
        self.bridge.set_enabled(True, approved=True)
        token = await self.token("/heating/off", page="/heating")
        for _ in range(10):
            self.server.limits.allow(("actions", "admin-user"), 10, 60, time.monotonic())
        self.assertEqual((await self.request("POST", "/heating/off", {"csrf_token": token}))[0], 303)
        self.assertFalse(self.bridge.enabled)
