"""Offline regressions for capability-limited traversal and test diagnostics.

The DAC model checks ordering, not actual kernel capabilities/UID transitions.
The separate container suite must exercise those with the real security flags.
"""
from contextlib import ExitStack
import errno
import os
from pathlib import Path
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import bootstrap
import storage
import test_bootstrap_container as harness
from test_app import OPTIONS
from test_bootstrap_container import cleanup_fixture, reclaim_fixture_state, subprocess_diagnostics


class PrivateDirectoryModel:
    """Root has CHOWN but no DAC override; physical fixture stays root-owned."""
    def __init__(self, state, directory_owner=0):
        self.state = state
        self.euid = 0
        self.owners = {state: (directory_owner, directory_owner)}
        self.changes = []
        self.real_lstat = Path.lstat
        self.real_iterdir = Path.iterdir

    def traverse(self, path):
        if path.parent == self.state and self.owners[self.state][0] != self.euid:
            raise PermissionError(errno.EACCES, "Permission denied", str(path))

    def lstat(self, path, *args, **kwargs):
        self.traverse(path)
        info = self.real_lstat(path, *args, **kwargs)
        uid, gid = self.owners.get(path, (info.st_uid, info.st_gid))
        return SimpleNamespace(st_mode=info.st_mode, st_uid=uid, st_gid=gid,
                               st_nlink=info.st_nlink, st_size=info.st_size)

    def iterdir(self, path):
        if path == self.state and self.owners[path][0] != self.euid:
            raise PermissionError(errno.EACCES, "Permission denied", str(path))
        return self.real_iterdir(path)

    def chown(self, path, uid, gid, **kwargs):
        path = Path(path)
        self.traverse(path)
        self.owners[path] = (uid, gid)
        self.changes.append((path, uid, gid))

    def install(self):
        stack = ExitStack()
        stack.enter_context(patch.object(Path, "lstat", new=lambda path, *a, **k: self.lstat(path, *a, **k)))
        stack.enter_context(patch.object(Path, "iterdir", new=lambda path: self.iterdir(path)))
        stack.enter_context(patch("bootstrap.os.chown", side_effect=self.chown))
        return stack


class BootstrapOrderTests(unittest.TestCase):
    def fixture(self, directory):
        state = Path(directory) / "state"
        state.mkdir(mode=0o700)
        storage.atomic_json(state / "identity-created.json", {"synthetic": True})
        return state

    def test_children_transferred_before_private_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            state = self.fixture(directory)
            model = PrivateDirectoryModel(state)
            with model.install():
                bootstrap.restore_ownership(state)
            self.assertEqual(model.changes[-1], (state, 65534, 65534))
            self.assertEqual(model.owners[state / "identity-created.json"], (65534, 65534))

    def test_runtime_owned_directory_reclaimed_before_inspection(self):
        with tempfile.TemporaryDirectory() as directory:
            state = self.fixture(directory)
            model = PrivateDirectoryModel(state, directory_owner=65534)
            with model.install():
                bootstrap.restore_ownership(state)
            self.assertEqual(model.changes[0], (state, 0, 0))
            self.assertEqual(model.changes[-1], (state, 65534, 65534))

    def test_invalid_restart_state_restores_original_directory_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            state = self.fixture(directory)
            (state / "unexpected").write_text("synthetic")
            model = PrivateDirectoryModel(state, directory_owner=65534)
            with model.install(), self.assertRaises(ValueError):
                bootstrap.restore_ownership(state)
            self.assertEqual(model.changes, [(state, 0, 0), (state, 65534, 65534)])

    def test_settings_written_only_after_uid_drop_for_fresh_and_existing_data(self):
        for existing in (False, True):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as directory:
                data = Path(directory)
                state = data / "state"
                if existing:
                    self.fixture(directory)
                storage.atomic_json(data / "options.json", OPTIONS)
                model = PrivateDirectoryModel(state, directory_owner=65534 if existing else 0)
                written = []
                def write_settings(path, value):
                    self.assertEqual(model.euid, 65534)
                    self.assertEqual(model.owners[state], (65534, 65534))
                    self.assertEqual(path, state / "settings.json")
                    self.assertEqual(value, OPTIONS)
                    written.append(path)
                with model.install(), patch("bootstrap.os.getuid", side_effect=lambda: model.euid), \
                        patch("bootstrap.os.setgroups") as groups, patch("bootstrap.os.setgid") as gid, \
                        patch("bootstrap.os.setuid", side_effect=lambda uid: setattr(model, "euid", uid)) as uid, \
                        patch("bootstrap.ctypes.CDLL", return_value=Mock(prctl=Mock(return_value=0))), \
                        patch("storage.atomic_json", side_effect=write_settings):
                    bootstrap.prepare(data)
                    groups.assert_called_once_with([])
                    gid.assert_called_once_with(65534)
                    uid.assert_called_once_with(65534)
                self.assertEqual(written, [state / "settings.json"])
                self.assertEqual(stat.S_IMODE(state.stat().st_mode), 0o700)


class BootstrapHarnessTests(unittest.TestCase):
    def test_subprocess_failure_and_timeout_retain_redacted_diagnostics(self):
        result = subprocess.CompletedProcess([], 1, stdout=b'secret="synthetic-secret"',
                                             stderr=b'PermissionError: /tmp/fixture/state/app_key.pem')
        timeout = subprocess.TimeoutExpired([], 20, output=result.stdout, stderr=result.stderr)
        for outcome in (result, timeout):
            case = harness.ContainerBootstrapTests("test_real_root_restore_ownership_and_runtime_privilege_drop")
            kwargs = {"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome}
            with self.subTest(timeout=isinstance(outcome, Exception)), \
                    patch("test_bootstrap_container.subprocess.run", **kwargs), \
                    self.assertRaises(AssertionError) as failure:
                case.run_bootstrap(Path("/unused-synthetic-fixture"))
            message = str(failure.exception)
            self.assertIn("stdout:", message)
            self.assertIn("stderr:", message)
            self.assertIn("PermissionError", message)
            self.assertNotIn("synthetic-secret", message)

    def test_diagnostics_include_traceback_and_redact_secret_material(self):
        stdout = b'password="synthetic password" token=synthetic-token pairing_code=123456789\n'
        stderr = (b"Traceback: PermissionError: /tmp/fixture/state/app_key.pem\n"
                  b"-----BEGIN EC PRIVATE KEY-----\nsynthetic-key-material\n-----END EC PRIVATE KEY-----\n")
        message = subprocess_diagnostics(1, stdout, stderr)
        for public in ("exit=1", "stdout:", "stderr:", "PermissionError", "/tmp/fixture/state/app_key.pem"):
            self.assertIn(public, message)
        for secret in ("synthetic password", "synthetic-token", "123456789", "synthetic-key-material"):
            self.assertNotIn(secret, message)

    def test_cleanup_reclaims_only_fixture_directory_without_chmod(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            state = data / "state"
            state.mkdir(mode=0o700)
            model = PrivateDirectoryModel(state, directory_owner=65534)
            temporary = SimpleNamespace(name=str(data), cleanup=Mock())
            with model.install():
                cleanup_fixture(temporary)
            self.assertEqual(model.changes, [(state, 0, 0)])
            temporary.cleanup.assert_called_once_with()
            self.assertEqual(stat.S_IMODE(state.stat().st_mode), 0o700)

    def test_cleanup_refuses_symlink_state(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            target = data / "elsewhere"
            target.mkdir(mode=0o700)
            (data / "state").symlink_to(target)
            with patch("os.chown") as chown, self.assertRaises(ValueError):
                reclaim_fixture_state(data)
            chown.assert_not_called()
