"""Required image test: real paho + synthetic TLS MQTT peer, no household I/O."""
import asyncio
import json
from pathlib import Path
import socket
import ssl
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import AsyncMock, patch

import monitor
from mqtt_bridge import Settings
from test_app import SNAPSHOT, synthetic_state


def encode_packet(header, body):
    length = len(body); output = bytearray([header])
    while True:
        digit = length % 128; length //= 128
        output.append(digit | (128 if length else 0))
        if not length:
            return bytes(output) + body


def exact(stream, length):
    data = bytearray()
    while len(data) < length:
        part = stream.recv(length - len(data))
        if not part:
            raise EOFError
        data.extend(part)
    return bytes(data)


class SyntheticBroker:
    def __init__(self, root):
        self.cert = root / "broker.crt"; key = root / "broker.key"
        result = subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
                "-nodes", "-days", "1", "-subj", "/CN=Synthetic MQTT broker", "-addext", "subjectAltName=IP:127.0.0.1",
                "-keyout", str(key), "-out", str(self.cert)], capture_output=True, timeout=15)
        if result.returncode:
            raise RuntimeError("Synthetic TLS fixture failed")
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.load_cert_chain(str(self.cert), str(key))
        self.socket = socket.socket(); self.socket.bind(("127.0.0.1", 0)); self.socket.listen()
        self.socket.settimeout(0.2); self.port = self.socket.getsockname()[1]
        self.stop = threading.Event(); self.subscriptions = []; self.publications = []; self.errors = []
        self.command_factory = None; self.unsubscriptions = []
        self.thread = threading.Thread(target=self.run, daemon=True); self.thread.start()

    def run(self):
        while not self.stop.is_set():
            try:
                raw, _ = self.socket.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                raw.settimeout(2)
                with self.context.wrap_socket(raw, server_side=True) as stream:
                    while not self.stop.is_set():
                        header = exact(stream, 1)[0]; length = 0; multiplier = 1
                        for _ in range(4):
                            digit = exact(stream, 1)[0]; length += (digit & 127) * multiplier
                            if not digit & 128:
                                break
                            multiplier *= 128
                        if length > 1048576:
                            raise ValueError("Synthetic packet too large")
                        body = exact(stream, length); kind = header >> 4
                        if kind == 1:
                            stream.sendall(b"\x20\x02\x00\x00")
                        elif kind == 8:
                            size = int.from_bytes(body[2:4], "big")
                            self.subscriptions.append(body[4:4 + size].decode())
                            stream.sendall(b"\x90\x03" + body[:2] + b"\x00")
                            # Malicious unsolicited retained command must have
                            # no executable path even if a broker sends it.
                            topic = b"danfoss_link/forged/room/7/temperature/set"
                            stream.sendall(encode_packet(0x31, len(topic).to_bytes(2, "big") + topic + b"35"))
                            if self.command_factory is not None:
                                for flag, command_topic, payload in self.command_factory(self.subscriptions[-1]):
                                    encoded = command_topic.encode()
                                    stream.sendall(encode_packet(flag, len(encoded).to_bytes(2, "big") + encoded + payload))
                        elif kind == 10:
                            size = int.from_bytes(body[2:4], "big")
                            self.unsubscriptions.append(body[4:4 + size].decode())
                            stream.sendall(b"\xb0\x02" + body[:2])
                        elif kind == 3:
                            size = int.from_bytes(body[:2], "big"); topic = body[2:2 + size].decode(); offset = size + 2
                            qos = (header >> 1) & 3
                            if qos:
                                packet_id = body[offset:offset + 2]; offset += 2
                                stream.sendall(b"\x40\x02" + packet_id)
                            self.publications.append((topic, body[offset:]))
                        elif kind == 12:
                            stream.sendall(b"\xd0\x00")
                        elif kind == 14:
                            break
            except (EOFError, ssl.SSLError, ConnectionError, socket.timeout):
                raw.close()
            except Exception as error:
                self.errors.append(type(error).__name__); raw.close()

    def close(self):
        self.stop.set(); self.socket.close(); self.thread.join(timeout=5)
        if self.thread.is_alive():
            raise RuntimeError("Synthetic broker did not stop")


class TLSWireTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_paho_verified_tls_discovery_and_no_command_subscription(self):
        import paho.mqtt.client  # Required, intentionally no skip fallback.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); state = synthetic_state(root / "state"); broker = SyntheticBroker(root)
            task = None
            try:
                config = Settings("127.0.0.1", broker.port, "synthetic-user", "synthetic-password", True,
                                  str(broker.cert), allow_writes=False)
                bridge = monitor.MonitorBridge(config, state)
                async def heartbeat(stop, report):
                    await stop.wait()
                with patch("monitor.read_only_cloud_operation", new=AsyncMock(return_value=SNAPSHOT)) as reads, patch("monitor.heartbeat", side_effect=heartbeat):
                    task = asyncio.create_task(bridge.run())
                    async with asyncio.timeout(10):
                        while not any(t.endswith("/diagnostics/state") for t, _ in broker.publications):
                            await asyncio.sleep(0.05)
                    self.assertEqual(broker.subscriptions, ["homeassistant/status"])
                    self.assertIsNone(bridge.queue)
                    self.assertTrue(bridge.cloud_ready)
                    for call in reads.call_args_list:
                        self.assertEqual(call.args, (state,))
                        self.assertEqual(call.kwargs, {})
                    configs = [json.loads(p) for t, p in broker.publications if t.endswith("/config") and p]
                    self.assertTrue(configs)
                    self.assertTrue(all("command" not in key for payload in configs for key in payload))
                    self.assertFalse(broker.errors)
                    bridge.stop.set(); await asyncio.wait_for(task, 10)
                    self.assertTrue(any(t.endswith("/availability") and p == b"offline" for t, p in broker.publications))
            finally:
                if task is not None and not task.done():
                    bridge.stop.set()
                    await asyncio.wait_for(task, 10)
                broker.close()

    async def test_tls_rejects_wrong_ip_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            broker = SyntheticBroker(Path(directory))
            try:
                context = ssl.create_default_context(cafile=str(broker.cert))
                with socket.create_connection(("127.0.0.1", broker.port), timeout=3) as raw:
                    with self.assertRaises(ssl.SSLCertVerificationError):
                        context.wrap_socket(raw, server_hostname="192.0.2.1")
            finally:
                broker.close()

    async def test_imported_wrong_ca_rejects_real_loopback_broker_chain(self):
        import commissioning
        from test_first_install import certificates
        from test_app import OPTIONS
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); state = synthetic_state(root / "state"); broker = SyntheticBroker(root)
            try:
                commissioning.import_ca(state, certificates()[0], approved=True)
                options = dict(OPTIONS, operation="setup", mqtt_host="127.0.0.1", mqtt_port=broker.port)
                with self.assertRaises(ssl.SSLCertVerificationError):
                    await commissioning.verify_tls(options, state=state)
                self.assertFalse(broker.subscriptions)
                self.assertFalse(broker.publications)
            finally:
                broker.close()


class HeatingTLSWireTests(unittest.IsolatedAsyncioTestCase):
    async def test_opt_in_commands_over_real_paho_tls_and_off_unsubscribes(self):
        import heating
        from test_heating import Transport, ROOM
        from mqtt_bridge import clean_world
        from storage import atomic_json
        from test_app import OPTIONS
        import time
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); state = synthetic_state(root / "state"); broker = SyntheticBroker(root)
            atomic_json(state / "settings.json", dict(OPTIONS, mqtt_host="broker.invalid", danfoss_allow_writes=True))
            config = Settings("127.0.0.1", broker.port, "synthetic-user", "synthetic-password", True, str(broker.cert), allow_writes=False)
            bridge = heating.HeatingBridge(config, state, permitted=True)
            transport = Transport()
            async def heartbeat(stop, report):
                await stop.wait()
            snapshot = clean_world({"allRooms": [ROOM], "systemStatus": {"currentState": "Synthetic"}, "allUnresolvedAlarms": []})
            def commands(topic):
                if not topic.endswith("/temperature/set"):
                    return []
                target = bridge.base + "/room/77/temperature/set"
                payload = json.dumps({"generation": bridge.generation, "sent_at": time.time(), "temperature": 17.5}).encode()
                return [(0x31, target, payload), (0x38, target, payload), (0x30, "watts_live/synthetic/power", payload), (0x30, target, payload)]
            broker.command_factory = commands
            task = None
            try:
                with patch("monitor.read_only_cloud_operation", new=AsyncMock(return_value=snapshot)), patch("monitor.heartbeat", side_effect=heartbeat), patch("heating.PairedControlTransport.connect", new=AsyncMock(return_value=transport)):
                    task = asyncio.create_task(bridge.run())
                    async with asyncio.timeout(10):
                        while not bridge.cloud_ready:
                            await asyncio.sleep(0.02)
                        bridge.set_enabled(True, approved=True)
                        while bridge.outcome != "verified":
                            await asyncio.sleep(0.02)
                    self.assertEqual(len(transport.patches()), 1)
                    self.assertEqual(set(broker.subscriptions), {"homeassistant/status", bridge.base + "/room/+/temperature/set"})
                    command_subscription = bridge.base + "/room/+/temperature/set"
                    previous_unsubscribes = broker.unsubscriptions.count(command_subscription)
                    bridge.set_enabled(False)
                    async with asyncio.timeout(10):
                        # Startup also unsubscribes; require the new OFF request
                        # to reach the broker rather than matching that old event.
                        while broker.unsubscriptions.count(command_subscription) <= previous_unsubscribes:
                            await asyncio.sleep(0.02)
                    self.assertFalse(bridge.enabled)
                    self.assertFalse(broker.errors)
                    bridge.stop.set(); await asyncio.wait_for(task, 10)
            finally:
                if task is not None and not task.done():
                    bridge.stop.set(); await asyncio.wait_for(task, 10)
                broker.close()
