"""Private, interactive commissioning. Never accept secrets as arguments/env."""
import argparse
import asyncio
import ctypes
import getpass
import os
from pathlib import Path
import sys
import warnings

from storage import UID, private, validate_state
import commissioning
from commissioning import LocalCodeError, write_secret, mqtt_string, mqtt_connect_packet, broker_connack

STATE = Path("/data/state")


def hidden(prompt):
    if not sys.stdin.isatty():
        raise ValueError("A private interactive terminal is required")
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        return getpass.getpass(prompt)


def configure():
    password = hidden("MQTT password (hidden): ")
    confirmation = hidden("Repeat MQTT password (hidden): ")
    commissioning.save_password(STATE, password, confirmation)
    print("Private MQTT credentials and trusted CA saved; no broker changes made")


def check_mqtt(options):
    asyncio.run(commissioning.check_mqtt(options, STATE))
    print("MQTT TLS chain/IP identity, dedicated authentication and anonymous rejection passed; no topics published")


def keypair_hashes():
    return commissioning.keypair_hashes(STATE)


async def initialize_and_pair():
    print("Requires explicit owner approval and a NEW cloud app code from the physical CC. Existing phones must remain paired.")
    if input("Type PAIR NEW CLIENT to continue: ") != "PAIR NEW CLIENT":
        raise ValueError("Pairing cancelled")
    code = hidden("Fresh cloud pairing code (hidden): ")
    await commissioning.pair_code(STATE, code, approved=True)
    print("Independent identity and CC pin saved. Keep setup mode until the commissioning checklist permits monitoring.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("configure", "check-mqtt", "initialize-and-pair", "verify-state", "use-supervisor-mqtt"))
    args = parser.parse_args()
    lock = None
    try:
        if not sys.stdin.isatty():
            raise ValueError("Interactive private local terminal required")
        os.umask(0o077)
        if ctypes.CDLL(None, use_errno=True).prctl(38, 1, 0, 0, 0) != 0:
            raise ValueError("Cannot prevent privilege escalation")
        if os.getuid() == 0:
            os.setgroups([])
            os.setgid(UID)
            os.setuid(UID)
        private(STATE, directory=True)
        from runtime_check import check
        check()
        from monitor import operation_lock, options_from_file
        options = options_from_file()
        if options["operation"] != "setup":
            raise ValueError("Stop monitoring and select setup before maintenance")
        lock = operation_lock()
        if args.action == "configure":
            configure()
        elif args.action == "check-mqtt":
            check_mqtt(options)
        elif args.action == "verify-state":
            validate_state(STATE)
            print("Private identity, paired certificate, expiry, manifest and permissions valid; no connections made")
        elif args.action == "use-supervisor-mqtt":
            commissioning.use_supervisor_mqtt(STATE)
            print("Supervisor MQTT connection settings selected; private credential retained")
        else:
            asyncio.run(initialize_and_pair())
        return 0
    except LocalCodeError:
        print("Local pairing codes are unsupported. Use the CC cloud App pairing screen; no identity was created", file=sys.stderr)
        return 1
    except Exception:
        print("Commissioning stopped safely; investigate configuration/state or rejected input. Secret details suppressed", file=sys.stderr)
        return 1
    finally:
        if lock is not None:
            os.close(lock)


if __name__ == "__main__":
    raise SystemExit(main())
