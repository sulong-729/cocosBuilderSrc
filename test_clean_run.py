import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backend import Builder,BuildError

class CleanRunTests(unittest.TestCase):
    def test_clean_simulator_uninstalls_then_installs_and_launches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);builder=Builder(lambda _:None,lambda _:None)
            device={'id':'sim','name':'Test','kind':'simulator','state':'Booted'}
            calls=[]
            def capture(args,**kw):
                if 'devices' in args:return json.dumps({'devices':{'ios':[{'udid':'sim','state':'Booted'}]}})
                if 'listapps' in args:return '{}'
                return ''
            with (root/'run.log').open('w') as logfile,patch('backend.capture',side_effect=capture),patch('backend.simulator_app_processes',return_value=[]),patch.object(builder,'run',side_effect=lambda args,*a,**k:calls.append(list(map(str,args)))):
                builder.logfile=logfile
                builder.deploy(root,root/'new.app','com.test.game',device,'arm64',False,run_only=True,clean=True)
            actions=[c[2] for c in calls if len(c)>2 and c[1]=='simctl']
            self.assertLess(actions.index('uninstall'),actions.index('install'))
            self.assertLess(actions.index('install'),actions.index('launch'))
    def test_missing_artifact_never_deletes_installed_game(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=Builder(lambda _:None,lambda _:None)
            with patch.object(b,'run') as run:
                with self.assertRaises(BuildError):
                    b.run_existing(tmp,{'debug':True},'com.test.game',{'id':'sim','name':'Test','kind':'simulator','state':'Booted'},False,True,clean=True)
                run.assert_not_called()
