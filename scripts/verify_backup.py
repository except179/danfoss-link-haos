#!/usr/bin/env python3
"""Inspect an already-decrypted HA backup in memory. No extraction or network.

Use a UI-downloaded backup on encrypted off-device storage. Raw encrypted
Supervisor backups are rejected; this tool never requests encryption keys.
"""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import ssl
import subprocess
import tarfile


def index(archive):
    entries = {}
    for entry in archive:
        name = entry.name.removeprefix("./")
        if name in ("", "."):
            continue
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or name in entries:
            raise ValueError("Ambiguous or unsafe archive path")
        entries[name] = entry
        if len(entries) > 200000:
            raise ValueError("Archive has too many members")
    return entries


def read(archive, entries, name, limit=262144, private=False):
    entry = entries[name]
    if not entry.isfile() or entry.size > limit or (private and (entry.mode & 0o077 or entry.uid not in (0, 65534))):
        raise ValueError("Unsafe/missing backup member")
    with archive.extractfile(entry) as file:
        return file.read(limit + 1)


def openssl(arguments, data):
    result = subprocess.run(["openssl", *arguments], input=data, capture_output=True, timeout=15)
    if result.returncode:
        raise ValueError("Backup certificate/key validation failed")
    return result.stdout


def verify_app(inner):
    with tarfile.open(fileobj=io.BytesIO(inner), mode="r:*") as archive:
        entries = index(archive)
        prefix = "data/state/"
        names = ("app_key.pem", "app_cert.pem", "paired_cc.json", "identity_manifest.json",
                 "identity-created.json", "mqtt_password", "mqtt-ca.crt", "mqtt_discovery_rooms.json")
        payload = {name: read(archive, entries, prefix + name, private=True) for name in names}
        ssl.create_default_context(cadata=payload["mqtt-ca.crt"].decode())
        password = payload["mqtt_password"].decode()
        if not 1 <= len(password) <= 1024 or not password.isprintable():
            raise ValueError("Backup MQTT credential is invalid")
        if json.loads(payload["identity-created.json"]) != {"format": 1, "identity_initialized": True}:
            raise ValueError("Backup initialization marker invalid")
        options = json.loads(read(archive, entries, "data/options.json"))
        if type(options.get("danfoss_allow_writes")) is not bool or options.get("mqtt_tls") is not True:
            raise ValueError("Backup contains unsafe runtime options")
        overlay = prefix + "mqtt-settings.json"
        if overlay in entries:
            connection = json.loads(read(archive, entries, overlay, private=True))
            if (not isinstance(connection, dict) or set(connection) != {"mqtt_host", "mqtt_port", "mqtt_username"}
                    or type(connection["mqtt_port"]) is not int or not 1 <= connection["mqtt_port"] <= 65535
                    or any(not isinstance(connection[key], str) or not 1 <= len(connection[key]) <= 253
                           or not connection[key].isprintable() or connection[key] != connection[key].strip()
                           for key in ("mqtt_host", "mqtt_username"))):
                raise ValueError("Backup contains invalid MQTT connection override")
        expected = {name: hashlib.sha256(payload[name]).hexdigest() for name in names[:3]}
        if json.loads(payload["identity_manifest.json"]) != {"format": 1, "sha256": expected}:
            raise ValueError("Backup identity manifest mismatch")
        if openssl(["pkey", "-pubout"], payload["app_key.pem"]) != openssl(["x509", "-pubkey", "-noout"], payload["app_cert.pem"]):
            raise ValueError("Backup key/certificate mismatch")
        openssl(["x509", "-checkend", "0", "-noout"], payload["app_cert.pem"])
        trust = json.loads(payload["paired_cc.json"])
        der = base64.b64decode(trust["certificate_der"], validate=True)
        openssl(["x509", "-inform", "DER", "-checkend", "0", "-noout"], der)
        peer_id = openssl(["x509", "-inform", "DER", "-noout", "-ext", "subjectKeyIdentifier"], der)
        match = re.search(rb"(?:[0-9A-Fa-f]{2}:){19}[0-9A-Fa-f]{2}", peer_id)
        if trust.get("format") != 1 or not match or trust["peer_name"] != match.group().decode().lower():
            raise ValueError("Backup peer identity mismatch")
        controller = hashlib.sha256(trust["peer_name"].encode()).hexdigest()[:16]
        discovery = json.loads(payload["mqtt_discovery_rooms.json"])
        if discovery.get("controller_id") != controller:
            raise ValueError("Backup discovery identity mismatch")
        room_ids = discovery.get("room_ids")
        if not isinstance(room_ids, list) or any(type(room) is not int or room < 0 for room in room_ids):
            raise ValueError("Backup room IDs invalid")
        return {"paired_identity_verified": True, "controller_id": controller, "room_count": len(room_ids)}


def verify(path, slug=None):
    with tarfile.open(path, "r:*") as outer:
        entries = index(outer)
        metadata = json.loads(read(outer, entries, "backup.json", limit=2097152))
        if metadata.get("type") != "full":
            raise ValueError("A full backup is required")
        apps = metadata.get("addons", [])
        result = {"full_backup_metadata": True, "date": metadata.get("date"),
                  "app_count": len(apps), "folders": metadata.get("folders", []),
                  "ha_payload_present": any(name.startswith("homeassistant.tar") for name in entries)}
        if not result["ha_payload_present"]:
            raise ValueError("Home Assistant payload missing")
        # Read all inner compressed streams to their tar end: catches truncated
        # or encrypted downloads without extracting household files.
        for name, entry in entries.items():
            if name.endswith((".tar", ".tar.gz")):
                if not entry.isfile():
                    raise ValueError("Backup payload is not a regular file")
                with outer.extractfile(entry) as file, tarfile.open(fileobj=file, mode="r|*") as inner:
                    for member in inner:
                        if member.isfile():
                            with inner.extractfile(member) as contents:
                                while contents.read(1048576):
                                    pass
        if slug:
            if slug not in {app["slug"] for app in apps}:
                raise ValueError("App is not listed in backup metadata")
            candidates = [name for name in entries if name in (slug + ".tar", slug + ".tar.gz")]
            if len(candidates) != 1:
                raise ValueError("App backup payload missing or ambiguous")
            result.update(verify_app(read(outer, entries, candidates[0], limit=67108864)))
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1048576), b""):
            digest.update(block)
    result["archive_sha256"] = digest.hexdigest()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--slug", help="Exact installed Supervisor slug; require paired state too")
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.archive, args.slug), indent=2))
    except Exception:
        raise SystemExit("Backup verification failed: inspect archive format, completeness and private state; no secrets printed")
