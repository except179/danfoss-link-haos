"""Shared CLI/Ingress commissioning operations; no HTTP or automatic network I/O."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import struct
import subprocess
import time
import uuid

from storage import atomic_json, identity_hashes, private, validate_keypair, validate_state

CA_SOURCE = Path("/config/mqtt-ca.crt")
MQTT_KEYS = frozenset({"mqtt_host", "mqtt_port", "mqtt_username"})
PAIR_TIMEOUT = 180
IMPORT_CA_LIMIT = 16384


class LocalCodeError(ValueError):
    pass


class SetupError(ValueError):
    """Only fixed public error codes cross the UI boundary."""
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def write_secret(path, value):
    temporary = path.with_name(path.name + ".new")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w") as file:
            file.write(value)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def public_ca(source=CA_SOURCE):
    try:
        fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        raise SetupError("ca_invalid") from None
    try:
        import stat
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or not 1 <= info.st_size <= 65535:
            raise SetupError("ca_invalid")
        with os.fdopen(fd, "rb", closefd=False) as file:
            data = file.read(65536)
        if len(data) > 65535:
            raise SetupError("ca_invalid")
        try:
            text = data.decode("ascii")
            if "PRIVATE KEY" in text:
                raise SetupError("ca_invalid")
            ssl.create_default_context(cadata=text)
        except (UnicodeError, ssl.SSLError):
            raise SetupError("ca_invalid") from None
        return text
    finally:
        os.close(fd)


def connection_ca(state, source=CA_SOURCE):
    """Use the same saved trust as monitoring; never silently replace it."""
    saved = Path(state) / "mqtt-ca.crt"
    if saved.exists() or saved.is_symlink():
        private(saved)
        return public_ca(saved)
    return public_ca(source)


def import_ca(state, text, *, approved=False):
    """Setup caller holds the operation lock. Accept public PEM only, no paths."""
    if approved is not True:
        raise SetupError("ca_approval_required")
    if not isinstance(text, str) or not 1 <= len(text) <= IMPORT_CA_LIMIT:
        raise SetupError("ca_invalid")
    try:
        text.encode("ascii")
    except UnicodeError:
        raise SetupError("ca_invalid") from None
    certificate = r"-----BEGIN CERTIFICATE-----\r?\n(?:[A-Za-z0-9+/=]+\r?\n)+-----END CERTIFICATE-----"
    blocks = re.findall(certificate, text)
    if not 1 <= len(blocks) <= 8 or re.sub(certificate, "", text).strip():
        raise SetupError("ca_invalid")
    try:
        # Parse each certificate, require CA constraints and current validity.
        # All data passed to OpenSSL is public; stdout/stderr never reach UI/logs.
        now = time.time()
        for block in blocks:
            result = subprocess.run(["openssl", "x509", "-noout", "-dates", "-ext", "basicConstraints"],
                                    input=block.encode("ascii"), capture_output=True, timeout=5)
            output = result.stdout.decode("ascii")
            start = re.search(r"^notBefore=(.+)$", output, re.M)
            end = re.search(r"^notAfter=(.+)$", output, re.M)
            if (result.returncode or not re.search(r"\bCA:TRUE\b", output) or start is None or end is None
                    or not ssl.cert_time_to_seconds(start[1]) <= now < ssl.cert_time_to_seconds(end[1])):
                raise ValueError("Invalid public CA")
        ssl.create_default_context(cadata=text)
    except (ValueError, UnicodeError, ssl.SSLError, subprocess.SubprocessError):
        raise SetupError("ca_invalid") from None
    state = private(state, directory=True)
    target = state / "mqtt-ca.crt"
    if target.exists() or target.is_symlink():
        private(target)
        if target.stat().st_nlink != 1:
            raise SetupError("ca_invalid")
    # Existing bootstrap/backup allowlist already contains this fixed filename.
    write_secret(target, text)


def save_password(state, password, confirmation, source=CA_SOURCE):
    if (not isinstance(password, str) or not isinstance(confirmation, str)
            or not 1 <= len(password.encode("utf-8")) <= 1024 or not password.isprintable()):
        raise SetupError("input_invalid")
    import hmac
    if not hmac.compare_digest(password.encode(), confirmation.encode()):
        raise SetupError("password_mismatch")
    ca = connection_ca(state, source)
    if not (state / "mqtt-ca.crt").exists():
        write_secret(state / "mqtt-ca.crt", ca)
    write_secret(state / "mqtt_password", password)


def save_mqtt(state, current_options, fields, source=CA_SOURCE):
    from monitor import validate_options
    connection = {key: fields[key] for key in MQTT_KEYS}
    try:
        validate_options(dict(current_options, **connection), require_connection=True)
    except ValueError:
        raise SetupError("input_invalid") from None
    # Validate all inputs and CA before changing any persisted connection data.
    save_password(state, fields["password"], fields["confirmation"], source)
    atomic_json(state / "mqtt-settings.json", connection)


def use_supervisor_mqtt(state):
    path = state / "mqtt-settings.json"
    if path.exists() or path.is_symlink():
        private(path)
        path.unlink()
        directory = os.open(state, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


def mqtt_string(value):
    encoded = value.encode("utf-8")
    return struct.pack("!H", len(encoded)) + encoded


def mqtt_connect_packet(username="", password=""):
    body = b"\x00\x04MQTT\x04" + bytes([0xC2 if username else 0x02]) + b"\x00\x1e"
    body += mqtt_string("danfoss-preflight-" + uuid.uuid4().hex[:12])
    if username:
        body += mqtt_string(username) + mqtt_string(password)
    length = len(body)
    remaining = bytearray()
    while True:
        digit = length % 128
        length //= 128
        remaining.append(digit | (128 if length else 0))
        if not length:
            return b"\x10" + bytes(remaining) + body


async def verify_tls(options, source=CA_SOURCE, *, state=None):
    from monitor import validate_options
    validate_options(options, require_connection=True)
    context = ssl.create_default_context(cadata=public_ca(source) if state is None else connection_ca(state, source))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    writer = None
    try:
        async with asyncio.timeout(15):
            _, writer = await asyncio.open_connection(options["mqtt_host"], options["mqtt_port"],
                                                       ssl=context, server_hostname=options["mqtt_host"],
                                                       ssl_handshake_timeout=10)
    finally:
        if writer is not None:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 2)
            except (OSError, TimeoutError):
                pass


async def broker_connack(config, anonymous=False):
    context = ssl.create_default_context(cafile=config.ca_file)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    writer = None
    try:
        async with asyncio.timeout(15):
            reader, writer = await asyncio.open_connection(config.host, config.port, ssl=context,
                                                           server_hostname=config.host, ssl_handshake_timeout=10)
            writer.write(mqtt_connect_packet() if anonymous else mqtt_connect_packet(config.username, config.password))
            await writer.drain()
            response = await reader.readexactly(4)
            if response[:3] != b"\x20\x02\x00":
                raise SetupError("broker_protocol")
            if response[3] == 0:
                writer.write(b"\xe0\x00")
                await writer.drain()
            return response[3]
    finally:
        if writer is not None:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 2)
            except (OSError, TimeoutError):
                pass


async def check_mqtt(options, state):
    from monitor import settings
    try:
        config = settings(options, state)
    except (OSError, ValueError):
        raise SetupError("mqtt_incomplete") from None
    if await broker_connack(config) != 0:
        raise SetupError("broker_auth")
    if await broker_connack(config, anonymous=True) not in (4, 5):
        raise SetupError("broker_anonymous")


def keypair_hashes(state):
    return {name: hashlib.sha256(private(state / name).read_bytes()).hexdigest()
            for name in ("app_key.pem", "app_cert.pem")}


async def pair_code(state, code, *, approved=False):
    if approved is not True:
        raise SetupError("approval_required")
    from pair_cc import normalize_code, code_mode, pair
    from danfoss_mdg.identity import ensure_identity
    code = normalize_code(code)
    if code_mode(code) == "local":
        raise LocalCodeError("Unsupported local pairing code")
    for name in ("paired_cc.json", "identity_manifest.json"):
        if (state / name).exists() or (state / name).is_symlink():
            raise SetupError("already_paired")
    marker = state / "identity-created.json"
    if not marker.exists() and not marker.is_symlink():
        if any((state / name).exists() or (state / name).is_symlink()
               for name in ("app_key.pem", "app_cert.pem", "pending-keypair.json")):
            raise SetupError("identity_invalid")
        atomic_json(marker, {"format": 1, "identity_initialized": True})
        ensure_identity(state, profile="apk")
        validate_keypair(state)
        atomic_json(state / "pending-keypair.json", {"sha256": keypair_hashes(state)})
    else:
        if json.loads(private(marker).read_text()) != {"format": 1, "identity_initialized": True}:
            raise SetupError("identity_invalid")
        validate_keypair(state)
        pending = json.loads(private(state / "pending-keypair.json").read_text())
        if pending != {"sha256": keypair_hashes(state)}:
            raise SetupError("identity_invalid")
    async with asyncio.timeout(PAIR_TIMEOUT):
        await pair(state, code, "HAOS Danfoss Monitor", identity_profile="apk")
    atomic_json(state / "identity_manifest.json", {"format": 1, "sha256": identity_hashes(state)})
    validate_state(state)


def pairing_status(state):
    # GET status uses only metadata. Never read a key, password or pairing code.
    names = ("identity-created.json", "app_key.pem", "app_cert.pem", "pending-keypair.json",
             "paired_cc.json", "identity_manifest.json")
    present = set()
    for name in names:
        path = state / name
        if path.exists() or path.is_symlink():
            private(path)
            present.add(name)
    if not present:
        return "not_paired"
    if set(names) - {"pending-keypair.json"} <= present:
        return "stored"
    if set(names[:4]) == present:
        return "pending"
    return "invalid"
