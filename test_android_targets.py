import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from android_backend import AndroidRunner, AndroidDependencyError, AndroidDeviceError, merge_android_targets

class TargetTests(unittest.TestCase):
    def test_running_avd_and_stopped_avd_share_single_target_list(self):
        result=merge_android_targets(['pixel6a','pixel8'],[
            {'serial':'emulator-5554','kind':'emulator','name':'sdk','state':'device','avd':'pixel6a'},
            {'serial':'USB123','kind':'device','name':'Phone','state':'unauthorized'}])
        self.assertEqual(len(result),3)
        byid={d['id']:d for d in result}
        self.assertEqual(byid['avd:pixel6a']['serial'],'emulator-5554')
        self.assertEqual(byid['avd:pixel8']['state'],'stopped')
        self.assertEqual(byid['serial:USB123']['state'],'unauthorized')

    def test_selected_avd_is_not_replaced_by_other_running_emulator(self):
        runner=AndroidRunner({},lambda _:None,lambda _:None)
        targets=merge_android_targets(['chosen','other'],[{'serial':'emulator-5556','kind':'emulator','name':'sdk','avd':'other','state':'device'}])
        with patch.object(runner,'list_targets',return_value=targets):
            with self.assertRaisesRegex(AndroidDeviceError,'chosen'):
                runner.require_target({'id':'avd:chosen','avd':'chosen','kind':'emulator'})
            self.assertEqual(runner.require_target({'id':'avd:other','avd':'other','kind':'emulator'})['serial'],'emulator-5556')

    def test_unauthorized_phone_has_rsa_instructions(self):
        runner=AndroidRunner({},lambda _:None,lambda _:None)
        targets=merge_android_targets([], [{'serial':'USB123','kind':'device','name':'Phone','state':'unauthorized'}])
        with patch.object(runner,'list_targets',return_value=targets):
            with self.assertRaisesRegex(AndroidDeviceError,'RSA'):
                runner.require_target({'id':'serial:USB123','serial':'USB123','kind':'device'})

    def test_auto_java_uses_compatible_jdk_without_changing_studio(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);wrapper=root/'gradle/wrapper';wrapper.mkdir(parents=True)
            (wrapper/'gradle-wrapper.properties').write_text('distributionUrl=https://services.gradle.org/distributions/gradle-6.5.1-all.zip')
            homes=[]
            for major in (21,11):
                home=root/str(major);(home/'bin').mkdir(parents=True);(home/'bin/java').touch()
                (home/'release').write_text(f'JAVA_VERSION="{major}.0.1"');homes.append(str(home))
            chosen=[]
            runner=AndroidRunner({'java':homes[0],'studio':'Studio2025'},lambda _:None,lambda _:None,java_selected=chosen.append)
            with patch('android_backend.discover_java_homes',return_value=homes):
                runner.ensure_gradle_java(root)
            self.assertEqual(runner.tools['java'],homes[1])
            self.assertEqual(runner.tools['studio'],'Studio2025')
            self.assertEqual(chosen,[homes[1]])

    def test_missing_compatible_java_is_actionable_dependency(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);wrapper=root/'gradle/wrapper';wrapper.mkdir(parents=True)
            (wrapper/'gradle-wrapper.properties').write_text('distributionUrl=https://services.gradle.org/distributions/gradle-6.5.1-all.zip')
            with patch('android_backend.discover_java_homes',return_value=[]):
                with self.assertRaisesRegex(AndroidDependencyError,'JDK'):
                    AndroidRunner({'java':''},lambda _:None,lambda _:None).ensure_gradle_java(root)

class TargetRaceTests(unittest.TestCase):
    def test_two_instances_of_same_avd_keep_selected_serial_on_reorder(self):
        a={'serial':'emulator-5554','kind':'emulator','name':'sdk','avd':'same','state':'device'}
        b={**a,'serial':'emulator-5556'}
        initial=merge_android_targets(['same'],[a,b])
        selected=next(t for t in initial if t['serial']=='emulator-5554')
        latest=merge_android_targets(['same'],[b,a])
        runner=AndroidRunner({},lambda _:None,lambda _:None)
        with patch.object(runner,'list_targets',return_value=latest):
            self.assertEqual(runner.require_target(selected)['serial'],'emulator-5554')

    def test_reused_serial_for_different_avd_is_rejected(self):
        selected={'id':'avd:chosen','name':'chosen','avd':'chosen','serial':'emulator-5554','kind':'emulator'}
        latest=merge_android_targets(['other'],[{'serial':'emulator-5554','kind':'emulator','name':'sdk','avd':'other','state':'device'}])
        with patch.object(AndroidRunner,'list_targets',return_value=latest):
            with self.assertRaises(AndroidDeviceError):
                AndroidRunner({},lambda _:None,lambda _:None).require_target(selected)

    def test_unresponsive_unrelated_emulator_does_not_hide_phone(self):
        from backend import BuildError
        runner=AndroidRunner({'sdk':'/sdk'},lambda _:None,lambda _:None)
        data=[{'serial':'emulator-5554','kind':'emulator','name':'sdk','state':'device'},
              {'serial':'USB123','kind':'device','name':'Phone','state':'device'}]
        with patch.object(runner,'scan',return_value=data),patch.object(runner,'adb',side_effect=BuildError('offline')):
            targets=runner.list_targets()
        self.assertTrue(any(t['serial']=='USB123' and t['state']=='device' for t in targets))

class SDKJavaTests(unittest.TestCase):
    def test_sdk_manager_uses_modern_java_without_changing_build_java(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);homes=[]
            for major in (11,21):
                home=root/str(major);home.mkdir();(home/'release').write_text(f'JAVA_VERSION="{major}.0.1"');homes.append(str(home))
            runner=AndroidRunner({'java':homes[0]},lambda _:None,lambda _:None)
            with patch('android_backend.discover_java_homes',return_value=homes):
                env=runner.command_environment(['/sdk/cmdline-tools/latest/bin/avdmanager','list','device'])
            self.assertEqual(env['JAVA_HOME'],homes[1])
            self.assertEqual(runner.tools['java'],homes[0])
