from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import setup_tool

class SetupQRTests(unittest.TestCase):
    def test_existing_runtime_installs_new_qr_dependency_without_recreating_venv(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);venv=root/'venv';(venv/'bin').mkdir(parents=True);(venv/'bin/python').touch()
            uv=root/'bootstrap/bin/uv';uv.parent.mkdir(parents=True);uv.touch()
            commands=[]
            def run(args,**kw):
                commands.append(args)
                return subprocess.CompletedProcess(args,1 if args[-1]=='import qrcode' else 0)
            app=root/'Debug.app'
            with patch.object(setup_tool,'OUTPUT',root),patch.object(setup_tool,'VENV',venv),patch.object(setup_tool,'APP',app),patch('setup_tool.subprocess.run',side_effect=run):
                setup_tool.setup()
            self.assertTrue(any('pip' in c and 'install' in c for c in commands))
            self.assertFalse(any('venv' in c or ('python' in c and 'install' in c) for c in commands))
            self.assertTrue((app/'Contents/Resources/android_wifi.py').is_file())
