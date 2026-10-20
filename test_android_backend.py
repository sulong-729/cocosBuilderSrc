import json
import os
import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from android_backend import (inspect_android_project, discover_studios, parse_devices,
    make_android_config, android_environment, validate_android_options, AndroidRunner,
    select_apk, parse_badging, check_android_tools, strip_secrets)
from backend import BuildError, input_fingerprint


class AndroidTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir()
        (self.root / 'package.json').write_text(json.dumps({'creator': {'version': '3.7.3'}}))

    def test_android_only_task_merges_package_profile(self):
        profile = self.root / 'profiles/v2/packages'
        profile.mkdir(parents=True)
        (profile / 'builder.json').write_text(json.dumps({'BuildTaskManager': {'taskMap': {'same': {'options': {'platform': 'android', 'scenes': [{'uuid': 'a'}]}}}}}))
        (profile / 'android.json').write_text(json.dumps({'builder': {'options': {'android': {'packageName': 'com.test.app', 'custom': 8}}, 'taskOptionsMap': {'same': {'apiLevel': 33}}}}))
        result = inspect_android_project(self.root)
        self.assertEqual(result['configs'][0]['id'], 'same')
        self.assertEqual(result['configs'][0]['options']['packages']['android']['apiLevel'], 33)
        self.assertEqual(result['configs'][0]['options']['packages']['android']['custom'], 8)

    def test_project_without_android_task_still_loads(self):
        self.assertEqual(inspect_android_project(self.root)['configs'], [])

    def test_studio_renamed_bundles_and_duplicates(self):
        for name in ('Android Studio.app', 'Android Studio copy.app', 'Other.app'):
            contents = self.root / name / 'Contents'
            contents.mkdir(parents=True)
            (contents / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': 'com.google.android.studio' if name != 'Other.app' else 'other', 'CFBundleShortVersionString': '2025.2'}))
        result = discover_studios([self.root])
        self.assertEqual(len(result), 2)
        self.assertNotEqual(result[0]['path'], result[1]['path'])

    def test_adb_states_and_multiple_serials(self):
        result = parse_devices('List of devices attached\nemulator-5554 device product:sdk model:Pixel_8 device:emu\nABC unauthorized usb:1\nXYZ offline\n* daemon started successfully *\n')
        self.assertEqual([d['serial'] for d in result], ['emulator-5554', 'ABC', 'XYZ'])
        self.assertEqual(result[1]['state'], 'unauthorized')
        self.assertEqual(result[0]['kind'], 'emulator')

    def test_config_preserves_extensions_and_forces_apk(self):
        original = {'platform': 'ios', 'packages': {'android': {'appBundle': True, 'custom': 12}, 'extension': {'keep': 7}}}
        config = make_android_config(original, {'sdk': '/sdk', 'ndk': '/ndk'}, 'com.test.game')
        self.assertEqual(config['platform'], 'android')
        self.assertFalse(config['packages']['android']['appBundle'])
        self.assertEqual(config['packages']['extension'], {'keep': 7})
        self.assertEqual(config['packages']['android']['sdkPath'], '/sdk')
        self.assertEqual(original['platform'], 'ios')

    def test_selected_java_environment_does_not_mutate_global(self):
        before = dict(os.environ)
        env = android_environment({'sdk': '/sdk', 'ndk': '/ndk', 'java': '/jdk'})
        self.assertEqual(env['JAVA_HOME'], '/jdk')
        self.assertEqual(env['ANDROID_HOME'], '/sdk')
        self.assertEqual(dict(os.environ), before)

    def test_invalid_scene_abi_and_package(self):
        options = {'scenes': [{'uuid': 'a'}], 'startScene': 'a', 'packages': {'android': {'appABIs': ['arm64-v8a'], 'packageName': 'com.test.app'}}}
        self.assertEqual(validate_android_options(options), '')
        options['packages']['android']['appABIs'] = []
        self.assertIn('ABI', validate_android_options(options))
        options['packages']['android']['appABIs'] = ['arm64-v8a']
        options['packages']['android']['packageName'] = 'bad;cmd'
        self.assertIn('Package', validate_android_options(options))

    def test_adb_requires_explicit_serial_and_checks_failure(self):
        (self.root / 'platform-tools').mkdir()
        (self.root / 'platform-tools/adb').touch()
        runner = AndroidRunner({'sdk': str(self.root)}, lambda _: None, lambda _: None)
        with patch.object(runner, 'run', return_value='Success') as run:
            runner.adb('ABC', ['install', '-r', '/tmp/game.apk'])
            self.assertEqual(run.call_args.args[0][1:3], ['-s', 'ABC'])
        with self.assertRaises(BuildError):
            runner.adb('', ['shell', 'echo', 'x'])

    def test_apk_selection_rejects_ambiguous_and_missing_outputs(self):
        folder = self.root / 'outputs/apk/debug'; folder.mkdir(parents=True)
        with self.assertRaises(BuildError): select_apk(self.root, 'debug')
        apk = folder / 'app-debug.apk'; apk.write_bytes(b'apk')
        self.assertEqual(select_apk(self.root, 'debug'), apk)
        (folder / 'split.apk').write_bytes(b'apk')
        with self.assertRaises(BuildError): select_apk(self.root, 'debug')

    def test_apk_badging_identity_and_abi(self):
        meta = parse_badging("package: name='com.test.app' versionCode='1' versionName='1.0'\nlaunchable-activity: name='com.cocos.game.AppActivity' label='' icon=''\nnative-code: 'arm64-v8a' 'armeabi-v7a'\nsdkVersion:'24'\n")
        self.assertEqual(meta['package'], 'com.test.app')
        self.assertIn('arm64-v8a', meta['abis'])
        self.assertEqual(meta['minSdk'], 24)

    def test_strip_secrets_preserves_other_extensions(self):
        value = strip_secrets({'packages': {'android': {'keystorePassword': 'secret', 'custom': 9}, 'native': {'xxteaKey': 'secret'}}})
        self.assertNotIn('secret', json.dumps(value))
        self.assertEqual(value['packages']['android']['custom'], 9)

    def test_cancelled_runner_starts_no_process(self):
        runner = AndroidRunner({}, lambda _: None, lambda _: None)
        runner.cancel()
        with patch('android_backend.subprocess.Popen') as process:
            with self.assertRaises(BuildError): runner.run(['/bin/echo', 'hello'])
            process.assert_not_called()

    def test_missing_tools_explained_individually(self):
        issues = check_android_tools({'sdk': str(self.root), 'java': '', 'ndk': '', 'creator': ''}, '3.7.3')
        text = '\n'.join(issues)
        for word in ('Cocos', 'JDK', 'SDK', 'NDK'):
            self.assertIn(word, text)


class PipelineTests(unittest.TestCase):
    def test_install_checks_abi_before_uninstall_and_targets_selected_device(self):
        runner = AndroidRunner({'sdk': '/sdk'}, lambda _: None, lambda _: None)
        meta = {'package': 'com.test.app', 'abis': ['arm64-v8a'], 'minSdk': 24}
        calls = []
        def adb(serial, args, **kw):
            calls.append((serial, args))
            if args == ['shell', 'getprop', 'ro.product.cpu.abilist']: return 'x86_64'
            return ''
        with patch.object(runner, 'apk_metadata', return_value=meta), patch.object(runner, 'scan', return_value=[{'serial': 'ABC', 'state': 'device'}]), patch.object(runner, 'adb', side_effect=adb):
            with self.assertRaisesRegex(BuildError, 'ABI'): runner.install_run('/test.apk', 'ABC', 'com.test.app', clean=True)
        self.assertFalse(any('uninstall' in args for _, args in calls))
        self.assertTrue(all(serial == 'ABC' for serial, _ in calls))

    def test_install_launch_checks_adb_semantic_errors(self):
        runner = AndroidRunner({'sdk': '/sdk'}, lambda _: None, lambda _: None)
        meta = {'package': 'com.test.app', 'abis': ['arm64-v8a'], 'minSdk': 24}
        def adb(serial, args, **kw):
            if 'ro.product.cpu.abilist' in args: return 'arm64-v8a'
            if 'ro.build.version.sdk' in args: return '33'
            if args[0] == 'install': return 'Success'
            if 'resolve-activity' in args: return 'com.test.app/com.cocos.game.AppActivity'
            if 'start' in args: return 'Error: activity does not exist'
            return ''
        with patch.object(runner, 'apk_metadata', return_value=meta), patch.object(runner, 'scan', return_value=[{'serial': 'ABC', 'state': 'device'}]), patch.object(runner, 'adb', side_effect=adb):
            with self.assertRaisesRegex(BuildError, 'launch'): runner.install_run('/test.apk', 'ABC', 'com.test.app')

    def test_runner_stream_failure_and_timeout(self):
        lines = []
        runner = AndroidRunner({}, lines.append, lambda _: None)
        self.assertEqual(runner.run(['/bin/echo', 'hello']), 'hello')
        with self.assertRaises(BuildError): runner.run(['/usr/bin/false'])
        with self.assertRaisesRegex(BuildError, 'thời gian'): runner.run(['/bin/sleep', '5'], timeout=.1)
        self.assertIsNone(runner.process)

    def test_gradle_java_old_wrapper_rejects_new_studio_java(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); wrapper = root/'gradle/wrapper'; wrapper.mkdir(parents=True)
            (wrapper/'gradle-wrapper.properties').write_text('distributionUrl=https://services.gradle.org/distributions/gradle-6.5.1-all.zip')
            java = root/'jdk'; java.mkdir(); (java/'release').write_text('JAVA_VERSION="21.0.1"')
            runner = AndroidRunner({'java':str(java)}, lambda _:None, lambda _:None)
            with self.assertRaisesRegex(BuildError, 'JDK 21'): runner.validate_gradle_java(root)
            (java/'release').write_text('JAVA_VERSION="11.0.1"')
            runner.validate_gradle_java(root)

    def test_failed_build_invalidates_existing_apk_record_and_temp_config_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'assets').mkdir()
            (root/'package.json').write_text('{"creator":{"version":"3.7.3"}}')
            output = root/'build/android'; output.mkdir(parents=True)
            marker = output/'.android-builder-apk.json'; marker.write_text('{"apk":"stale.apk"}')
            opts = {'debug':True, 'buildPath':'project://build','outputName':'android','scenes':[{'uuid':'a'}], 'startScene':'a','packages':{'android':{'packageName':'com.test.app','appABIs':['arm64-v8a']}}}
            runner = AndroidRunner({'sdk':'/sdk','ndk':'/ndk','creator':'/creator'}, lambda _:None, lambda _:None)
            config_paths=[]
            def fail(args, **kw):
                config_paths.append(Path(args[-1].split('=',1)[1])); raise BuildError('export failed')
            with patch('android_backend.check_android_tools',return_value=[]), patch.object(runner,'run',side_effect=fail):
                with self.assertRaises(BuildError): runner.build_apk(root, opts)
            self.assertFalse(marker.exists())
            self.assertTrue(config_paths)
            self.assertFalse(config_paths[0].exists())

    def test_existing_apk_rejects_tampering(self):
        from android_backend import apk_hash
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve(); output=root/'build/android'; output.mkdir(parents=True)
            apk=output/'test.apk'; apk.write_bytes(b'first')
            opts={'buildPath':'project://build','outputName':'android','packages':{'android':{'packageName':'com.test.app'}}}
            tools={'sdk':'/sdk','ndk':'/ndk'}
            cfg=make_android_config(opts,tools,'com.test.app')
            (output/'.android-builder-apk.json').write_text(json.dumps({'apk':str(apk),'sha256':apk_hash(apk),'config':strip_secrets(cfg),'fingerprint':input_fingerprint(root,cfg)}))
            runner=AndroidRunner(tools,lambda _:None,lambda _:None)
            self.assertEqual(runner.existing_apk(root,opts),str(apk))
            apk.write_bytes(b'changed')
            with self.assertRaises(BuildError):runner.existing_apk(root,opts)

