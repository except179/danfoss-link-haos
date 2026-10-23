"""Run as container root with --network none; no real credentials are used."""
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import unittest

from test_app import OPTIONS, synthetic_state
from storage import atomic_json


def mqtt_override(state):
    atomic_json(state / "mqtt-settings.json", {"mqtt_host": "broker.invalid", "mqtt_port": 8883,
                                               "mqtt_username": "synthetic-override"})


def redact_output(output):
    """Retain tracebacks/paths, but never echo PEM blocks or secret inputs."""
    if isinstance(output, bytes):
        output = output.decode("utf-8", errors="replace")
    output = output or ""
    output = re.sub(r"-----BEGIN [A-Z0-9 ]+-----.*?(?:-----END [A-Z0-9 ]+-----|$)",
                    "[REDACTED PEM]", output, flags=re.DOTALL)
    output = re.sub(
        r'''(?i)(["']?(?:mqtt[_-]?password|password|token|secret|pairing[_ -]?code)["']?\s*[:=]\s*)(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,;]+)''',
        r"\1[REDACTED]", output)
    output = re.sub(r"(?<!\w)\d{6,69}(?!\w)", "[REDACTED CODE]", output)
    # Redact before truncation, so a long PEM cannot leak a partial block.
    return output[:12000] + ("\n[output truncated]" if len(output) > 12000 else "")


def subprocess_diagnostics(returncode, stdout, stderr):
    return (f"Container ownership/drop smoke test failed (exit={returncode})\n"
            f"stdout:\n{redact_output(stdout)}\nstderr:\n{redact_output(stderr)}")


def reclaim_fixture_state(data):
    """Only the generated test state's directory, never production storage.

    CHOWN can reclaim the directory without traversing its contents. That is
    sufficient for root to inspect/unlink fixture files even without DAC/FOWNER.
    File ownership and modes are not changed, allowing assertions afterwards.
    """
    state = data / "state"
    try:
        info = state.lstat()
    except FileNotFoundError:
        return
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, 65534)
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise ValueError("Refusing to reclaim unexpected fixture directory")
    if info.st_uid != 0:
        os.chown(state, 0, 0, follow_symlinks=False)


def cleanup_fixture(temporary):
    reclaim_fixture_state(Path(temporary.name))
    temporary.cleanup()


BOOTSTRAP_SCRIPT = """from pathlib import Path
import json,os,stat,sys
from bootstrap import prepare
from storage import atomic_json,validate_state
from monitor import options_from_file
data=Path(sys.argv[1])
expected=sys.argv[2]
permitted=json.loads(sys.argv[3])
prepare(data)
assert os.getuid()==os.getgid()==os.geteuid()==os.getegid()==65534
assert os.getgroups()==[]
state=data/'state'
assert state.stat().st_uid==state.stat().st_gid==65534
assert stat.S_IMODE(state.stat().st_mode)==0o700
assert data.stat().st_uid==0 and stat.S_IMODE(data.stat().st_mode)==0o711
assert (data/'options.json').stat().st_uid==0
assert stat.S_IMODE((data/'options.json').stat().st_mode)==0o600
try:
    (data/'options.json').read_text()
except PermissionError:
    pass
else:
    raise AssertionError('Runtime could read root-private Supervisor options')
if expected:
    assert validate_state(state)==expected
else:
    assert not (state/'app_key.pem').exists()
    assert not (state/'paired_cc.json').exists()
options=json.loads((state/'settings.json').read_text())
assert options['danfoss_allow_writes'] is permitted and options['mqtt_tls'] is True
effective=options_from_file(state)
assert effective['danfoss_allow_writes'] is permitted and effective['mqtt_tls'] is True
if permitted:
    from monitor import settings
    from heating import HeatingBridge
    from unittest.mock import Mock
    config=settings(effective,state)
    assert config.poll_interval==180 and config.allow_writes is False
    assert (state/'mqtt_password').read_text()=='synthetic-password'
    bridge=HeatingBridge(config,state,Mock(),permitted=True)
    assert bridge.enabled is False and bridge.permission() is True
if (state/'mqtt-settings.json').exists():
    assert effective['mqtt_host']=='broker.invalid'
    assert effective['mqtt_username']=='synthetic-override'
atomic_json(state/'runtime.json', {'synthetic_write_check': True})
assert json.loads((state/'runtime.json').read_text())=={'synthetic_write_check': True}
for entry in state.iterdir():
    info=entry.lstat()
    assert stat.S_ISREG(info.st_mode) and info.st_nlink==1
    assert info.st_uid==info.st_gid==65534
    assert stat.S_IMODE(info.st_mode)==0o600
status=dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
assert int(status['CapEff'].strip(),16)==0
assert int(status['CapPrm'].strip(),16)==0
assert int(status['CapAmb'].strip(),16)==0
assert status['NoNewPrivs'].strip()=='1'
try:
    os.setuid(0)
except PermissionError:
    pass
else:
    raise AssertionError('Runtime regained root')
print('Private state validated: UID/GID 65534, directory 0700, files 0600, no effective capabilities, no-new-privileges')
"""


