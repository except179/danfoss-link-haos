"""Process liveness, separate from cloud readiness. Never contacts the CC."""
import json
from pathlib import Path
import time


def healthy(path=Path("/tmp/danfoss-health.json"), now=None):
    try:
        data = json.loads(path.read_text())
        age = (time.monotonic() if now is None else now) - data["heartbeat"]
        return 0 <= age < 90
    except (OSError, ValueError, KeyError, TypeError):
        return False


if __name__ == "__main__":
    raise SystemExit(0 if healthy() else 1)