class NativeConfigTests(unittest.TestCase):
    def test_runtime_overrides_reject_invalid_version_values(self):
        opts = {'scenes':[{'uuid':'a'}], 'startScene':'a', 'packages':{'android':{'packageName':'com.test.app','appABIs':['arm64-v8a']}}, 'builderAndroid':{'versionCode':'oops'}}
        self.assertIn('versionCode', validate_android_options(opts))

    def test_native_only_rejects_changed_sources_before_gradle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve(); (root/'assets').mkdir()
            (root/'package.json').write_text('{"creator":{"version":"3.7.3"}}')
            output=root/'build/android'; output.mkdir(parents=True)
            opts={'buildPath':'project://build','outputName':'android','scenes':[{'uuid':'a'}], 'startScene':'a','packages':{'android':{'packageName':'com.test.app','appABIs':['arm64-v8a']}}}
            (output/'.android-builder-apk.json').write_text(json.dumps({'fingerprint':'outdated'}))
            runner=AndroidRunner({'creator':'/creator','sdk':'/sdk','ndk':'/ndk'},lambda _:None,lambda _:None)
            with patch('android_backend.check_android_tools',return_value=[]),patch.object(runner,'run') as run:
                with self.assertRaisesRegex(BuildError, 'export'):runner.build_apk(root,opts,True)
                run.assert_not_called()

