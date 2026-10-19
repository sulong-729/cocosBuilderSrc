import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from build_config_panel import BuildConfigPanel

APP=QApplication.instance() or QApplication([])

class PanelTests(unittest.TestCase):
    def test_auto_rotate_defaults_true_for_existing_profiles(self):
        panel=BuildConfigPanel()
        panel.load({})
        self.assertTrue(panel.options()["builderAutoRotate"])
        panel.load({"builderAutoRotate":False})
        self.assertFalse(panel.options()["builderAutoRotate"])

    def test_collapse_preserves_edited_values(self):
        panel=BuildConfigPanel()
        panel.debug.setCurrentIndex(1)
        self.assertTrue(panel.body.isHidden())
        panel.toggle.click()
        self.assertFalse(panel.body.isHidden())
        panel.toggle.click()
        self.assertTrue(panel.body.isHidden())
        self.assertFalse(panel.options()['debug'])

    def test_edit_preserves_extension_and_unselected_scene_can_return(self):
        options={'debug':True,'scenes':[{'uuid':'a','url':'a.scene'}],'startScene':'a','packages':{'custom':{'keep':42}}}
        p=BuildConfigPanel();p.load(options)
        p.debug.setCurrentIndex(1)
        edited=p.options()
        self.assertFalse(edited['debug'])
        self.assertEqual(edited['packages']['custom']['keep'],42)
        self.assertTrue(options['debug'])
        self.assertEqual(edited['scenes'],options['scenes'])

    def test_projects_remember_distinct_options_when_switching(self):
        from app import Window
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)
            for name in ['a','b']:
                root=home/name
                (root/'assets').mkdir(parents=True)
                (root/'package.json').write_text(json.dumps({'creator':{'version':'3.7.3'}}))
                (root/'buildCmd').mkdir()
                (root/'buildCmd/buildConfig_ios.json').write_text(json.dumps({'platform':'ios','debug':True,'scenes':[{'uuid':'s','url':'s.scene'}],'startScene':'s','packages':{'ios':{'packageName':'com.test.'+name}}}))
            with patch('app.Path.home',return_value=home),patch.object(Window,'scan'),patch.object(Window,'load_teams'),patch.object(Window,'check_tools'):
                w=Window()
                w.load_project(str(home/'a'))
                w.build_config.debug.setCurrentIndex(1)
                w.load_project(str(home/'b'))
                self.assertTrue(w.build_config.options()['debug'])
                w.load_project(str(home/'a'))
                self.assertFalse(w.build_config.options()['debug'])
                self.assertEqual(w.project_list.count(),2)
                saved=json.loads(w.settings_path.read_text())
                self.assertEqual(len(saved['projects']),2)
                w.crash_panel.timer.stop();w.live_timer.stop();w.log_timer.stop()
                w.close()
