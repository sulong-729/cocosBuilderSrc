import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from app import Window

APP = QApplication.instance() or QApplication([])

class AndroidUITests(unittest.TestCase):
    def test_android_only_project_and_independent_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); (root / 'assets').mkdir()
            (root / 'package.json').write_text(json.dumps({'creator': {'version': '3.7.3'}}))
            (root / 'buildCmd').mkdir()
            (root / 'buildCmd/buildConfig_android.json').write_text(json.dumps({'platform': 'android', 'debug': True, 'scenes': [{'uuid': 's', 'url': 'Main.scene'}], 'startScene': 's', 'packages': {'android': {'packageName': 'com.test.game', 'appABIs': ['arm64-v8a'], 'apiLevel': 33}}}))
            with patch('app.Path.home', return_value=root), patch.object(Window, 'scan'), patch.object(Window, 'load_teams'), patch.object(Window, 'check_tools'):
                window = Window()
                try:
                    self.assertEqual([window.platform_tabs.tabText(i) for i in range(2)], ['iOS', 'Android'])
                    window.load_project(str(root))
                    panel = window.android_panel
                    self.assertEqual(panel.info['root'], str(root))
                    self.assertEqual(panel.config.count(), 1)
                    self.assertEqual(panel.build_config.options()['packages']['android']['packageName'], 'com.test.game')
                    self.assertEqual(window.platform_tabs.currentIndex(), 1)
                    panel.build_config.fields['packages.android.packageName'].setText('com.test.changed')
                    panel.save()
                    saved = window.settings['projects'][str(root)]['android']
                    self.assertEqual(saved['buildOptions']['file']['packages']['android']['packageName'], 'com.test.changed')
                    self.assertNotIn('buildOptions', window.settings['projects'][str(root)])
                    panel.load_project(str(root))
                    self.assertEqual(panel.build_config.options()['packages']['android']['packageName'], 'com.test.changed')
                finally:
                    window.crash_panel.timer.stop(); window.live_timer.stop(); window.log_timer.stop()
                    if hasattr(window, 'android_panel'): window.android_panel.timer.stop()
                    window.close()

    def test_android_configuration_preserves_extensions(self):
        from build_config_panel import BuildConfigPanel
        panel = BuildConfigPanel(platform='android')
        options = {'debug': True, 'packages': {'android': {'packageName': 'com.test.app', 'appABIs': ['x86_64'], 'apiLevel': 33, 'custom': 7}}, 'scenes': [{'uuid': 'a'}], 'startScene': 'a'}
        panel.load(options)
        self.assertEqual(panel.options()['packages']['android']['custom'], 7)
        self.assertEqual(panel.options()['packages']['android']['appABIs'], ['x86_64'])
        self.assertNotIn('ios', panel.options()['packages'])




class DependencyNoticeUITests(unittest.TestCase):
    def test_missing_tools_visible_in_banner_and_yellow_log_without_duplicates(self):
        from log_style import LogHighlighter
        with tempfile.TemporaryDirectory() as temp:
            with patch('app.Path.home',return_value=Path(temp)),patch.object(Window,'scan'),patch.object(Window,'load_teams'),patch.object(Window,'check_tools'):
                window=Window()
                try:
                    panel=window.android_panel
                    issues=['Thiếu avdmanager. Cài Android SDK Command-line Tools (latest) trong SDK Manager → SDK Tools.']
                    panel.tools_checked(issues,repeat=False)
                    panel.flush_log()
                    self.assertFalse(panel.dependency_notice.isHidden())
                    self.assertIn('avdmanager',panel.dependency_message.text())
                    self.assertIn('Command-line Tools',panel.log.toPlainText())
                    self.assertEqual(LogHighlighter.level(panel.log.toPlainText()),'warning')
                    count=len(panel.history)
                    panel.tools_checked(issues,repeat=False);panel.flush_log()
                    self.assertEqual(len(panel.history),count)
                    panel.tools_checked([],repeat=False)
                    self.assertTrue(panel.dependency_notice.isHidden())
                finally:
                    window.crash_panel.timer.stop();window.live_timer.stop();window.log_timer.stop();window.android_panel.timer.stop();window.close()


    def test_dependency_failure_opens_install_notification(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch('app.Path.home',return_value=Path(temp)),patch.object(Window,'scan'),patch.object(Window,'load_teams'),patch.object(Window,'check_tools'):
                window=Window()
                try:
                    panel=window.android_panel
                    issue='Thiếu avdmanager. Cài Android SDK Command-line Tools (latest).'
                    with patch.object(panel,'show_dependency_notification') as notify:
                        panel.finished({'ok':False,'name':'Tạo AVD','error':issue,'dependencies':[issue]})
                    notify.assert_called_once()
                    self.assertEqual(panel.dependency_issues,[issue])
                    self.assertFalse(panel.dependency_notice.isHidden())
                    with patch('android_panel.QMessageBox') as messagebox:
                        panel.show_dependency_notification()
                        messagebox.return_value.setInformativeText.assert_called_once_with(issue)
                        messagebox.return_value.exec.assert_called_once()
                finally:
                    window.crash_panel.timer.stop();window.live_timer.stop();window.log_timer.stop();window.android_panel.timer.stop();window.close()

if __name__ == '__main__': unittest.main()
