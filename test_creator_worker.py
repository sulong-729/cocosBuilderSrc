from pathlib import Path
import plistlib
import tempfile
import shutil
import unittest
from concurrent.futures import ThreadPoolExecutor
import time
from unittest.mock import patch


class CreatorWorkerTests(unittest.TestCase):
    def test_worker_is_agent_only_and_keeps_installed_creator_untouched(self):
        from android_backend import prepare_creator_cli
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);contents=root/'Creator.app/Contents'
            (contents/'MacOS').mkdir(parents=True)
            for name in ('Resources','Frameworks'):(contents/name).mkdir()
            (contents/'Resources/app.asar').write_bytes(b'fake asar')
            executable=contents/'MacOS/CocosCreator';executable.write_bytes(b'fake executable')
            info=contents/'Info.plist';info.write_bytes(plistlib.dumps({'CFBundleExecutable':'CocosCreator','CFBundleIdentifier':'com.cocos.creator','CFBundleName':'CocosCreator','CFBundleURLTypes':[{'CFBundleURLSchemes':['cocos']}] }))
            helper=contents/'Frameworks/CocosCreator Helper.app/Contents/MacOS/helper'
            helper.parent.mkdir(parents=True);helper.write_bytes(b'helper binary')
            original=info.read_bytes()
            def command(args,**kwargs):
                if args[0]=='/bin/cp':
                    time.sleep(0.03)
                    shutil.copytree(args[-2],args[-1],symlinks=True)
            with patch('android_backend.sys.platform','darwin'),patch('android_backend.subprocess.run',side_effect=command) as sign:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    one=pool.submit(prepare_creator_cli,str(executable),root/'cache')
                    two=pool.submit(prepare_creator_cli,str(executable),root/'cache')
                    worker,other=one.result(),two.result()
            self.assertEqual(worker,other)
            metadata=plistlib.loads((worker.parents[1]/'Info.plist').read_bytes())
            self.assertTrue(metadata['LSUIElement'])
            self.assertNotIn('CFBundleURLTypes',metadata)
            self.assertEqual(info.read_bytes(),original)
            self.assertEqual(executable.read_bytes(),b'fake executable')
            self.assertFalse(worker.is_symlink())
            self.assertFalse((worker.parents[1]/'Resources').is_symlink())
            self.assertFalse((worker.parents[1]/'Frameworks').is_symlink())
            self.assertEqual((worker.parents[1]/'Frameworks/CocosCreator Helper.app/Contents/MacOS/helper').read_bytes(),b'helper binary')
            self.assertEqual(sign.call_count,2)
            self.assertNotIn('--deep',sign.call_args.args[0])

    def test_cli_reuses_installed_engine_and_respects_custom_engine_preferences(self):
        from android_backend import creator_engine_arguments
        import json
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);contents=root/'Creator.app/Contents'
            (contents/'MacOS').mkdir(parents=True)
            source=contents/'MacOS/CocosCreator';source.write_bytes(b'executable')
            (contents/'Info.plist').write_bytes(plistlib.dumps({'CFBundleShortVersionString':'3.7.3'}))
            engine=contents/'Resources/resources/3d/engine';(engine/'native').mkdir(parents=True)
            with patch('android_backend.Path.home',return_value=root):
                self.assertEqual(creator_engine_arguments(str(source)),['--engine',str(engine)])
                prefs=root/'.CocosCreator/profiles/v2/packages/engine.json';prefs.parent.mkdir(parents=True)
                prefs.write_text(json.dumps({'engine':{'373':{'native':{'builtin':False,'path':'/custom/engine'}}}}))
                self.assertEqual(creator_engine_arguments(str(source)),[])
