import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from app import Window
from android_panel import AndroidPanel
APP=QApplication.instance() or QApplication([])

class DeviceUITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();(self.root/'assets').mkdir()
        (self.root/'package.json').write_text('{"creator":{"version":"3.7.3"}}')
        (self.root/'buildCmd').mkdir()
        (self.root/'buildCmd/buildConfig_android.json').write_text(json.dumps({'platform':'android','scenes':[{'uuid':'a'}],'startScene':'a','packages':{'android':{'packageName':'com.test.app','appABIs':['arm64-v8a'],'apiLevel':29}}}))
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch('app.Path.home',return_value=self.root))
        for name in ('scan','load_teams','check_tools'):self.stack.enter_context(patch.object(Window,name))
        self.sync_patch = patch.object(AndroidPanel, 'sync_logcat')
        self.stack.enter_context(self.sync_patch)
        self.window=Window();self.window.load_project(str(self.root));self.panel=self.window.android_panel
        self.addCleanup(self.close_window)

    def close_window(self):
        self.window.crash_panel.timer.stop();self.window.live_timer.stop();self.window.log_timer.stop();self.panel.timer.stop()
        if hasattr(self.panel,'device_timer'):self.panel.device_timer.stop()
        self.window.close()

    def test_build_run_clickable_without_device_and_explains_missing_selection(self):
        self.assertTrue(self.panel.build_run_button.isEnabled())
        with patch('android_panel.QMessageBox.warning') as notice,patch.object(self.panel,'task') as task:
            self.panel.start_build(True)
        notice.assert_called_once()
        self.assertIn('thiết bị',notice.call_args.args[2])
        task.assert_not_called()

    def test_single_target_dropdown_and_mode_specific_controls(self):
        self.assertFalse(hasattr(self.panel,'avd'))
        self.assertFalse(self.panel.emulator_controls.isHidden())
        self.assertTrue(self.panel.physical_controls.isHidden())
        self.panel.mode.setCurrentIndex(1)
        self.assertTrue(self.panel.emulator_controls.isHidden())
        self.assertFalse(self.panel.physical_controls.isHidden())
        self.assertFalse(self.panel.qr_button.isHidden())

    def test_stopped_selection_tracks_same_avd_after_boot_and_never_switches(self):
        first={'id':'avd:chosen','kind':'emulator','name':'chosen','avd':'chosen','serial':'','state':'stopped'}
        other={'id':'avd:other','kind':'emulator','name':'other','avd':'other','serial':'emulator-5556','state':'device'}
        self.panel.devices_scanned([first,other])
        self.panel.device.setCurrentIndex(1)
        self.assertEqual(self.panel.device.currentData()['id'],'avd:chosen')
        booted={**first,'serial':'emulator-5554','state':'device'}
        self.panel.devices_scanned([other,booted])
        self.assertEqual(self.panel.device.currentData()['serial'],'emulator-5554')
        self.panel.devices_scanned([other])
        self.assertEqual(self.panel.device.currentData()['id'],'avd:chosen')
        self.assertNotEqual(self.panel.device.currentData()['state'],'device')

    def test_open_avd_uses_selected_single_dropdown_target(self):
        target={'id':'avd:chosen','kind':'emulator','name':'chosen','avd':'chosen','serial':'','state':'stopped'}
        self.panel.devices_scanned([target]);self.panel.device.setCurrentIndex(1)
        with patch.object(self.panel,'task') as task:
            self.panel.start_avd()
        runner=__import__('unittest.mock',fromlist=['Mock']).Mock()
        task.call_args.args[1](runner)
        runner.start_avd.assert_called_once_with('chosen')

    def test_device_poll_does_not_lock_build_and_run(self):
        with patch('android_panel.threading.Thread') as thread:
            self.panel.poll_devices(force=True)
        thread.return_value.start.assert_called_once()
        self.assertIsNone(self.panel.runner)
        self.assertTrue(self.panel.build_run_button.isEnabled())

    def test_platform_spinner_tracks_only_active_side_and_stops(self):
        from unittest.mock import Mock
        self.window.builder = Mock(monitoring=False)
        self.window.platform_device_counts = [2, 1]
        self.window.refresh_platform_status()
        ios, android = self.window.platform_badges
        self.assertTrue(ios.timer.isActive())
        self.assertFalse(android.timer.isActive())
        self.assertEqual((ios.count, android.count), (2, 1))
        before = ios.angle
        ios.advance()
        self.assertNotEqual(ios.angle, before)
        self.window.builder = None
        self.panel.runner = Mock(monitoring=False)
        self.window.refresh_platform_status()
        self.assertFalse(ios.timer.isActive())
        self.assertTrue(android.timer.isActive())
        self.panel.runner = None
        self.window.refresh_platform_status()
        self.assertFalse(android.timer.isActive())

    def test_device_count_result_updates_both_tabs(self):
        self.window.platform_counts_updated({0: 3, 1: 2})
        self.window.refresh_platform_status()
        self.assertEqual([badge.count for badge in self.window.platform_badges], [3, 2])

    def test_refresh_selects_running_emulator_even_with_unchanged_inventory(self):
        from device_combo import BOOTED_ROLE
        stopped = {'id':'avd:off','kind':'emulator','name':'off','avd':'off','serial':'','state':'stopped'}
        running = {'id':'avd:on','kind':'emulator','name':'on','avd':'on','serial':'emulator-5554','state':'device'}
        booting = {'id':'avd:boot','kind':'emulator','name':'boot','avd':'boot','serial':'emulator-5556','state':'booting'}
        self.panel.devices_scanned([stopped, running, booting])
        self.panel.device.setCurrentIndex(1)
        with patch.object(self.panel, 'poll_devices'):
            self.panel.scan_devices()
        self.panel.inventory_updated({'sdk':self.panel.tools()['sdk'], 'targets':[stopped,running,booting]})
        self.assertEqual(self.panel.device.currentData()['id'], 'avd:on')
        self.assertFalse(self.panel.device.itemData(1, BOOTED_ROLE))
        self.assertTrue(self.panel.device.itemData(2, BOOTED_ROLE))
        self.assertFalse(self.panel.device.itemData(3, BOOTED_ROLE))

    def test_refresh_preserves_current_running_emulator_when_multiple_are_on(self):
        devices = [{'id':'avd:'+name,'kind':'emulator','name':name,'avd':name,'serial':serial,'state':'device'} for name,serial in [('a','emulator-5554'),('b','emulator-5556')]]
        self.panel.devices_scanned(devices)
        self.panel.device.setCurrentIndex(2)
        self.panel.pick_running_emulator()
        self.assertEqual(self.panel.device.currentData()['id'], 'avd:b')

    def test_ios_refresh_prefers_booted_simulator_over_saved_shutdown_device(self):
        devices = [{'id':'off','kind':'simulator','name':'off','state':'Shutdown','runtime':'iOS'}, {'id':'on','kind':'simulator','name':'on','state':'Booted','runtime':'iOS'}]
        self.window.mode.setCurrentIndex(self.window.mode.findData('simulator'))
        self.window.info = {'root':str(self.root),'version':'3.7.3'}
        self.window.settings['projects'][str(self.root)] = {'device':'off'}
        self.window.scanned({'kind':'simulator','devices':devices}, '')
        self.assertEqual(self.window.device.currentData()['id'], 'on')

    def test_android_power_matches_ios_colors_and_toggles_selected_avd(self):
        target={'id':'avd:test','kind':'emulator','name':'test','avd':'test','serial':'','state':'stopped'}
        self.panel.devices_scanned([target]);self.panel.device.setCurrentIndex(1)
        self.assertTrue(self.panel.power_avd_button.isEnabled())
        self.assertIn('#166534',self.panel.power_avd_button.styleSheet())
        with patch.object(self.panel,'start_avd') as start,patch.object(self.panel,'stop_avd') as stop:
            self.panel.power_avd_button.click()
            start.assert_called_once();stop.assert_not_called()
        self.panel.devices_scanned([{**target,'serial':'emulator-5554','state':'device'}])
        self.assertIn('#7f1d1d',self.panel.power_avd_button.styleSheet())
        with patch.object(self.panel,'start_avd') as start,patch.object(self.panel,'stop_avd') as stop:
            self.panel.power_avd_button.click()
            stop.assert_called_once();start.assert_not_called()
        self.panel.devices_scanned([{**target,'serial':'emulator-5554','state':'booting'}])
        self.assertFalse(self.panel.power_avd_button.isEnabled())

    def test_auto_logcat_switches_devices_without_locking_build_controls(self):
        from unittest.mock import Mock
        from PySide6.QtWidgets import QPushButton
        self.sync_patch.__exit__(None,None,None)
        devices=[{'id':'avd:'+name,'kind':'emulator','name':name,'avd':name,'serial':serial,'state':'device'} for name,serial in [('a','emulator-5554'),('b','emulator-5556')]]
        first,second=Mock(),Mock()
        with patch('android_panel.AndroidRunner',side_effect=[first,second]) as factory,patch('android_panel.threading.Thread'):
            self.panel.devices_scanned(devices)
            self.panel.device.setCurrentIndex(1)
            self.assertIs(self.panel.log_runner,first)
            self.assertFalse(self.panel.busy)
            self.assertTrue(self.panel.build_run_button.isEnabled())
            self.panel.sync_logcat()
            self.assertEqual(factory.call_count,1)
            self.panel.device.setCurrentIndex(2)
            first.cancel.assert_called_once()
            self.assertIs(self.panel.log_runner,second)
            self.panel.logcat_finished({'runner':first,'error':'stale failure'})
            self.assertIs(self.panel.log_runner,second)
            self.panel.device.setCurrentIndex(0)
            second.cancel.assert_called_once()
            self.assertIsNone(self.panel.log_runner)
        texts=[b.text() for b in self.panel.findChildren(QPushButton)]
        for removed in ('Logcat','Mở output','Mở project trong Studio','Crash thiết bị'):
            self.assertNotIn(removed,texts)
