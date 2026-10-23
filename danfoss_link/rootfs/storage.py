"""Persistent state checks. No identity generation is reachable from startup."""
import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess

UID = 65534
IDENTITY_FILES = ("app_key.pem", "app_cert.pem", "paired_cc.json")


def private(path, directory=False, owner=None, limit=65535):
    path = Path(path)
    info = path.lstat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(info.st_mode) or path.is_symlink() or info.st_mode & 0o077:
        raise ValueError("Unsafe private state permissions")
    if info.st_uid != (os.getuid() if owner is None else owner):
        raise ValueError("Unsafe private state ownership")
    if not directory and info.st_size > limit:
        raise ValueError("Private state exceeds size limit")
    return path


def atomic_json(path, value):
    # No key material goes through this helper. Fixed per-process filename,
    # exclusive creation and a private directory reject unsafe preexisting paths.
    path = Path(path)
    temporary = path.with_name(path.name + f".{os.getpid()}.new")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as file:
            json.dump(value, file, sort_keys=True)
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


def openssl(*arguments):
    result = subprocess.run(["openssl", *arguments], capture_output=True, timeout=10)
    if result.returncode:
        raise ValueError("Identity validation failed")
    return result.stdout


def validate_keypair(state):
    state = private(state, directory=True)
    key = private(state / "app_key.pem", limit=16384)
    cert = private(state / "app_cert.pem", limit=16384)
    public_key = openssl("pkey", "-in", str(key), "-pubout")
    public_cert = openssl("x509", "-in", str(cert), "-pubkey", "-noout")
    if public_key != public_cert:
        raise ValueError("Application key and certificate mismatch")
    openssl("x509", "-in", str(cert), "-checkend", "0", "-noout")


def identity_hashes(state):
    return {name: hashlib.sha256(private(state / name).read_bytes()).hexdigest()
            for name in IDENTITY_FILES}


def validate_state(state):
    state = Path(state)
    if json.loads(private(state / "identity-created.json").read_text()) != {"format": 1, "identity_initialized": True}:
        raise ValueError("Identity initialization marker is invalid")
    validate_keypair(state)
    from danfoss_mdg.readonly_transport import load_trust
    _, _, peer_id, peer_der = load_trust(state)
    record = json.loads(private(state / "paired_cc.json").read_text())
    if record.get("peer_name") != peer_id:
        raise ValueError("Peer identity differs from paired certificate")
    # Parse/expiry validation of saved peer, without making a live connection.
    import ssl
    # x509 takes public certificate data via stdin; never send a private key.
    result = subprocess.run(["openssl", "x509", "-inform", "DER", "-checkend", "0", "-noout"],
                            input=peer_der, capture_output=True, timeout=10)
    if result.returncode:
        raise ValueError("Paired peer certificate is invalid or expired")
    ssl.DER_cert_to_PEM_cert(base64.b64decode(record["certificate_der"], validate=True))
    manifest = json.loads(private(state / "identity_manifest.json").read_text())
    if manifest != {"format": 1, "sha256": identity_hashes(state)}:
        raise ValueError("Identity changed; investigate before starting")
    return hashlib.sha256(peer_id.encode()).hexdigest()[:16]