class FreshnessTests(unittest.TestCase):
    def test_recorded_apk_rejects_source_changes(self):
        from android_backend import apk_hash
        from backend import input_fingerprint
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve(); (root/'assets').mkdir()
            source=root/'assets/game.ts';source.write_text('old')
            output=root/'build/android';output.mkdir(parents=True)
            apk=output/'app.apk';apk.write_bytes(b'apk')
            opts={'buildPath':'project://build','outputName':'android','packages':{'android':{'packageName':'com.test.app'}}}
            tools={'sdk':'/sdk','ndk':'/ndk'};config=make_android_config(opts,tools,'com.test.app')
            (output/'.android-builder-apk.json').write_text(json.dumps({'apk':str(apk),'sha256':apk_hash(apk),'config':strip_secrets(config),'fingerprint':input_fingerprint(root,config)}))
            runner=AndroidRunner(tools,lambda _:None,lambda _:None)
            source.write_text('new code')
            with self.assertRaisesRegex(BuildError,'Asset/script'):runner.existing_apk(root,opts)

    def test_log_colors_for_exception_names_and_logcat_priority(self):
        from log_style import LogHighlighter
        for line in ('TypeError: bad data', 'ReferenceError: missing', 'java.lang.NullPointerException'):
            self.assertEqual(LogHighlighter.level(line), 'error')
        self.assertEqual(LogHighlighter.level('10-20 00:00:01.001 123 456 W Cocos: deprecated'), 'warning')
        self.assertEqual(LogHighlighter.level('10-20 00:00:01.001 123 456 I Cocos: warning count 0'), 'normal')


