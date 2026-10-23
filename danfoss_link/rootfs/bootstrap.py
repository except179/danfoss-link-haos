"""Root setup limited to the Supervisor-assigned private data directory."""
import json
import ctypes
import os
from pathlib import Path
import stat
import sys

from storage import UID

STATE_FILES = frozenset({
    "app_key.pem", "app_cert.pem", "paired_cc.json", "identity_manifest.json",
    "mqtt_discovery_rooms.json", "pending-keypair.json", "identity-created.json",
    "mqtt_password", "mqtt-ca.crt", "settings.json", "runtime.json",
    "operation.lock", "untrusted-public-certificates.json", "mqtt-settings.json",
})


def restore_ownership(state):
    """Supervisor copytree restore can produce root-owned private files.

    Root without DAC override cannot traverse a runtime-owned 0700 directory.
    Temporarily reclaim this one validated directory, inspect every child
    before changing child ownership, then transfer the directory LAST.
    No recursion, symlinks, hardlinks or permission widening.
    """
    info = state.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, UID) or info.st_mode & 0o077:
        raise ValueError("Invalid private state directory")
    original_owner = (info.st_uid, info.st_gid)
    reclaimed = info.st_uid != 0
    if reclaimed:
        os.chown(state, 0, 0, follow_symlinks=False)
    try:
        entries = list(state.iterdir())
        for entry in entries:
            info = entry.lstat()
            if (entry.name not in STATE_FILES or not stat.S_ISREG(info.st_mode)
                    or info.st_nlink != 1 or info.st_uid not in (0, UID)
                    or info.st_mode & 0o077 or info.st_size > 262144):
                raise ValueError("Unexpected or unsafe private state; investigate")
        for entry in entries:
            os.chown(entry, UID, UID, follow_symlinks=False)
        os.chown(state, UID, UID, follow_symlinks=False)
    except BaseException:
        if reclaimed:
            os.chown(state, *original_owner, follow_symlinks=False)
        raise


def prepare(data=Path("/data")):
    if os.getuid() != 0 or data.is_symlink() or not data.is_dir():
        raise ValueError("Supervisor private storage is required")
    # The root directory remains root-owned: the daemon cannot alter options.
    data.chmod(0o711)
    state = data / "state"
    if not state.exists():
        if state.is_symlink():
            raise ValueError("Invalid state directory")
        state.mkdir(mode=0o700)
    # Supervisor creates options as root. Pass non-secret options through a
    # runtime-owned private file; do not change Supervisor file ownership.
    from storage import atomic_json
    options = json.loads((data / "options.json").read_text())
    restore_ownership(state)
    os.umask(0o077)
    if ctypes.CDLL(None, use_errno=True).prctl(38, 1, 0, 0, 0) != 0:
        raise ValueError("Cannot prevent runtime privilege escalation")
    os.setgroups([])
    os.setgid(UID)
    os.setuid(UID)
    for name in ("SUPERVISOR_TOKEN", "HASSIO_TOKEN"):
        os.environ.pop(name, None)
    # All private-directory I/O after handoff runs as its actual owner.
    atomic_json(state / "settings.json", options)


if __name__ == "__main__":
    try:
        prepare()
        os.execv(sys.executable, [sys.executable, "/opt/haos_app/monitor.py"])
    except Exception:
        print("App bootstrap failed; inspect private storage and permissions", file=sys.stderr)
        raise SystemExit(1)
