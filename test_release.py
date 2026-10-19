import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree

import build_release


class ReleaseTests(unittest.TestCase):
    def test_distribution_without_credentials_stops_before_setup(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'release.toml'
            config.write_text('[distribution]\napplication_identity=""\ninstaller_identity=""\nnotary_profile=""\n')
            with patch('setup_tool.setup') as setup:
                with self.assertRaisesRegex(ValueError, 'application_identity'):
                    build_release.build(config_path=config)
                setup.assert_not_called()

    def test_installer_requests_system_authorization(self):
        xml = ElementTree.fromstring(build_release.distribution_xml())
        self.assertEqual(xml.find('domains').get('enable_currentUserHome'), 'false')
        package = next(p for p in xml.findall('pkg-ref') if p.text)
        self.assertEqual(package.get('auth'), 'root')

    def test_notary_rejection_does_not_staple_or_assess(self):
        result = __import__('subprocess').CompletedProcess([], 0, json.dumps({'id': 'job', 'status': 'Invalid'}))
        with patch('subprocess.run', return_value=result) as process:
            with self.assertRaisesRegex(RuntimeError, 'Invalid'):
                build_release.notarize(Path('/tmp/example.pkg'), 'test-profile')
            self.assertEqual(process.call_count, 1)

    def test_signing_finds_embedded_code_before_containing_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / 'Example.app'
            framework = app / 'Contents/Resources/lib/QtCore.framework'
            binary = framework / 'Versions/A/QtCore'
            binary.parent.mkdir(parents=True)
            binary.write_bytes(bytes.fromhex('cffaedfe') + b'example')
            (framework / 'QtCore').symlink_to('Versions/A/QtCore')
            (app / 'Contents/Resources/data.txt').write_text('plain data')
            self.assertEqual(build_release.signing_targets(app), [binary, framework, app])