class WorkflowTests(unittest.TestCase):
    def test_successful_build_records_apk_and_applies_early_gradle_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve(); (root/'assets').mkdir()
            (root/'package.json').write_text('{"creator":{"version":"3.7.3"}}')
            output=root/'build/android';proj=output/'proj';proj.mkdir(parents=True)
            (proj/'gradlew').touch()
            apk=proj/'build/game/outputs/apk/debug/game-debug.apk'
            options={'buildPath':'project://build','outputName':'android','debug':True,'scenes':[{'uuid':'a'}],'startScene':'a','packages':{'android':{'packageName':'com.test.app','appABIs':['arm64-v8a']}},'builderAndroid':{'versionCode':'42','versionName':"release.${literal}"}}
            runner=AndroidRunner({'creator':'/creator','sdk':'/test/sdk','ndk':'/ndk','java':'/jdk'},lambda _:None,lambda _:None)
            scripts=[];creator_configs=[]
            def run(args,**kwargs):
                if args[0]=='/creator':
                    config=Path(args[-1].split('=',1)[1]);creator_configs.append(config)
                    self.assertNotIn('builderAndroid',json.loads(config.read_text()))
                else:
                    script=Path(args[args.index('--init-script')+1]);scripts.append(script.read_text())
                    self.assertIn('assembleDebug',args)
                    apk.parent.mkdir(parents=True);apk.write_bytes(b'apk')
                return ''
            with patch('android_backend.check_android_tools',return_value=[]),patch.object(runner,'validate_gradle_java'),patch.object(runner,'run',side_effect=run),patch.object(runner,'apk_metadata',return_value={'package':'com.test.app'}):
                self.assertEqual(runner.build_apk(root,options),str(apk))
            record=json.loads((output/'.android-builder-apk.json').read_text())
            self.assertEqual(record['package'],'com.test.app')
            self.assertIn('gradle.beforeProject',scripts[0])
            self.assertNotIn('projectsEvaluated',scripts[0])
            self.assertIn("versionName = 'release.${literal}'",scripts[0])
            self.assertTrue(all(not p.exists() for p in creator_configs))
            self.assertIn('sdk.dir=/test/sdk',(proj/'local.properties').read_text())
            self.assertEqual(runner.existing_apk(root,options),str(apk))

    def test_missing_avdmanager_has_setup_instructions(self):
        runner=AndroidRunner({'sdk':'/missing-sdk'},lambda _:None,lambda _:None)
        with self.assertRaisesRegex(BuildError,'SDK Manager'):
            runner.avd_catalog()

    def test_delete_running_avd_refuses_without_delete_command(self):
        runner=AndroidRunner({'sdk':'/sdk'},lambda _:None,lambda _:None)
        with patch.object(runner,'scan',return_value=[{'kind':'emulator','state':'device','serial':'emulator-5554'}]),patch.object(runner,'adb',return_value='Pixel_3_XL\nOK'),patch.object(runner,'run') as run:
            with self.assertRaisesRegex(BuildError,'Tắt AVD'):runner.delete_avd('Pixel_3_XL')
            run.assert_not_called()


