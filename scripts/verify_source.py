#!/usr/bin/env python3
"""Verify the unchanged audited source inventory before any image build."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
vendor = root / "danfoss_link/vendor"
actual = {str(path.relative_to(vendor)): hashlib.sha256(path.read_bytes()).hexdigest()
          for path in vendor.rglob("*") if path.is_file() and "__pycache__" not in path.parts}
expected = json.loads((root / "metadata/vendor-sha256.json").read_text())
if actual != expected:
    raise SystemExit("Audited source inventory mismatch; stop and review")
print(f"Audited source inventory verified: {len(actual)} files")
