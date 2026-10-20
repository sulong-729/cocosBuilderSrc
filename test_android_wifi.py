"""QR pairing protocol tests; no phone, adb server or GUI is used."""
import importlib.util
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from backend import BuildError


class ClockEvent:
    def __init__(self):
        self.now = 0
        self.stopped = False
    def is_set(self):
        return self.stopped
    def wait(self, seconds):
        self.now += seconds
        return self.stopped


class Runner:
    def __init__(self, mdns='', pairing='Successfully paired to 192.168.1.2:37001 [guid=adb-PHONE-abc]', devices=None):
        self.cancelled = ClockEvent()
        self.secrets = []
        self.calls = []
        self.logs = []
        self.mdns = mdns
        self.pairing = pairing
        self.devices = devices or []
    def tool(self, name):
        return name
    def stage(self, value):
        self.logs.append(value)
    def write(self, value):
        self.logs.append(value)
    def run(self, args, **kwargs):
        self.calls.append((args, kwargs))
        if args[1:3] == ['mdns', 'services']:
            return self.mdns
        if args[1] == 'pair':
            return self.pairing
        if args[1] == 'devices':
            return '\n'.join(f"{d['serial']} {d['state']}" for d in self.devices)
        raise AssertionError(args)
    def scan(self):
        return self.devices


class WifiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if importlib.util.find_spec('android_wifi'):
            import android_wifi
            cls.wifi = android_wifi
        else:
            cls.wifi = None
    def setUp(self):
        self.assertIsNotNone(self.wifi, 'QR pairing module must exist')
        self.session = self.wifi.new_pairing_session()
    def pair(self, runner, timeout=2):
        with patch.object(self.wifi.time, 'monotonic', side_effect=lambda: runner.cancelled.now):
            return self.wifi.pair_qr(runner, self.session, timeout)
    def discovery(self):
        return f'{self.session.service}\t_adb-tls-pairing._tcp.\t192.168.1.2:37001\n'
    def test_random_payload_is_adb_protocol_and_repr_hides_secret(self):
        other = self.wifi.new_pairing_session()
        self.assertRegex(self.session.service, r'^studio-[A-Za-z0-9]{10}$')
        self.assertGreaterEqual(len(self.session.password), 12)
        self.assertRegex(self.session.password, r'^[A-Za-z0-9]+$')
        self.assertEqual(self.session.payload, f'WIFI:T:ADB;S:{self.session.service};P:{self.session.password};;')
        self.assertNotEqual(self.session.password, other.password)
        self.assertNotEqual(self.session.service, other.service)
        self.assertNotIn(self.session.password, repr(self.session))
    def test_qr_has_boolean_square_and_quiet_border(self):
        matrix = self.wifi.qr_matrix(self.session.payload)
        self.assertGreater(len(matrix), 28)
        self.assertTrue(all(len(row) == len(matrix) for row in matrix))
        self.assertTrue(all(type(v) is bool for row in matrix for v in row))
        self.assertTrue(any(v for row in matrix for v in row))
        self.assertTrue(all(not any(row) for row in matrix[:4] + matrix[-4:]))
        self.assertTrue(all(not any(row[:4] + row[-4:]) for row in matrix))
    def test_pairs_only_exact_requested_service_sends_secret_via_stdin(self):
        runner = Runner('other _adb-tls-pairing._tcp 10.0.0.9:3000\n' + self.discovery())
        result = self.pair(runner)
        self.assertTrue(result['paired'])
        self.assertEqual(result['serial'], '')
        args, kwargs = next(call for call in runner.calls if call[0][1] == 'pair')
        self.assertEqual(args, ['adb', 'pair', '192.168.1.2:37001'])
        self.assertEqual(kwargs['input_text'], self.session.password + '\n')
        self.assertFalse(kwargs['emit_output'])
        self.assertNotIn(self.session.password, repr(runner.logs))
        self.assertNotIn(self.session.password, repr([call[0] for call in runner.calls]))
        self.assertNotIn(self.session.password, runner.secrets)
    def test_selects_only_online_matching_guid_ignoring_other_phone(self):
        runner = Runner(self.discovery(), devices=[{'serial':'OTHER', 'state':'device','kind':'device'}, {'serial':'adb-PHONE-abc._adb-tls-connect._tcp','state':'device','kind':'device'}])
        self.assertEqual(self.pair(runner)['serial'], 'adb-PHONE-abc._adb-tls-connect._tcp')
    def test_offline_matching_and_unrelated_online_are_not_connected(self):
        runner = Runner(self.discovery(), devices=[{'serial':'adb-PHONE-abc._adb-tls-connect._tcp','state':'offline','kind':'device'}, {'serial':'OTHER','state':'device','kind':'device'}])
        self.assertEqual(self.pair(runner)['serial'], '')
    def test_guid_connect_service_resolves_ip_serial(self):
        runner = Runner(self.discovery() + 'adb-PHONE-abc _adb-tls-connect._tcp 192.168.1.2:41000\n', devices=[{'serial':'192.168.1.2:41000','state':'device','kind':'device'}])
        self.assertEqual(self.pair(runner)['serial'], '192.168.1.2:41000')
    def test_service_prefix_or_wrong_type_never_pairs(self):
        runner = Runner(f'{self.session.service}-other _adb-tls-pairing._tcp 10.0.0.1:1\n{self.session.service} _adb-tls-connect._tcp 10.0.0.1:2')
        with self.assertRaisesRegex(BuildError, 'QR|Wi-Fi|mDNS'):
            self.pair(runner)
        self.assertFalse(any(call[0][1] == 'pair' for call in runner.calls))
    def test_failed_pair_does_not_leak_response_secret(self):
        runner = Runner(self.discovery(), pairing='Failed: ' + self.session.password)
        with self.assertRaises(BuildError) as caught:
            self.pair(runner)
        self.assertNotIn(self.session.password, str(caught.exception))
    def test_failed_unknown_response_with_success_words_is_not_success(self):
        runner = Runner(self.discovery(), pairing='Failed: Successfully paired but server returned unknown response=2')
        with self.assertRaises(BuildError):
            self.pair(runner)
    def test_cancelled_does_not_start_commands(self):
        runner = Runner(self.discovery())
        runner.cancelled.stopped = True
        with self.assertRaisesRegex(BuildError, 'dừng|hủy'):
            self.pair(runner)
        self.assertFalse(runner.calls)
    def test_connection_scan_failure_keeps_successful_pairing(self):
        runner = Runner(self.discovery())
        original = runner.run
        def run(args, **kwargs):
            if args[1] == 'devices':
                raise BuildError('adb connection scan failed')
            return original(args, **kwargs)
        runner.run = run
        result = self.pair(runner)
        self.assertTrue(result['paired'])
        self.assertEqual(result['serial'], '')
    def test_missing_guid_does_not_guess_even_with_online_phone(self):
        runner = Runner(self.discovery(), pairing='Successfully paired to 192.168.1.2:37001', devices=[{'serial':'192.168.1.2:41000','state':'device','kind':'device'}])
        self.assertEqual(self.pair(runner)['serial'], '')
    def test_cancel_after_pair_stops_discovery(self):
        runner = Runner(self.discovery())
        original = runner.run
        def run(args, **kwargs):
            output = original(args, **kwargs)
            if args[1] == 'pair':
                runner.cancelled.stopped = True
            return output
        runner.run = run
        with self.assertRaisesRegex(BuildError, 'dừng'):
            self.pair(runner)
        self.assertNotIn(self.session.password, runner.secrets)
    def test_fully_qualified_ipv6_service_is_supported(self):
        runner = Runner(f'{self.session.service}._adb-tls-pairing._tcp.local. _adb-tls-pairing._tcp.local. [fe80::1234%en0]:37001')
        self.assertTrue(self.pair(runner)['paired'])
        args = next(call[0] for call in runner.calls if call[0][1] == 'pair')
        self.assertEqual(args[-1], '[fe80::1234%en0]:37001')
    def test_real_runner_does_not_log_pairing_stdin_or_echoed_secret(self):
        from android_backend import AndroidRunner
        with tempfile.TemporaryDirectory() as directory:
            adb = Path(directory) / 'adb'
            adb.write_text("#!/bin/sh\nif [ \"$1\" = mdns ]; then\n  echo '" + self.session.service + " _adb-tls-pairing._tcp 192.168.1.2:37001'\nelif [ \"$1\" = pair ]; then\n  read code\n  echo \"$code\"\n  echo 'Successfully paired to 192.168.1.2:37001 [guid=adb-PHONE-abc]'\nelif [ \"$1\" = devices ]; then\n  echo 'adb-PHONE-abc._adb-tls-connect._tcp device model:Phone'\nfi\n")
            adb.chmod(0o755)
            logs = []
            runner = AndroidRunner({}, logs.append, logs.append)
            runner.tool = lambda name: adb
            result = self.wifi.pair_qr(runner, self.session, timeout=3)
            self.assertEqual(result['serial'], 'adb-PHONE-abc._adb-tls-connect._tcp')
            self.assertNotIn(self.session.password, '\n'.join(logs))
            self.assertNotIn(self.session.password, runner.secrets)
    def test_invalid_mdns_endpoint_cannot_be_used_as_option(self):
        runner = Runner(f'{self.session.service} _adb-tls-pairing._tcp -a:37001\n')
        with self.assertRaises(BuildError):
            self.pair(runner)
        self.assertFalse(any(call[0][1] == 'pair' for call in runner.calls))

if __name__ == '__main__':
    unittest.main()