class LogcatDeviceTimeTests(unittest.TestCase):
    def test_remote_date_format_is_one_shell_argument(self):
        import shlex
        runner=AndroidRunner({},lambda _:None,lambda _:None)
        def adb(serial,args,**kwargs):
            self.assertEqual(serial,'emulator-5554')
            remote=shlex.split(' '.join(args[1:]))
            self.assertEqual(remote,['date','+%m-%d %H:%M:%S.000'])
            return '10-20 08:10:00.000'
        with patch.object(runner,'adb',side_effect=adb):
            self.assertEqual(runner.device_time('emulator-5554'),'10-20 08:10:00.000')


class DependencyReportTests(unittest.TestCase):
    def test_avd_dependencies_report_package_and_install_location(self):
        with tempfile.TemporaryDirectory() as temp:
            issues=check_android_tools({'sdk':temp},'',build=False,include_avd=True)
        report='\n'.join(issues)
        for name in ('adb','emulator','avdmanager','sdkmanager'):
            self.assertIn(name,report)
        self.assertIn('Android SDK Command-line Tools (latest)',report)
        self.assertIn('SDK Manager → SDK Tools',report)
        self.assertNotIn('/missing/',report)

    def test_missing_command_raises_structured_dependency_notification(self):
        from android_backend import AndroidDependencyError
        runner=AndroidRunner({'sdk':'/missing-sdk'},lambda _:None,lambda _:None)
        with self.assertRaises(AndroidDependencyError) as raised:
            runner.avd_catalog()
        self.assertIn('avdmanager',raised.exception.issues[0])


if __name__ == '__main__':
    unittest.main()
