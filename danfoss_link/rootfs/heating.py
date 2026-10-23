"""Optional, process-local setpoint permission; no persisted ON state or retries.

Upstream remains unchanged. Only its canonical setpoint client/transport is used.
Supervisor permission AND a confirmed Ingress activation are required. MQTT is
an authenticated broker boundary, not per-message proof of a Home Assistant user.
"""
import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import json
import re
import secrets
import time

from danfoss_client import DanfossClient, numeric, temperature_request
from danfoss_mdg.control_transport import PairedControlTransport
from danfoss_readonly import ProtocolError, read_request, response_content
from mqtt_bridge import discovery, read_snapshot
from monitor import MonitorBridge, options_from_file
from storage import atomic_json, validate_state

MAX_AGE = 30
COMMAND_TIMEOUT = 75


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate field")
        result[key] = value
    return result


class SetpointExchange:
    """Second allowlist, bound to one admitted command and fresh raw room limits."""
    def __init__(self, transport, bridge, command):
        self.transport, self.bridge, self.command = transport, bridge, command
        self.limits = None
        self.patch_started = False

    async def exchange(self, request):
        body = request.get("data", {}).get("data", {})
        if body.get("method") == "GET":
            uri = body.get("uri")
            if uri not in ("/api/rooms", "/api/world") or request != read_request(request.get("id"), uri):
                raise ProtocolError("Read rejected")
            result = await self.transport.exchange(request)
            if uri == "/api/rooms":
                rooms = response_content(result, request["id"])
                if not isinstance(rooms, list) or any(not isinstance(r, dict) or type(r.get("id")) is not int for r in rooms):
                    raise ProtocolError("Invalid room limits")
                matches = [r for r in rooms if r["id"] == self.command["room"]]
                if len(matches) != 1:
                    raise ProtocolError("Unknown or ambiguous room")
                low, high = matches[0].get("minSetpoint"), matches[0].get("maxSetpoint")
                if not numeric(low) or not numeric(high) or not low <= high or max(6, low) > min(35, high):
                    raise ProtocolError("Explicit room limits required")
                self.limits = (max(6, low), min(35, high))
            return result
        expected = temperature_request(request.get("id"), self.command["room"], self.command["temperature"])
        if request != expected or self.patch_started or not self.bridge.current(self.command):
            raise ProtocolError("Write rejected")
        if self.limits is None or not self.limits[0] <= self.command["temperature"] <= self.limits[1]:
            raise ProtocolError("Room limits rejected")
        # Admission cutoff: OFF can reject any PATCH not yet admitted here. Once
        # admitted, network cancellation cannot establish whether the CC applied it.
        self.patch_started = True
        self.bridge.outcome = "in_flight"
        return await self.transport.exchange(request)


