import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from storage import atomic_json, validate_state
from test_app import OPTIONS, synthetic_state
from verify_backup import verify


def tar_bytes(files):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, data in files.items():
            member = tarfile.TarInfo(name); member.size = len(data); member.mode = 0o600; member.uid = 65534
            archive.addfile(member, io.BytesIO(data))
    return buffer.getvalue()


class BackupTests(unittest.TestCase):
    def test_non_disruptive_archive_verification_and_identity_tamper_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); state = synthetic_state(root / "state")
            controller = validate_state(state)
            atomic_json(state / "mqtt_discovery_rooms.json", {"controller_id": controller, "room_ids": [7]})
            for name, value in (("mqtt_password", "synthetic-only"), ("mqtt-ca.crt", (state / "app_cert.pem").read_text())):
                (state / name).write_text(value); (state / name).chmod(0o600)
            files = {"data/state/" + path.name: path.read_bytes() for path in state.iterdir()}
            files["data/options.json"] = json.dumps(OPTIONS).encode()
            metadata = {"type": "full", "addons": [{"slug": "local_danfoss_link_monitor"}], "folders": ["ssl", "addons/local"]}
            def archive(payload):
                path = root / "synthetic-backup.tar"
                path.write_bytes(tar_bytes({"backup.json": json.dumps(metadata).encode(),
                    "homeassistant.tar.gz": tar_bytes({"data/synthetic.txt": b"synthetic"}),
                    "local_danfoss_link_monitor.tar.gz": tar_bytes(payload)}))
                return path
            path = archive(files)
            result = verify(path, "local_danfoss_link_monitor")
            self.assertTrue(result["paired_identity_verified"])
            self.assertEqual(result["controller_id"], controller)
            self.assertEqual(result["room_count"], 1)
            self.assertFalse((root / "data").exists(), "Verifier must never extract private state")
            enabled_permission = dict(files)
            enabled_permission["data/options.json"] = json.dumps(dict(OPTIONS, danfoss_allow_writes=True)).encode()
            self.assertTrue(verify(archive(enabled_permission), "local_danfoss_link_monitor")["paired_identity_verified"])
            overlay = dict(files)
            overlay["data/state/mqtt-settings.json"] = json.dumps({"mqtt_host": "broker.invalid", "mqtt_port": 8883, "mqtt_username": "synthetic"}).encode()
            self.assertTrue(verify(archive(overlay), "local_danfoss_link_monitor")["paired_identity_verified"])
            overlay["data/state/mqtt-settings.json"] = b'{"danfoss_allow_writes":true}'
            with self.assertRaises(ValueError):
                verify(archive(overlay), "local_danfoss_link_monitor")
            changed = dict(files); changed["data/state/app_key.pem"] = b"corrupted synthetic key"
            with self.assertRaises(ValueError):
                verify(archive(changed), "local_danfoss_link_monitor")
            missing = dict(files); del missing["data/state/paired_cc.json"]
            with self.assertRaises(KeyError):
                verify(archive(missing), "local_danfoss_link_monitor")

    def test_metadata_only_backup_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metadata.tar"
            path.write_bytes(tar_bytes({"backup.json": b'{"type":"full","addons":[]}'}))
            with self.assertRaises(ValueError):
                verify(path)
