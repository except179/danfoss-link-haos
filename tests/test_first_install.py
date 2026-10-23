"""v0.3.1 fresh/legacy setup and CA trust regressions, synthetic state only."""
import asyncio
import copy
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import ssl
import subprocess
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch

import commissioning as setup
import heating
import ingress
import monitor
from storage import atomic_json, identity_hashes, validate_state
from test_app import OPTIONS, SNAPSHOT, synthetic_state
import test_ingress as ingress_tests
from test_ingress import PREFIX

FRESH = dict(OPTIONS, operation="setup", mqtt_host="", mqtt_username="")


@lru_cache(maxsize=1)
def certificates():
    """Generate public CA/leaf fixtures; private keys stay in disposable tmp."""
    result = []
    with tempfile.TemporaryDirectory() as directory:
        for name, ca in (("ca", "TRUE"), ("leaf", "FALSE")):
            cert = Path(directory) / (name + ".pem")
            subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt",
                            "ec_paramgen_curve:prime256v1", "-noenc", "-keyout", str(cert.with_suffix(".key")),
                            "-out", str(cert), "-subj", "/CN=Synthetic MQTT fixture",
                            "-addext", "basicConstraints=critical,CA:" + ca, "-days", "2"],
                           capture_output=True, check=True, timeout=10)
            result.append(cert.read_text())
    return result


def seed_mqtt(state):
    for name, value in (("mqtt_password", "synthetic-password"), ("mqtt-ca.crt", certificates()[0])):
        (state / name).write_text(value)
        (state / name).chmod(0o600)


class FreshOptionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_blank_setup_has_no_network_or_identity_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            atomic_json(state / "settings.json", FRESH)
            with patch("commissioning.asyncio.open_connection", new=AsyncMock()) as network, patch("commissioning.pair_code", new=AsyncMock()) as pairing:
                self.assertEqual(monitor.options_from_file(state), FRESH)
                server = ingress.IngressServer(state)
                for route in ingress.PAGES:
                    self.assertIn("Not configured", server.page(route, "admin", PREFIX, 0))
                network.assert_not_called(); pairing.assert_not_called()
            self.assertEqual({p.name for p in state.iterdir()}, {"settings.json"})

    async def test_incomplete_monitor_and_every_connection_path_reject_blanks(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            seed_mqtt(state)
            for options in (FRESH, dict(FRESH, mqtt_host="broker.invalid"), dict(FRESH, mqtt_username="synthetic")):
                with self.assertRaises(ValueError):
                    monitor.validate_options(dict(options, operation="monitor"))
                with self.assertRaises(ValueError):
                    monitor.settings(options, state)
                with patch("commissioning.asyncio.open_connection", new=AsyncMock()) as network:
                    with self.assertRaises(ValueError):
                        await setup.verify_tls(options, state=state)
                    with self.assertRaises(setup.SetupError):
                        await setup.check_mqtt(options, state)
                    network.assert_not_called()

    async def test_malformed_setup_options_still_fail_closed(self):
        for change in ({"mqtt_host": None}, {"mqtt_username": " "}, {"mqtt_port": True},
                       {"mqtt_tls": False}, {"danfoss_allow_writes": "false"},
                       {"poll_interval": 0}, {"topic_prefix": "#"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                monitor.validate_options(FRESH | change)

    async def test_missing_credentials_fail_before_network(self):
        with tempfile.TemporaryDirectory() as directory, patch("commissioning.broker_connack", new=AsyncMock()) as network:
            with self.assertRaises(setup.SetupError) as result:
                await setup.check_mqtt(dict(OPTIONS, operation="setup"), Path(directory))
            self.assertEqual(result.exception.code, "mqtt_incomplete")
            network.assert_not_called()

    async def test_invalid_save_does_not_create_credentials_or_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            fields = dict(mqtt_host="", mqtt_port=8883, mqtt_username="synthetic", password="synthetic", confirmation="synthetic")
            with self.assertRaises(setup.SetupError):
                setup.save_mqtt(state, FRESH, fields)
            self.assertEqual(list(state.iterdir()), [])


class CAImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = Path(self.temp.name)
        self.ca, self.leaf = certificates()

    def tearDown(self):
        self.temp.cleanup()

    def test_public_ca_is_private_fixed_path_and_needs_explicit_approval(self):
        with self.assertRaises(setup.SetupError):
            setup.import_ca(self.state, self.ca)
        self.assertEqual(list(self.state.iterdir()), [])
        setup.import_ca(self.state, self.ca, approved=True)
        self.assertEqual({p.name for p in self.state.iterdir()}, {"mqtt-ca.crt"})
        self.assertEqual((self.state / "mqtt-ca.crt").stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.state / "mqtt-ca.crt").stat().st_uid, os.getuid())
        self.assertEqual((self.state / "mqtt-ca.crt").read_text(), self.ca)

    def test_non_pem_private_key_extra_text_leaf_and_oversize_rejected(self):
        invalid = ("", "https://broker.invalid/ca", "../untrusted.pem", "not a PEM", self.leaf,
                   self.ca + "\nPRIVATE KEY", self.ca + "\n-----BEGIN PRIVATE KEY-----\nsynthetic\n-----END PRIVATE KEY-----",
                   self.ca + "\x00", self.ca + "é", "X" * (setup.IMPORT_CA_LIMIT + 1), self.ca * 9)
        for value in invalid:
            with self.subTest(kind=type(value).__name__), self.assertRaises(setup.SetupError):
                setup.import_ca(self.state, value, approved=True)
            self.assertEqual(list(self.state.iterdir()), [])

    def test_malformed_base64_certificate_rejected_by_openssl(self):
        with self.assertRaises(setup.SetupError):
            setup.import_ca(self.state, "-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----\n", approved=True)

    def test_expired_and_not_yet_valid_ca_rejected(self):
        for offset in (-3 * 86400, 3 * 86400):
            with patch("commissioning.time.time", return_value=time.time() + offset), self.assertRaises(setup.SetupError):
                setup.import_ca(self.state, self.ca, approved=True)
        self.assertEqual(list(self.state.iterdir()), [])

    def test_symlink_hardlink_and_unsafe_permissions_are_rejected(self):
        target = self.state / "mqtt-ca.crt"
        other = self.state / "other.pem"
        other.write_text(self.ca); other.chmod(0o600)
        target.symlink_to(other)
        with self.assertRaises(ValueError): setup.import_ca(self.state, self.ca, approved=True)
        target.unlink(); os.link(other, target)
        with self.assertRaises(setup.SetupError): setup.import_ca(self.state, self.ca, approved=True)
        target.unlink(); target.write_text(self.ca); target.chmod(0o644)
        with self.assertRaises(ValueError): setup.import_ca(self.state, self.ca, approved=True)
        self.assertEqual(other.read_text(), self.ca)

    def test_bad_ca_or_atomic_failure_retains_existing_trust_and_cleans_temp(self):
        target = self.state / "mqtt-ca.crt"
        setup.import_ca(self.state, self.ca, approved=True)
        with self.assertRaises(setup.SetupError): setup.import_ca(self.state, self.leaf, approved=True)
        with patch("commissioning.os.replace", side_effect=OSError("synthetic failure")), self.assertRaises(OSError):
            setup.import_ca(self.state, self.ca, approved=True)
        self.assertEqual(target.read_text(), self.ca)
        self.assertFalse((self.state / "mqtt-ca.crt.new").exists())

    def test_import_cannot_follow_a_symlinked_state_directory(self):
        link = self.state / "linked-state"
        link.symlink_to(self.state, target_is_directory=True)
        with self.assertRaises(ValueError): setup.import_ca(link, self.ca, approved=True)
        self.assertFalse((self.state / "mqtt-ca.crt").exists())

    def test_password_save_preserves_selected_ca_even_if_config_file_differs(self):
        setup.import_ca(self.state, self.ca, approved=True)
        source = self.state / "file-manager-ca.pem"
        source.write_text(self.leaf)
        before = (self.state / "mqtt-ca.crt").stat().st_ino
        setup.save_password(self.state, "synthetic-new", "synthetic-new", source)
        self.assertEqual((self.state / "mqtt-ca.crt").read_text(), self.ca)
        self.assertEqual((self.state / "mqtt-ca.crt").stat().st_ino, before)

    def test_file_manager_fallback_remains_supported(self):
        source = self.state / "file-manager-ca.pem"; source.write_text(self.ca)
        setup.save_password(self.state, "synthetic", "synthetic", source)
        self.assertEqual((self.state / "mqtt-ca.crt").read_text(), self.ca)

    def test_missing_openssl_or_parse_failure_cannot_write_trust(self):
        with patch("commissioning.subprocess.run", side_effect=subprocess.TimeoutExpired("openssl", 5)), self.assertRaises(setup.SetupError):
            setup.import_ca(self.state, self.ca, approved=True)
        self.assertEqual(list(self.state.iterdir()), [])


class SetupIngressTests(unittest.IsolatedAsyncioTestCase):
    request = ingress_tests.IngressTests.request
    token = ingress_tests.IngressTests.token

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = Path(self.temp.name)
        atomic_json(self.state / "settings.json", FRESH)
        self.server = ingress.IngressServer(self.state)
        self.ca = certificates()[0]

    async def asyncTearDown(self): self.temp.cleanup()

    async def import_request(self, **changes):
        fields = dict(csrf_token=await self.token("/mqtt/import-ca"), ca_pem=self.ca, approval="yes")
        fields.update(changes)
        return await self.request("POST", "/mqtt/import-ca", fields)

    async def test_ca_form_import_and_response_never_echo_material(self):
        status, body, _ = await self.import_request()
        self.assertEqual(status, 200); self.assertIn("Public CA saved privately", body)
        self.assertNotIn("BEGIN CERTIFICATE", body)
        self.assertEqual((self.state / "mqtt-ca.crt").read_text(), self.ca)

    async def test_ca_only_bundle_above_old_field_limit_can_be_imported(self):
        bundle = self.ca * 6
        self.assertGreater(len(bundle), 2048)
        status, body, _ = await self.import_request(ca_pem=bundle)
        self.assertEqual(status, 200); self.assertIn("Public CA saved privately", body)
        self.assertEqual((self.state / "mqtt-ca.crt").read_text(), bundle)

    async def test_invalid_import_is_redacted_and_action_rate_limited(self):
        for _ in range(10):
            status, body, _ = await self.import_request(ca_pem="synthetic-private-input")
            self.assertEqual(status, 200); self.assertNotIn("synthetic-private-input", body)
            self.assertIn("CA is missing or invalid", body)
        self.assertEqual((await self.import_request(ca_pem="synthetic-private-input"))[0], 429)
        self.assertFalse((self.state / "mqtt-ca.crt").exists())

    async def test_ca_import_rejects_csrf_replay_cross_user_and_missing_approval(self):
        token = await self.token("/mqtt/import-ca")
        fields = dict(csrf_token=token, ca_pem=self.ca, approval="yes")
        self.assertEqual((await self.request("POST", "/mqtt/import-ca", fields, {"X-Remote-User-Id":"other"}))[0],403)
        self.assertEqual((await self.request("POST", "/mqtt/import-ca", fields))[0],403)
        status, body, _ = await self.import_request(approval="no")
        self.assertIn("explicit confirmation", body); self.assertEqual(status,200)
        self.assertFalse((self.state / "mqtt-ca.crt").exists())

    async def test_direct_peer_cross_site_get_and_arbitrary_file_fields_denied(self):
        token = await self.token("/mqtt/import-ca")
        fields = dict(csrf_token=token, ca_pem=self.ca, approval="yes")
        self.assertEqual((await self.request("POST","/mqtt/import-ca",fields,peer="127.0.0.1"))[0],403)
        self.assertEqual((await self.request("POST","/mqtt/import-ca",fields,{"Sec-Fetch-Site":"cross-site"}))[0],403)
        self.assertEqual((await self.request(route="/mqtt/import-ca"))[0],404)
        self.assertEqual((await self.request("POST","/mqtt/import-ca",dict(fields,filename="../escape")))[0],400)
        self.assertEqual((await self.request("POST","/mqtt/import-ca",fields,{"Content-Type":"multipart/form-data"}))[0],415)
        self.assertFalse((self.state / "mqtt-ca.crt").exists())

    async def test_import_size_is_bounded_without_relaxing_other_forms(self):
        self.assertEqual((await self.import_request(ca_pem="X" * (setup.IMPORT_CA_LIMIT+1)))[0],400)
        token=await self.token("/mqtt/test")
        self.assertEqual((await self.request("POST","/mqtt/test",dict(csrf_token=token,extra="X"*8192)))[0],413)
        self.assertFalse((self.state / "mqtt-ca.crt").exists())

    async def test_monitoring_mode_and_state_lock_block_import(self):
        atomic_json(self.state / "settings.json", OPTIONS)
        _, body, _ = await self.import_request()
        self.assertIn("Choose setup", body)
        atomic_json(self.state / "settings.json", FRESH)
        lock=monitor.operation_lock(self.state)
        try:
            _, body, _ = await self.import_request(); self.assertIn("holds the state lock",body)
        finally: os.close(lock)
        self.assertFalse((self.state / "mqtt-ca.crt").exists())

    async def test_incomplete_authentication_has_actionable_safe_error(self):
        token=await self.token("/mqtt/test")
        with patch("commissioning.broker_connack",new=AsyncMock()) as network:
            _, body, _=await self.request("POST","/mqtt/test",dict(csrf_token=token))
            self.assertIn("configuration is incomplete",body); network.assert_not_called()

    async def test_workflow_only_becomes_ready_after_explicit_check_and_resets(self):
        atomic_json(self.state / "settings.json", dict(OPTIONS,operation="setup")); seed_mqtt(self.state)
        self.assertIn("Ready for connection checks",(await self.request())[1])
        token=await self.token("/mqtt/test")
        with patch("commissioning.check_mqtt",new=AsyncMock()):
            await self.request("POST","/mqtt/test",dict(csrf_token=token))
        self.assertIn("Ready for pairing",(await self.request())[1])
        (self.state / "mqtt_password").write_text("synthetic-changed")
        self.assertIn("Ready for connection checks",(await self.request())[1])
        self.server=ingress.IngressServer(self.state)
        self.assertIn("Ready for connection checks",(await self.request())[1])

    async def test_invalid_options_have_safe_guidance_instead_of_secret_exception(self):
        atomic_json(self.state / "settings.json", dict(FRESH,mqtt_tls=False,mqtt_host="synthetic-private-example"))
        status,body,_=await self.request()
        self.assertEqual(status,200);self.assertIn("Invalid configuration",body)
        self.assertNotIn("synthetic-private-example",body)

    async def test_monitoring_and_disconnected_guidance_uses_current_bridge(self):
        atomic_json(self.state / "settings.json", OPTIONS)
        bridge=Mock(); bridge.control_status.return_value=dict(enabled=False,permitted=True,settling=False,off_confirmed=True,changed_at=None,outcome="none",ready=True)
        self.server.heating=bridge
        bridge.report.return_value=dict(ready=True,last_success="synthetic")
        self.assertIn("Paired and monitoring",(await self.request())[1])
        bridge.report.return_value=dict(ready=False,last_success="synthetic")
        self.assertIn("Temporarily disconnected",(await self.request())[1])


class LegacyUpgradeTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_blank_defaults_do_not_replace_saved_scalar_options(self):
        # Matches source-reviewed Supervisor dict-merge/scalar-override semantics.
        legacy = dict(OPTIONS, poll_interval=180, danfoss_allow_writes=True)
        merged = FRESH | legacy
        self.assertEqual(monitor.validate_options(merged), legacy)

    async def test_v030_identity_credentials_override_polling_and_11_rooms_survive(self):
        with tempfile.TemporaryDirectory() as directory:
            state=synthetic_state(Path(directory)/"legacy-state")
            legacy=dict(OPTIONS,poll_interval=180,danfoss_allow_writes=True)
            atomic_json(state/"settings.json",legacy);seed_mqtt(state)
            overlay=dict(mqtt_host="legacy-broker.invalid",mqtt_port=8883,mqtt_username="synthetic-legacy")
            atomic_json(state/"mqtt-settings.json",overlay)
            controller=validate_state(state)
            atomic_json(state/"mqtt_discovery_rooms.json",dict(controller_id=controller,room_ids=list(range(1,12))))
            protected={p.name:p.read_bytes() for p in state.iterdir()}
            effective=monitor.options_from_file(state)
            self.assertEqual(effective,legacy|overlay)
            config=monitor.settings(effective,state)
            self.assertEqual(config.poll_interval,180);self.assertFalse(config.allow_writes)
            sdk=Mock();bridge=heating.HeatingBridge(config,state,sdk,permitted=True)
            self.assertFalse(bridge.enabled);self.assertTrue(bridge.permission())
            bridge.refresh=Mock();bridge._connected()
            rooms=[dict(copy.deepcopy(SNAPSHOT['rooms'][0]),id=i,name=f'Synthetic room {i}') for i in range(1,12)]
            bridge.publish_snapshot(dict(copy.deepcopy(SNAPSHOT),rooms=rooms))
            payloads={c.args[0]:json.loads(c.args[1]) for c in sdk.publish.call_args_list if c.args[0].endswith('/config') and c.args[1]}
            climates={k:v for k,v in payloads.items() if '/climate/' in k}
            temps={k:v for k,v in payloads.items() if k.endswith(('_temperature/config','_setpoint/config'))}
            self.assertEqual(len(climates),11);self.assertEqual(len(temps),22)
            for i in range(1,12):
                c=climates[f'homeassistant/climate/danfoss_link_{controller}/room_{i}/config']
                self.assertEqual(c['unique_id'],f'danfoss_link_{controller}_room_{i}')
                self.assertEqual(c['device']['name'],'Danfoss Link CC')
                self.assertFalse(any('command' in k for k in c))
            self.assertEqual({p.name:p.read_bytes() for p in state.iterdir()},protected)
            self.assertEqual(bridge.controller_id,controller)
            self.assertFalse(any('/temperature/set' in call.args[0] for call in sdk.subscribe.call_args_list))

    async def test_v030_no_override_and_import_keep_pairing_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            state=synthetic_state(Path(directory)/'legacy-state')
            atomic_json(state/'settings.json',OPTIONS);seed_mqtt(state)
            before=identity_hashes(state);old=monitor.options_from_file(state)
            self.assertEqual(old,OPTIONS)
            setup.import_ca(state,certificates()[0],approved=True)
            self.assertEqual(identity_hashes(state),before)
            self.assertEqual(monitor.options_from_file(state),old)
            self.assertFalse(any(p.name.endswith('.new') for p in state.iterdir()))

    async def test_tls_verification_uses_same_saved_ca_as_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            state=Path(directory);seed_mqtt(state)
            config=monitor.settings(OPTIONS,state)
            writer=Mock(wait_closed=AsyncMock())
            with patch('commissioning.asyncio.open_connection',new=AsyncMock(return_value=(Mock(),writer))) as connect:
                await setup.verify_tls(OPTIONS,source=state/'missing-file-manager-ca',state=state)
            ctx=connect.call_args.kwargs['ssl']
            self.assertTrue(ctx.check_hostname);self.assertEqual(ctx.verify_mode,ssl.CERT_REQUIRED)
            self.assertEqual(Path(config.ca_file).read_text(),certificates()[0]);writer.write.assert_not_called()