class HeatingBridge(MonitorBridge):
    def __init__(self, config, state, mqtt_client=None, *, permitted=False):
        super().__init__(config, state, mqtt_client)
        self.permitted = permitted is True
        self.enabled = False
        self.generation = None
        self.changed_at = None
        self.outcome = "none"
        self.active_command = None
        self.command_task = None
        self.cloud_lock = asyncio.Lock()
        self.have_snapshot = False
        self.last_sent = {}
        self.last_admitted = float("-inf")

    def permission(self):
        try:
            options = options_from_file(self.state)
            return self.permitted and options["operation"] == "monitor" and options["danfoss_allow_writes"] is True
        except Exception:
            return False

    def set_enabled(self, enabled, *, approved=False):
        if type(enabled) is not bool:
            raise ValueError("Invalid control state")
        if enabled:
            if approved is not True or not self.permission() or not self.connected or not self.cloud_ready:
                raise ValueError("Control permission or readiness missing")
            if self.command_task is not None and not self.command_task.done():
                raise ValueError("Previous operation still settling")
            # A second ON request cannot replace an active generation.
            if self.enabled:
                raise ValueError("Already enabled")
        # Randomness must succeed before any activation state is committed.
        generation = secrets.token_hex(16) if enabled else None
        self.enabled = enabled
        self.generation = generation
        self.last_sent.clear()
        self.changed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if self.connected:
            try:
                if enabled:
                    self.client.subscribe(self.base + "/room/+/temperature/set", qos=0)
                else:
                    self.client.unsubscribe(self.base + "/room/+/temperature/set")
                if self.have_snapshot:
                    self.publish_rooms(list(self.rooms.values()), rediscover=True, state_update=False)
            except Exception:
                self.enabled = False
                self.generation = None
                if self.outcome != "unconfirmed":
                    self.outcome = "disabled_discovery_pending"
                self.force_discovery = True
                # A subscription may have succeeded before discovery failed.
                # Local gates are already OFF even if unsubscribe also fails.
                try:
                    self.client.unsubscribe(self.base + "/room/+/temperature/set")
                except Exception:
                    pass
                if self.refresh is not None:
                    self.refresh.set()
                if enabled:
                    raise ValueError("Activation failed safely") from None

    def revoke(self):
        if self.enabled:
            self.set_enabled(False)

    def current(self, command):
        return (self.enabled and isinstance(self.generation, str)
                and self.permission() and self.connected and self.cloud_ready
                and command["generation"] == self.generation
                and command["room"] in self.rooms
                and 0 <= time.time() - command["sent_at"] <= MAX_AGE
                and 0 <= time.monotonic() - command["received"] <= MAX_AGE)

    def _connected(self):
        # Reconnect/start never restores an activation or old discovery template.
        self.enabled = False
        self.generation = None
        self.last_sent.clear()
        super()._connected()
        self.client.unsubscribe(self.base + "/room/+/temperature/set")

    def _disconnected(self):
        self.enabled = False
        self.generation = None
        self.last_sent.clear()
        self.changed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        super()._disconnected()

    def offline(self):
        self.revoke()
        return super().offline()

    def on_message(self, client, userdata, message):
        if message.topic == self.config.discovery_prefix + "/status" and message.payload == b"online":
            return super().on_message(client, userdata, message)
        if not self.enabled or message.retain or message.dup or not isinstance(message.payload, bytes) or not 1 <= len(message.payload) <= 256:
            return
        self._notify(self.accept, message.topic, message.payload, time.monotonic())

    def accept(self, topic, payload, received):
        try:
            match = re.fullmatch(re.escape(self.base) + r"/room/(0|[1-9][0-9]{0,9})/temperature/set", topic)
            if match is None:
                return
            fields = json.loads(payload.decode("ascii"), object_pairs_hook=unique_object)
            if not isinstance(fields, dict) or set(fields) != {"generation", "sent_at", "temperature"}:
                return
            room = int(match[1])
            command = dict(fields, room=room, received=received)
            if not numeric(fields["temperature"]) or not 6 <= fields["temperature"] <= 35 or not numeric(fields["sent_at"]):
                return
            if not self.current(command) or fields["sent_at"] <= self.last_sent.get(room, float("-inf")):
                return
            self.last_sent[room] = fields["sent_at"]
            # No deferred queue. At most one operation; extra messages are dropped.
            if self.command_task is not None and not self.command_task.done():
                return
            if time.monotonic() - self.last_admitted < 2:
                return
            self.last_admitted = time.monotonic()
            self.outcome = "pending"
            self.command_task = asyncio.create_task(self.execute(command))
        except (ValueError, TypeError, UnicodeError):
            return

    async def execute(self, command):
        try:
            async with self.cloud_lock:
                await self.execute_locked(command)
        except asyncio.CancelledError:
            # Cancellation while waiting for the lock admitted no network write.
            self.outcome = "discarded"

    async def execute_locked(self, command):
        transport = None
        self.active_command = command
        try:
            if not self.current(command):
                self.outcome = "discarded"
                return
            validate_state(self.state)
            async with asyncio.timeout(COMMAND_TIMEOUT):
                transport = await PairedControlTransport.connect(self.state, allow_writes=True)
                if not self.current(command):
                    self.outcome = "discarded"
                    return
                guarded = SetpointExchange(transport, self, command)
                await DanfossClient(guarded, allow_writes=True).set_temperature(command["room"], command["temperature"])
                # get_rooms readback in the upstream client is mandatory;
                # publishing a broker ACK never establishes CC success.
                self.outcome = "verified"
                self.publish_snapshot(await read_snapshot(guarded), rediscover=self.force_discovery)
                self.force_discovery = False
        except (Exception, asyncio.CancelledError):
            self.outcome = "unconfirmed"
            try:
                self.offline()
            except Exception:
                self.enabled = False
                self.generation = None
            if self.refresh is not None:
                self.refresh.set()
            # Do not retry PATCH. A later poll uses read-only transport.
        finally:
            if transport is not None:
                try:
                    async with asyncio.timeout(5):
                        await transport.close()
                except Exception:
                    pass
            self.active_command = None

    async def controller_read(self):
        async with self.cloud_lock:
            if self.enabled and not self.permission():
                self.revoke()
            return await super().controller_read()

    async def stop_commands(self):
        self.revoke()
        if self.command_task is not None and not self.command_task.done():
            self.command_task.cancel()
            await asyncio.gather(self.command_task, return_exceptions=True)

    def publish_snapshot(self, snapshot, *, rediscover=False):
        self.have_snapshot = True
        return super().publish_snapshot(snapshot, rediscover=rediscover)

    def publish_rooms(self, rooms, *, rediscover=False, state_update=True):
        """Same upstream state/identity contract, with a supported command template."""
        if not self.connected:
            return
        current = {r["id"]: r for r in rooms}
        for room_id in self.known_ids - current.keys():
            self.client.publish(f"{self.config.discovery_prefix}/climate/danfoss_link_{self.controller_id}/room_{room_id}/config", "", qos=1, retain=True)
            self.published_configs.pop(room_id, None)
            self.client.publish(self.base + f"/room/{room_id}/state", "", qos=1, retain=True)
        self.rooms = current
        if self.known_ids != set(current):
            atomic_json(self.discovery_record, {"controller_id": self.controller_id, "room_ids": sorted(current)})
            self.known_ids = set(current)
        writable = self.enabled and self.permission()
        for room in rooms:
            topic, config = discovery(replace(self.config, allow_writes=writable), self.controller_id, room)
            if writable:
                config["temperature_command_template"] = ("{{ {'temperature': value | float, 'sent_at': now().timestamp(), 'generation': '" + self.generation + "'} | tojson }}")
            text = json.dumps(config, separators=(",", ":"), allow_nan=False)
            if rediscover or self.published_configs.get(room["id"]) != text:
                self.client.publish(topic, text, qos=1, retain=True)
                self.published_configs[room["id"]] = text
            if state_update:
                self.client.publish(self.base + f"/room/{room['id']}/state", json.dumps({"temperature": room["temperature"], "setpoint": room["setpoint"], "mode": "heat", "action": room.get("action")}, separators=(",", ":"), allow_nan=False), qos=1, retain=True)
        # A mode-only discovery refresh must never make cached telemetry fresh
        # or turn availability online after a disconnect/read failure.
        if state_update:
            self.cloud_ready = True
            self.client.publish(self.base + "/availability", "online", qos=1, retain=True)

    def control_status(self):
        permission = self.permission()
        settling = self.command_task is not None and not self.command_task.done()
        return {"enabled": self.enabled and permission, "permitted": permission,
                "changed_at": self.changed_at, "outcome": self.outcome,
                "settling": settling,
                # This confirms local write admission only, not reversal of a
                # previous physical change or an uncertain remote operation.
                "off_confirmed": not self.enabled and not settling and self.outcome != "unconfirmed",
                "ready": self.connected and self.cloud_ready}

    def report(self):
        return dict(super().report(), writes_enabled=self.enabled and self.permission())
