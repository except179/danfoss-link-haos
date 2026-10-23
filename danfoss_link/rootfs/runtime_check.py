"""Fail image builds/startup against the wrong ABI; no network or state changes."""
import importlib.metadata
import platform
import ssl
import subprocess
import sys


def check():
    if platform.machine() != "x86_64" or sys.version_info[:2] != (3, 12):
        raise RuntimeError("Unvalidated architecture or Python runtime")
    if not ssl.OPENSSL_VERSION.startswith("OpenSSL 3.5.9 "):
        raise RuntimeError("Private OpenSSL runtime is required")
    if importlib.metadata.version("paho-mqtt") != "2.1.0":
        raise RuntimeError("Unvalidated MQTT library")
    result = subprocess.run(["openssl", "version"], capture_output=True, timeout=5, check=True)
    if not result.stdout.startswith(b"OpenSSL 3.5.9 "):
        raise RuntimeError("OpenSSL executable and Python must use the private runtime")


if __name__ == "__main__":
    check()
