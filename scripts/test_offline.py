#!/usr/bin/env python3
"""Dependency-free tests; excludes the required private-runtime/container tests."""
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
for path in ("danfoss_link/rootfs", "danfoss_link/vendor/src", "danfoss_link/vendor/tests", "tests", "scripts"):
    sys.path.insert(0, str(ROOT / path))
modules = ["test_first_install", "test_heating", "test_app", "test_backup", "test_bootstrap_checks", "test_ingress", "test_pairing_lifecycle", "test_rooms", "test_temperature_control", "test_readonly_transport",
           "test_pace_crypto", "test_identity_profile", "test_code_diagnostics", "test_mqtt_bridge", "test_mqtt_status"]
result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromNames(modules))
raise SystemExit(0 if result.wasSuccessful() and not result.skipped else 1)