class ContainerBootstrapTests(unittest.TestCase):
    def fixture(self):
        self.assertEqual(os.getuid(), 0, "Run this required image test as container root")
        temporary = tempfile.TemporaryDirectory()
        # unittest reports cleanup errors separately, preserving a primary
        # assertion/timeout failure instead of masking it in __exit__.
        self.addCleanup(cleanup_fixture, temporary)
        data = Path(temporary.name)
        data.chmod(0o711)
        atomic_json(data / "options.json", OPTIONS)
        return data

    def run_bootstrap(self, data, expected="", *, permitted=False):
        try:
            result = subprocess.run([sys.executable, "-c", BOOTSTRAP_SCRIPT, str(data), expected, json.dumps(permitted)],
                                    capture_output=True, timeout=20)
        except subprocess.TimeoutExpired as error:
            self.fail(subprocess_diagnostics("timeout", error.stdout, error.stderr))
        self.assertEqual(result.returncode, 0,
                         subprocess_diagnostics(result.returncode, result.stdout, result.stderr))
        state = data / "state"
        info = state.stat()
        self.assertEqual((info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)), (65534, 65534, 0o700))
        # The parent intentionally lacks traversal permission at this point.
        # Check runtime directory ownership first, then reclaim ONLY this
        # fixture directory before checking child metadata or cleanup.
        reclaim_fixture_state(data)
        for entry in state.iterdir():
            info = entry.lstat()
            self.assertEqual((info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)), (65534, 65534, 0o600))

    def test_real_root_restore_ownership_and_runtime_privilege_drop(self):
        from storage import validate_state
        data = self.fixture()
        state = synthetic_state(data / "state")
        mqtt_override(state)
        self.run_bootstrap(data, validate_state(state))

    def test_fresh_private_storage_and_runtime_privilege_drop(self):
        self.run_bootstrap(self.fixture())

    def test_blank_v031_setup_drops_privileges_without_identity_creation(self):
        from test_first_install import FRESH
        data = self.fixture()
        atomic_json(data / "options.json", FRESH)
        self.run_bootstrap(data)
        self.assertFalse((data / "state" / "app_key.pem").exists())
        self.assertFalse((data / "state" / "paired_cc.json").exists())

    def test_legacy_monitor_permission_and_credentials_survive_real_handoff(self):
        from storage import validate_state
        from test_first_install import seed_mqtt
        data = self.fixture()
        atomic_json(data / "options.json", dict(OPTIONS, danfoss_allow_writes=True, poll_interval=180))
        state = synthetic_state(data / "state")
        seed_mqtt(state)
        mqtt_override(state)
        self.run_bootstrap(data, validate_state(state), permitted=True)

    def test_runtime_owned_state_on_app_restart(self):
        from storage import validate_state
        data = self.fixture()
        state = synthetic_state(data / "state")
        mqtt_override(state)
        expected = validate_state(state)
        # Model the state left by normal operation, transferring children first.
        for entry in state.iterdir():
            os.chown(entry, 65534, 65534, follow_symlinks=False)
        os.chown(state, 65534, 65534, follow_symlinks=False)
        self.run_bootstrap(data, expected)
