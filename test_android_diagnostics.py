import tempfile
import unittest
from pathlib import Path
from android_backend import AndroidRunner
from log_style import LogHighlighter


class DiagnosticsTests(unittest.TestCase):
    def test_versions_and_installed_ranges_are_logged(self):
        with tempfile.TemporaryDirectory() as folder:
            sdk = Path(folder)
            for name in ('android-29', 'android-34'):
                (sdk / 'platforms' / name).mkdir(parents=True)
            ndk = sdk / 'ndk/23.1.7779620'
            ndk.mkdir(parents=True)
            (ndk / 'source.properties').write_text('Pkg.Revision = 23.1.7779620\n')
            lines = []
            runner = AndroidRunner({'sdk': folder, 'ndk': str(ndk)}, lines.append, lambda _: None)
            runner.log_toolchain({'packages': {'android': {'apiLevel': 29}}, 'builderAndroid': {'minSdk': 24, 'compileSdk': 34}})
            text = '\n'.join(lines)
            for value in ('29 → 34', '23.1.7779620', 'minSdk=24', 'targetSdk=29', 'compileSdk=34'):
                self.assertIn(value, text)
            self.assertTrue(all(LogHighlighter.level(line) == 'toolchain' for line in lines))
            self.assertIn('không khai báo', text)

    def test_missing_tools_still_emit_green_parameters(self):
        lines = []
        runner = AndroidRunner({'sdk': '/missing', 'ndk': '/missing'}, lines.append, lambda _: None)
        runner.log_toolchain({})
        self.assertIn('chưa cài', '\n'.join(lines))
        self.assertTrue(all(LogHighlighter.level(line) == 'toolchain' for line in lines))
        self.assertEqual(LogHighlighter.level('Error: Thiếu SDK'), 'error')
        self.assertEqual(LogHighlighter.level('Warning: Thiếu NDK'), 'warning')

    def test_green_format_is_applied_to_document(self):
        from PySide6.QtGui import QTextDocument
        document = QTextDocument('[Android Tools] SDK: 29 → 34')
        highlighter = LogHighlighter(document)
        highlighter.rehighlight()
        ranges = document.firstBlock().layout().formats()
        self.assertEqual(ranges[0].format.foreground().color().name(), '#8cdda4')
