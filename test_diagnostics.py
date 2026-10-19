import json
import tempfile
import unittest
from pathlib import Path

class DiagnosticsTests(unittest.TestCase):
    def test_two_json_objects_and_crashed_thread(self):
        import diagnostics
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'game.ips'
            p.write_text(json.dumps({'app_name':'Game'})+'\n'+json.dumps({'procPath':'/Devices/ABC/data/Game.app/Game','faultingThread':1,'threads':[{'frames':[]},{'frames':[{'imageIndex':0,'imageOffset':12}]}],'usedImages':[{'name':'Game','base':4096}]}))
            report = diagnostics.read_report(p)
            self.assertEqual(report['frames'][0]['address'],4108)
            self.assertTrue(diagnostics.matches(report,'Game','ABC'))
            self.assertFalse(diagnostics.matches(report,'Other','ABC'))
            self.assertFalse(diagnostics.matches(report,'Game','DEF'))
    def test_source_excerpt_missing_file_safe(self):
        import diagnostics
        self.assertIn('Không',diagnostics.source_excerpt('/missing/no.cpp',12))
    def test_symbol_mismatch_never_symbolicates(self):
        import diagnostics
        self.assertFalse(diagnostics.uuid_matches('UUID: ABC (arm64) path','DEF','arm64'))
        self.assertTrue(diagnostics.uuid_matches('UUID: AB-CD (arm64) path','abcd','arm64'))
