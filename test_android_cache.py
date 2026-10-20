import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from android_backend import AndroidRunner
from backend import BuildError


class AndroidCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        (self.root/'assets').mkdir();(self.root/'assets/game.ts').write_text('initial')
        (self.root/'package.json').write_text('{"creator":{"version":"3.7.3"}}')
        self.proj=self.root/'build/android/proj';self.proj.mkdir(parents=True)
        (self.proj/'gradlew').write_text('wrapper')
        self.apk=self.proj/'build/game/outputs/apk/debug/game-debug.apk'
        self.options={'buildPath':'project://build','outputName':'android','debug':True,'scenes':[{'uuid':'a'}],'startScene':'a','packages':{'android':{'packageName':'com.test.app','appABIs':['arm64-v8a']}}}
        self.calls=[];self.lines=[];self.fail_gradle=False
        self.runner=AndroidRunner({'creator':'/creator','sdk':'/sdk','ndk':'/ndk','java':'/jdk'},self.lines.append,lambda _:None)
        self.check=patch('android_backend.check_android_tools',return_value=[]);self.check.start();self.addCleanup(self.check.stop)
        for name,value in [('validate_gradle_java',None),('apk_metadata',{'package':'com.test.app'})]:
            p=patch.object(self.runner,name,return_value=value);p.start();self.addCleanup(p.stop)
        p=patch.object(self.runner,'run',side_effect=self.fake_run);p.start();self.addCleanup(p.stop)

    def fake_run(self,args,**kwargs):
        self.calls.append([str(a) for a in args])
        if args[0]!='/creator':
            if self.fail_gradle: raise BuildError('Gradle failed')
            self.apk.parent.mkdir(parents=True,exist_ok=True);self.apk.write_bytes(b'apk')
        return ''

    def build(self,**kwargs):
        return self.runner.build_apk(self.root,self.options,**kwargs)

    def exports(self):
        return [args for args in self.calls if args[0]=='/creator']

    def test_second_unchanged_build_skips_cocos_and_uses_gradle_cache(self):
        self.build();self.build()
        self.assertEqual(len(self.exports()),1)
        gradle=[args for args in self.calls if 'assembleDebug' in args]
        self.assertEqual(len(gradle),2)
        self.assertIn('--daemon',gradle[1]);self.assertIn('--build-cache',gradle[1])
        self.assertTrue(any('Cache Cocos: HIT' in line for line in self.lines))
        self.assertTrue(any('Thời gian' in line for line in self.lines))

    def test_changed_assets_and_config_force_export(self):
        self.build()
        (self.root/'assets/game.ts').write_text('changed asset')
        self.build()
        self.options['packages']['android']['apiLevel']=34
        self.build()
        self.assertEqual(len(self.exports()),3)

    def test_project_native_and_extension_profile_changes_invalidate_export(self):
        self.build()
        for relative in ('native/engine/android/custom.cpp','profiles/v2/packages/custom.json','build-templates/android/custom.txt'):
            path=self.root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('{}' if path.suffix=='.json' else 'changed')
            self.build()
        self.assertEqual(len(self.exports()),4)

    def test_failed_gradle_retry_reuses_successful_cocos_export(self):
        self.fail_gradle=True
        with self.assertRaises(BuildError):self.build()
        self.fail_gradle=False;self.build()
        self.assertEqual(len(self.exports()),1)

    def test_force_export_and_missing_wrapper_ignore_cached_marker(self):
        self.build();self.build(force_export=True)
        self.assertEqual(len(self.exports()),2)
        (self.proj/'gradlew').unlink()
        with self.assertRaises(BuildError):self.build()
        self.assertEqual(len(self.exports()),3)

    def test_reused_gradle_inputs_are_not_rewritten(self):
        self.build()
        local=self.proj/'local.properties'
        scripts=[Path(args[args.index('--init-script')+1]) for args in self.calls if '--init-script' in args]
        self.assertTrue(scripts[0].is_file())
        old=(local.stat().st_mtime_ns,scripts[0].stat().st_mtime_ns)
        self.build()
        self.assertEqual(old,(local.stat().st_mtime_ns,scripts[0].stat().st_mtime_ns))

    def test_invalid_export_cache_marker_causes_export_instead_of_failing_build(self):
        self.build()
        (self.root/'build/android/.android-builder-export.json').write_text('broken json')
        self.build()
        self.assertEqual(len(self.exports()),2)

    def test_gradle_only_version_override_reuses_cocos_export(self):
        self.build()
        self.options['builderAndroid']={'versionCode':42,'versionName':'1.2'}
        self.build()
        self.assertEqual(len(self.exports()),1)
        script=self.root/'build/android/.android-builder-gradle.gradle'
        self.assertIn('versionCode = 42',script.read_text())

    def test_edit_during_export_is_not_recorded_as_current_output(self):
        original=self.fake_run
        def edit(args,**kwargs):
            result=original(args,**kwargs)
            if args[0]=='/creator':(self.root/'assets/game.ts').write_text('edited while exporting')
            return result
        with patch.object(self.runner,'run',side_effect=edit):self.build()
        self.build()
        self.assertEqual(len(self.exports()),2)

    def test_identical_settings_rewrite_does_not_invalidate_export(self):
        settings=self.root/'settings/v2/packages/project.json';settings.parent.mkdir(parents=True);settings.write_text('{}')
        original=self.fake_run
        def rewrite(args,**kwargs):
            result=original(args,**kwargs)
            if args[0]=='/creator':settings.write_text('{}')
            return result
        with patch.object(self.runner,'run',side_effect=rewrite):self.build()
        self.build()
        self.assertEqual(len(self.exports()),1)

    def test_creator_resources_and_engine_updates_invalidate_export(self):
        from android_backend import android_export_fingerprint
        creator=self.root/'Creator.app/Contents/MacOS/CocosCreator';creator.parent.mkdir(parents=True);creator.write_text('exe')
        resources=creator.parents[1]/'Resources';resources.mkdir()
        archive=resources/'app.asar';archive.write_text('old')
        engine=resources/'resources/3d/engine';engine.mkdir(parents=True)
        source=engine/'engine.ts';source.write_text('initial')
        first=android_export_fingerprint(self.root,self.options,str(creator))
        archive.write_text('new archive')
        second=android_export_fingerprint(self.root,self.options,str(creator))
        self.assertNotEqual(first,second)
        source.write_text('updated')
        self.assertNotEqual(second,android_export_fingerprint(self.root,self.options,str(creator)))

    def test_identical_generated_native_rewrite_does_not_invalidate_export(self):
        native=self.root/'native/engine/android/app/build.gradle';native.parent.mkdir(parents=True);native.write_text('same config')
        original=self.fake_run
        def rewrite(args,**kwargs):
            result=original(args,**kwargs)
            if args[0]=='/creator':native.write_text('same config')
            return result
        with patch.object(self.runner,'run',side_effect=rewrite):self.build()
        self.build()
        self.assertEqual(len(self.exports()),1)
