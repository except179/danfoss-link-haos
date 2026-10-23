import asyncio
import base64
import copy
import json
import os
from pathlib import Path
import shutil
import ssl
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import bootstrap
import healthcheck
import manage
import monitor
from storage import atomic_json, identity_hashes, validate_state
from danfoss_mdg.identity import ensure_identity
from danfoss_mdg.readonly_transport import PairedReadTransport, certificate_peer_id
from danfoss_readonly import ProtocolError, read_request
from mqtt_bridge import Settings, clean_world

OPTIONS = dict(operation="monitor", mqtt_host="broker.example.invalid", mqtt_port=8883,
               mqtt_username="synthetic", mqtt_tls=True, danfoss_allow_writes=False,
               poll_interval=60, topic_prefix="danfoss_link", discovery_prefix="homeassistant")
SNAPSHOT = clean_world({"allRooms": [{"id": 7, "name": "Synthetic room", "ambientTemperature": 20.5,
                                    "setpoint": {"temperature": 21}, "regulationState": "Heating"}],
                        "systemStatus": {"currentState": "Synthetic status"}, "allUnresolvedAlarms": []})


def synthetic_state(state):
    state.mkdir(mode=0o700)
    _, cert = ensure_identity(state, profile="apk")
    der = ssl.PEM_cert_to_DER_cert(cert.read_text())
    atomic_json(state / "paired_cc.json", {"format": 1, "peer_name": certificate_peer_id(der),
                "certificate_der": base64.b64encode(der).decode(), "display_name": "Synthetic CC"})
    atomic_json(state / "identity_manifest.json", {"format": 1, "sha256": identity_hashes(state)})
    atomic_json(state / "identity-created.json", {"format": 1, "identity_initialized": True})
    return state


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.state = synthetic_state(self.root / "original")

    def tearDown(self):
        self.temp.cleanup()

    def test_offline_copy_preserves_identity_and_room_ids(self):
        original = validate_state(self.state)
        atomic_json(self.state / "mqtt_discovery_rooms.json", {"controller_id": original, "room_ids": [7, 91]})
        restored = self.root / "restored"
        shutil.copytree(self.state, restored)
        self.assertEqual(validate_state(restored), original)
        self.assertEqual(identity_hashes(restored), identity_hashes(self.state))
        with patch("mqtt_bridge.load_trust", return_value=(None, None, certificate_peer_id(ssl.PEM_cert_to_DER_cert((restored / "app_cert.pem").read_text())), b"synthetic")):
            bridge = monitor.MonitorBridge(Settings("broker", username="synthetic", password="synthetic", tls=True, allow_writes=False), restored, Mock())
        self.assertEqual(bridge.known_ids, {7, 91})
        self.assertEqual(bridge.controller_id, original)

    def test_every_missing_identity_file_fails_without_regeneration(self):
        for name in ("app_key.pem", "app_cert.pem", "paired_cc.json", "identity_manifest.json", "identity-created.json"):
            with self.subTest(name=name):
                saved = (self.state / name).read_bytes()
                (self.state / name).unlink()
                with self.assertRaises((OSError, ValueError, ProtocolError)):
                    validate_state(self.state)
                self.assertFalse((self.state / name).exists())
                (self.state / name).write_bytes(saved)
                (self.state / name).chmod(0o600)

    def test_mismatched_peer_identifier_rejected(self):
        path = self.state / "paired_cc.json"
        record = json.loads(path.read_text())
        record["peer_name"] = "00:" * 19 + "00"
        atomic_json(path, record)
        atomic_json(self.state / "identity_manifest.json", {"format": 1, "sha256": identity_hashes(self.state)})
        with self.assertRaises(ValueError):
            validate_state(self.state)

    def test_key_mismatch_and_loose_permissions_rejected(self):
        other = self.root / "other"
        key, _ = ensure_identity(other, profile="apk")
        (self.state / "app_key.pem").write_bytes(key.read_bytes())
        with self.assertRaises(ValueError):
            validate_state(self.state)
        (self.state / "app_key.pem").chmod(0o644)
        with self.assertRaises(ValueError):
            validate_state(self.state)

    def test_restore_requests_ownership_only_for_private_known_files(self):
        # This sandbox cannot chown to container UID 65534. Verify requests
        # here; the real ownership transition is a required image smoke test.
        with patch("bootstrap.os.chown") as chown:
            bootstrap.restore_ownership(self.state)
        self.assertEqual(chown.call_count, 1 + len(list(self.state.iterdir())))
        for call in chown.call_args_list:
            self.assertEqual(call.args[1:3], (65534, 65534))
        for path in self.state.iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_restore_rejects_symlink_hardlink_unknown_and_loose_file(self):
        for kind in ("symlink", "hardlink", "unknown", "loose"):
            target = self.root / kind
            shutil.copytree(self.state, target)
            path = target / "runtime.json"
            if kind == "symlink":
                path.symlink_to(target / "app_key.pem")
            elif kind == "hardlink":
                os.link(target / "app_key.pem", path)
            elif kind == "unknown":
                (target / "unrecognized").write_text("synthetic")
            else:
                path.write_text("{}"); path.chmod(0o644)
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                bootstrap.restore_ownership(target)


