"""HAOS adapter. Default monitoring uses only allowlisted GET transport."""
import asyncio
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import ssl
import sys
import time

from storage import atomic_json, private, validate_state
from mqtt_bridge import MQTTBridge, Settings, read_snapshot
from danfoss_mdg.readonly_transport import PairedReadTransport

STATE = Path("/data/state")


def options_from_file(state=STATE):
    options = json.loads(private(state / "settings.json").read_text())
    from commissioning import MQTT_KEYS
    overlay = state / "mqtt-settings.json"
    if overlay.exists() or overlay.is_symlink():
        connection = json.loads(private(overlay).read_text())
        if not isinstance(connection, dict) or set(connection) != MQTT_KEYS:
            raise ValueError("Invalid private MQTT connection settings")
        options.update(connection)
    return validate_options(options)


def validate_options(options, *, require_connection=False):
    if not isinstance(options, dict):
        raise ValueError("Invalid configuration")
    if type(options.get("danfoss_allow_writes")) is not bool or options.get("mqtt_tls") is not True:
        raise ValueError("Explicit write permission and TLS=true are required")
    if os.environ.get("DANFOSS_ALLOW_WRITES", "false") != "false":
        raise ValueError("Writes are prohibited")
    if os.environ.get("MQTT_TLS", "true") != "true" or os.environ.get("MQTT_PASSWORD"):
        raise ValueError("Use verified TLS and private file credentials")
    if options.get("operation") not in ("setup", "monitor"):
        raise ValueError("Invalid operation")
    if type(options.get("poll_interval")) is not int or not 60 <= options["poll_interval"] <= 3600:
        raise ValueError("Invalid poll interval")
    if type(options.get("mqtt_port")) is not int or not 1 <= options["mqtt_port"] <= 65535:
        raise ValueError("Invalid MQTT port")
    for name in ("topic_prefix", "discovery_prefix"):
        if not isinstance(options.get(name), str) or not re.fullmatch(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*", options[name]):
            raise ValueError("Invalid MQTT namespace")
    for name in ("mqtt_host", "mqtt_username"):
        value = options.get(name)
        # Supervisor's plain str schema accepts empty strings. Only an idle
        # setup process may be unconfigured; every connection path is strict.
        if value == "" and options["operation"] == "setup" and not require_connection:
            continue
        if not isinstance(value, str) or not 1 <= len(value) <= 253 or not value.isprintable() or value != value.strip():
            raise ValueError("Broker address and authentication are required")
    return options


def settings(options, state=STATE):
    validate_options(options, require_connection=True)
    password = private(state / "mqtt_password", limit=1024).read_text()
    if not 1 <= len(password) <= 1024 or not password.isprintable():
        raise ValueError("Invalid private MQTT password")
    ca = private(state / "mqtt-ca.crt")
    # Explicit trust store; CERT_REQUIRED and identity checking are mandatory.
    context = ssl.create_default_context(cafile=str(ca))
    if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
        raise ValueError("TLS verification is required")
    return Settings(host=options["mqtt_host"], port=options["mqtt_port"],
                    username=options["mqtt_username"], password=password, tls=True,
                    ca_file=str(ca), prefix=options["topic_prefix"],
                    discovery_prefix=options["discovery_prefix"],
                    poll_interval=options["poll_interval"], allow_writes=False)


def operation_lock(state=STATE):
    fd = os.open(state / "operation.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BaseException:
        os.close(fd)
        raise
    return fd


async def read_only_cloud_operation(state, writes=False, command=None):
    if writes is not False or command is not None:
        raise ValueError("Heating commands are prohibited")
    async with asyncio.timeout(75):
        transport = await PairedReadTransport.connect(state)
        try:
            return await read_snapshot(transport)
        finally:
            await transport.close()


class MonitorBridge(MQTTBridge):
    def __init__(self, config, state, mqtt_client=None):
        if config.allow_writes is not False or config.tls is not True or not config.username or not config.password:
            raise ValueError("Unsafe monitoring configuration")
        super().__init__(config, state, mqtt_client)
        self.last_success = None
        self.phase = "connecting"

    def on_message(self, client, userdata, message):
        if message.topic == self.config.discovery_prefix + "/status" and message.payload == b"online":
            self._notify(self._rediscover)

    def _enqueue(self, *args):
        raise ValueError("No command queue exists in this App")

    async def command_worker(self):
        raise ValueError("No command worker exists in this App")

    def _connected(self):
        # Do not inherit the conditional temperature subscription.
        self.connected = True
        self.cloud_ready = False
        self.epoch += 1
        self.published_configs.clear()
        self.force_discovery = True
        self.client.publish(self.base + "/availability", "offline", qos=1, retain=True)
        self.client.subscribe(self.config.discovery_prefix + "/status", qos=0)
        self.refresh.set()

    def publish_snapshot(self, snapshot, *, rediscover=False):
        if not self.connected:
            return
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        current_ids = {room["id"] for room in snapshot["rooms"]}
        for removed in self.known_ids - current_ids:
            for field in ("temperature", "setpoint"):
                key = f"room_{removed}_{field}"
                self.client.publish(f"{self.config.discovery_prefix}/sensor/danfoss_link_{self.controller_id}/{key}/config",
                                    "", qos=1, retain=True)
                self.published_configs.pop("monitor_" + key, None)
        # Upstream publishes valid climate and alarms. 'heat' is the supported
        # HVAC mode and must never be presented as observed Manual/Schedule.
        super().publish_snapshot(snapshot, rediscover=rediscover)
        self.last_success = timestamp
        self.phase = "ready"
        device = {"identifiers": ["danfoss_link_" + self.controller_id],
                  "name": "Danfoss Link CC", "manufacturer": "Danfoss", "model": "Link CC"}
        entities = [("last_success", "Last successful CC read", self.base + "/diagnostics/state",
                     "{{ value_json.last_success }}", {"device_class": "timestamp"})]
        for room in snapshot["rooms"]:
            for field, label in (("temperature", "Current temperature"), ("setpoint", "Target temperature")):
                entities.append((f"room_{room['id']}_{field}", room["name"] + " " + label,
                                 self.base + f"/room/{room['id']}/state",
                                 "{{ value_json." + field + " if value_json." + field + " is not none else 'None' }}",
                                 {"device_class": "temperature", "unit_of_measurement": "°C", "state_class": "measurement"}))
        for key, name, topic, template, extra in entities:
            config = dict(name=name, unique_id=f"danfoss_link_{self.controller_id}_{key}",
                          device=device, state_topic=topic, value_template=template,
                          availability_topic=self.base + "/availability",
                          expire_after=max(180, self.config.poll_interval * 3), **extra)
            payload = json.dumps(config, ensure_ascii=True, allow_nan=False)
            cache_key = "monitor_" + key
            if rediscover or self.published_configs.get(cache_key) != payload:
                self.client.publish(f"{self.config.discovery_prefix}/sensor/danfoss_link_{self.controller_id}/{key}/config",
                                    payload, qos=1, retain=True)
                self.published_configs[cache_key] = payload
        self.client.publish(self.base + "/diagnostics/state", json.dumps({"last_success": timestamp}), qos=1, retain=True)

    def offline(self):
        self.phase = "unavailable"
        return super().offline()

    async def controller_read(self):
        return await read_only_cloud_operation(self.state)

    async def stop_commands(self):
        pass

    async def poll(self):
        while not self.stop.is_set():
            self.refresh.clear()
            if self.connected:
                try:
                    # Recheck disk identity on every poll. Missing/altered state
                    # is fatal; cloud/network errors remain recoverable.
                    validate_state(self.state)
                except Exception:
                    self.offline()
                    self.stop.set()
                    raise ValueError("Identity validation failed; investigate") from None
                try:
                    snapshot = await self.controller_read()
                    self.publish_snapshot(snapshot, rediscover=self.force_discovery)
                    self.force_discovery = False
                except Exception:
                    self.offline()
                    print("Controller read unavailable; no writes attempted", flush=True)
            try:
                await asyncio.wait_for(self.refresh.wait(), self.config.poll_interval)
            except TimeoutError:
                pass

    async def run(self):
        self.loop = asyncio.get_running_loop()
        self.refresh = asyncio.Event()
        self.stop = asyncio.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            self.loop.add_signal_handler(sig, self.stop.set)
        self.client.connect_async(self.config.host, self.config.port, keepalive=30)
        self.client.loop_start()
        tasks = [asyncio.create_task(self.poll()), asyncio.create_task(heartbeat(self.stop, lambda: self.report()))]
        # A failed task must stop the service; do not leave a live MQTT thread
        # advertising healthy process liveness after poll failure.
        def task_done(task):
            if not task.cancelled() and task.exception() is not None:
                self.stop.set()
        for task in tasks:
            task.add_done_callback(task_done)
        failed = False
        try:
            await self.stop.wait()
        finally:
            await self.stop_commands()
            publication = self.offline()
            if publication is not None:
                try:
                    # Shutdown only: paho's own network thread handles ACKs.
                    # Keep this bounded and avoid an asyncio executor solely
                    # for teardown (which adds another thread-join lifecycle).
                    publication.wait_for_publish(3)
                except Exception:
                    pass
            for task in tasks:
                task.cancel()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            failed = any(isinstance(result, Exception) for result in results)
            self.client.disconnect()
            self.client.loop_stop()
            atomic_json(self.state / "runtime.json", self.report())
        if failed:
            raise ValueError("Monitoring task stopped")

    def report(self):
        return {"phase": self.phase, "mqtt_connected": self.connected,
                "ready": self.connected and self.cloud_ready,
                "last_success": self.last_success, "writes_enabled": False}


async def heartbeat(stop, report, state=STATE):
    while not stop.is_set():
        atomic_json(Path("/tmp/danfoss-health.json"), {"heartbeat": time.monotonic()})
        atomic_json(state / "runtime.json", report())
        try:
            await asyncio.wait_for(stop.wait(), 10)
        except TimeoutError:
            pass


async def setup_wait(state=STATE):
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    print("Setup mode: no automatic MQTT or Danfoss connections; use Open Web UI for commissioning", flush=True)
    await heartbeat(stop, lambda: {"phase": "setup", "ready": False, "writes_enabled": False}, state)


async def with_ingress(worker, heating=None):
    from ingress import IngressServer
    async with IngressServer(STATE, heating=heating):
        await worker()


def main():
    lock = None
    try:
        os.umask(0o077)
        from runtime_check import check
        check()
        options = options_from_file()
        if options["operation"] == "setup":
            asyncio.run(with_ingress(setup_wait))
            return 0
        lock = operation_lock()
        private(STATE / "identity-created.json")
        validate_state(STATE)
        from heating import HeatingBridge
        bridge = HeatingBridge(settings(options), STATE, permitted=options["danfoss_allow_writes"])
        asyncio.run(with_ingress(bridge.run, heating=bridge))
        return 0
    except Exception:
        print("App stopped safely: verify private identity, TLS and configuration; details suppressed", file=sys.stderr)
        return 1
    finally:
        if lock is not None:
            os.close(lock)


if __name__ == "__main__":
    raise SystemExit(main())