class OptionsTests(unittest.TestCase):
    def test_unsafe_options_and_hostile_environment_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            for change in ({"danfoss_allow_writes": None}, {"danfoss_allow_writes": "false"},
                           {"mqtt_tls": False}, {"mqtt_username": ""}, {"mqtt_port": 1883.0},
                           {"topic_prefix": "#"}, {"poll_interval": 1}):
                atomic_json(state / "settings.json", OPTIONS | change)
                with self.subTest(change=change), self.assertRaises(ValueError):
                    monitor.options_from_file(state)
            atomic_json(state / "settings.json", OPTIONS)
            for env in ({"DANFOSS_ALLOW_WRITES": "true"}, {"MQTT_TLS": "false"}, {"MQTT_PASSWORD": "synthetic"}):
                with self.subTest(env=env), patch.dict(os.environ, env), self.assertRaises(ValueError):
                    monitor.options_from_file(state)

    def test_noninteractive_secret_entry_rejected(self):
        with patch("sys.stdin.isatty", return_value=False), patch("getpass.getpass") as prompt:
            with self.assertRaises(ValueError):
                manage.hidden("synthetic")
            prompt.assert_not_called()

    def test_identity_creation_not_reachable_during_normal_startup(self):
        with patch("runtime_check.check"), patch("monitor.options_from_file", return_value=OPTIONS), patch("monitor.operation_lock", return_value=None), patch("monitor.private", side_effect=FileNotFoundError), patch("danfoss_mdg.identity.ensure_identity") as create:
            self.assertEqual(monitor.main(), 1)
            create.assert_not_called()

    def test_lock_rejects_duplicate_using_same_volume(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            lock = monitor.operation_lock(state)
            try:
                with self.assertRaises(BlockingIOError):
                    monitor.operation_lock(state)
            finally:
                os.close(lock)

    def test_health_distinguishes_liveness_from_readiness(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "health.json"
            atomic_json(path, {"heartbeat": 100})
            self.assertTrue(healthcheck.healthy(path, now=110))
            self.assertFalse(healthcheck.healthy(path, now=200))
            self.assertFalse(healthcheck.healthy(path, now=90))


class ReadOnlyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = Path(self.temp.name)
        self.sdk = Mock()
        self.config = Settings("synthetic-broker", username="synthetic", password="synthetic", tls=True, allow_writes=False)
        with patch("mqtt_bridge.load_trust", return_value=(None, None, "synthetic-peer", b"synthetic")):
            self.bridge = monitor.MonitorBridge(self.config, self.state, self.sdk)
        b = self.bridge
        b.loop = asyncio.get_running_loop()
        b.refresh = asyncio.Event()
        b.stop = asyncio.Event()

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def test_local_pairing_code_rejected_without_generating_identity(self):
        with patch("manage.STATE", self.state), patch("builtins.input", return_value="PAIR NEW CLIENT"), patch("manage.hidden", return_value="000012345"), patch("danfoss_mdg.identity.ensure_identity") as create:
            with self.assertRaises(manage.LocalCodeError):
                await manage.initialize_and_pair()
            create.assert_not_called()
            self.assertFalse((self.state / "identity-created.json").exists())

    async def test_partial_initialization_never_regenerates_missing_key(self):
        atomic_json(self.state / "identity-created.json", {"format": 1, "identity_initialized": True})
        with patch("manage.STATE", self.state), patch("builtins.input", return_value="PAIR NEW CLIENT"), patch("manage.hidden", return_value="123456789"), patch("danfoss_mdg.identity.ensure_identity") as create:
            with self.assertRaises(FileNotFoundError):
                await manage.initialize_and_pair()
            create.assert_not_called()
            self.assertFalse((self.state / "app_key.pem").exists())

    async def test_only_birth_subscription_and_forged_commands_ignored(self):
        b = self.bridge
        b._connected()
        self.assertEqual(self.sdk.subscribe.call_args_list, [unittest.mock.call("homeassistant/status", qos=0)])
        with patch.object(b, "_notify") as notify:
            for retained in (False, True):
                for duplicate in (False, True):
                    b.on_message(None, None, SimpleNamespace(topic=b.base + "/room/7/temperature/set", payload=b"35", retain=retained, dup=duplicate))
            notify.assert_not_called()
        with self.assertRaises(ValueError):
            b._enqueue((7, 35))
        with self.assertRaises(ValueError):
            await b.command_worker()
        self.assertIsNone(b.queue)

    async def test_discovery_has_no_commands_and_adds_real_measurements(self):
        b = self.bridge
        b._connected()
        b.publish_snapshot(copy.deepcopy(SNAPSHOT))
        configs = [json.loads(c.args[1]) for c in self.sdk.publish.call_args_list if c.args[0].endswith("/config") and c.args[1]]
        self.assertTrue(any(c.get("device_class") == "timestamp" for c in configs))
        self.assertEqual(sum(c.get("state_class") == "measurement" for c in configs), 2)
        self.assertTrue(all("command" not in key for c in configs for key in c))
        self.assertTrue(b.report()["ready"])
        b.offline()
        self.assertFalse(b.report()["ready"])
        for call in self.sdk.publish.call_args_list:
            self.assertNotIn("temperature/set", call.args[0])

    async def test_temperature_mode_schedule_and_retained_commands_have_no_execution_path(self):
        b = self.bridge
        b._connected()
        b.publish_snapshot(copy.deepcopy(SNAPSHOT))
        published = list(self.sdk.publish.call_args_list)
        configs = [json.loads(c.args[1]) for c in published
                   if c.args[0].endswith("/config") and c.args[1]]
        climate = next(c for c in configs if "temperature_state_topic" in c)
        self.assertIn("current_temperature_topic", climate)
        self.assertIn("temperature_state_topic", climate)
        self.assertFalse(climate["optimistic"])
        self.assertNotIn("supported_features", climate)  # HA derives this; no invented override.
        self.assertTrue(all("command" not in key for config in configs for key in config))
        with patch.object(b, "_notify") as notify, patch("monitor.PairedReadTransport.connect", new=AsyncMock()) as connect:
            for topic in ("room/7/temperature/set", "room/7/mode/set", "mode/set", "schedule/set"):
                for retain in (False, True):
                    b.on_message(None, None, SimpleNamespace(topic=b.base + "/" + topic,
                                 payload=b'{"temperature":35,"mode":"away"}', retain=retain, dup=False))
            notify.assert_not_called()
            connect.assert_not_called()
        self.assertEqual(self.sdk.publish.call_args_list, published)
        self.assertIsNone(b.queue)

    async def test_rename_preserves_unique_ids_and_removal_cleans_sensors(self):
        b = self.bridge; b._connected(); b.publish_snapshot(copy.deepcopy(SNAPSHOT))
        def ids():
            return {json.loads(c.args[1])["unique_id"] for c in self.sdk.publish.call_args_list if c.args[0].endswith("/config") and c.args[1]}
        before = ids(); self.sdk.reset_mock()
        renamed = copy.deepcopy(SNAPSHOT); renamed["rooms"][0]["name"] = "Renamed synthetic room"
        b.publish_snapshot(renamed, rediscover=True)
        self.assertEqual(ids(), before)
        self.sdk.reset_mock(); b.publish_snapshot(dict(SNAPSHOT, rooms=[]))
        removed = [c.args[0] for c in self.sdk.publish.call_args_list if c.args[1] == ""]
        self.assertTrue(any("room_7_temperature/config" in t for t in removed))
        self.assertTrue(any("room_7_setpoint/config" in t for t in removed))

    async def test_transport_allows_get_and_rejects_writes_before_io(self):
        transport = PairedReadTransport(None, None)
        transport._exchange_checked = AsyncMock(return_value={})
        for method in ("PATCH", "POST", "PUT", "DELETE"):
            request = read_request(1, "/api/world")
            request["data"]["data"]["method"] = method
            with self.assertRaises(ProtocolError):
                await transport.exchange(request)
        transport._exchange_checked.assert_not_called()
        await transport.exchange(read_request(1, "/api/world"))
        transport._exchange_checked.assert_awaited_once()

    async def test_live_operation_uses_read_transport_and_closes_it(self):
        transport = Mock(); transport.close = AsyncMock()
        with patch("monitor.PairedReadTransport.connect", new=AsyncMock(return_value=transport)) as connect, patch("monitor.read_snapshot", new=AsyncMock(return_value=SNAPSHOT)):
            self.assertEqual(await monitor.read_only_cloud_operation(self.state), SNAPSHOT)
            transport.close.assert_awaited_once()
            for kwargs in ({"writes": True}, {"command": (7, 35)}):
                with self.assertRaises(ValueError):
                    await monitor.read_only_cloud_operation(self.state, **kwargs)
            connect.assert_awaited_once()

    async def test_graceful_shutdown_publishes_offline_and_stops_mqtt(self):
        b = self.bridge
        async def finish():
            b._connected()
            b.stop.set()
        with patch.object(b, "poll", side_effect=finish), patch("monitor.heartbeat", new=AsyncMock()):
            await b.run()
        self.sdk.disconnect.assert_called_once()
        self.sdk.loop_stop.assert_called_once()
        self.assertFalse(b.cloud_ready)
