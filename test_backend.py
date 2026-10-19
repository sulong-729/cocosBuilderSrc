import json
import plistlib
from pathlib import Path
import signal
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from backend import (Builder, BuildError, export_folder, input_fingerprint, inspect_project,
                     make_config, scan_devices, scan_simulators, check_dependencies, simulator_catalog, create_simulator, delete_simulator, set_simulator_power)


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cocos project spaces ")
        self.root = Path(self.temp.name)
        (self.root / "assets").mkdir()
        (self.root / "package.json").write_text(json.dumps({"creator": {"version": "3.7.3"}}))
        self.profiles = self.root / "profiles/v2/packages"
        self.profiles.mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, value):
        (self.profiles / (name + ".json")).write_text(json.dumps(value))

    def test_task_overrides_common_and_preserves_extensions(self):
        options = {"platform": "ios", "name": "Example", "scenes": [{"uuid": "first"}],
                   "packages": {"ios": {"packageName": "com.task.override"}}}
        self.write("builder", {"BuildTaskManager": {"taskMap": {"a": {"options": options}}}})
        self.write("ios", {"builder": {"options": {"ios": {"packageName": "com.default"}},
                                       "taskOptionsMap": {"a": {"developerTeam": "ABCDEFGHIJ"}}}})
        self.write("native", {"builder": {"options": {"ios": {"encrypted": False}},
                                          "taskOptionsMap": {"a": {"encrypted": True}}}})
        result = inspect_project(str(self.root))["configs"][0]["options"]
        self.assertEqual(result["packages"]["ios"]["packageName"], "com.task.override")
        self.assertEqual(result["packages"]["ios"]["developerTeam"], "ABCDEFGHIJ")
        self.assertTrue(result["packages"]["native"]["encrypted"])
        self.assertEqual(result["scenes"], options["scenes"])

    def test_missing_configuration_is_actionable(self):
        with self.assertRaisesRegex(BuildError, "Chưa có task iOS"):
            inspect_project(str(self.root))

    def test_fallback_and_config_immutability(self):
        (self.root / "buildCmd").mkdir()
        options = {"platform": "ios", "scenes": ["a"], "packages": {"ios": {"orientation": {"portrait": True}}}}
        (self.root / "buildCmd/buildConfig_ios.json").write_text(json.dumps(options))
        result = inspect_project(str(self.root))["configs"][0]["options"]
        generated = make_config(result, "ABCDEFGHIJ", "com.game.debug", True)
        self.assertEqual(result, options)
        self.assertEqual(generated["packages"]["ios"]["osTarget"], {"iphoneos": False, "simulator": True})
        self.assertTrue(generated["packages"]["ios"]["orientation"]["portrait"])
        self.assertIn("/simulator", generated["buildPath"])
        self.assertIn("/device", make_config(result, "ABCDEFGHIJ", "com.game.debug")["buildPath"])

    def test_reuse_existing_output_preserves_cocos_task_directory(self):
        options = {"buildPath": "project://build", "outputName": "ios-custom", "packages": {}}
        config = make_config(options, "ABCDEFGHIJ", "com.game.debug", True, True)
        self.assertEqual(export_folder(self.root, config), (self.root / "build/ios-custom").resolve())
        self.assertEqual(options["packages"], {})

    def test_incremental_check_detects_asset_change_but_ignores_build_logs(self):
        asset = self.root / "assets/code.ts"
        asset.write_text("original")
        original = input_fingerprint(self.root, {})
        (self.root / "build").mkdir()
        (self.root / "build/log.txt").write_text("new build output")
        self.assertEqual(original, input_fingerprint(self.root, {}))
        asset.write_text("updated content")
        self.assertNotEqual(original, input_fingerprint(self.root, {}))


class ProcessTests(unittest.TestCase):
    def test_repair_replaces_old_device_archive_and_quotes_spaced_paths(self):
        with tempfile.TemporaryDirectory(prefix="cocos space ") as folder:
            root = Path(folder)
            creator = root / "Creator.app/Contents/MacOS/CocosCreator"
            native = creator.parent.parent / "Resources/resources/3d/engine/native"
            (native / "external/ios/libs").mkdir(parents=True)
            (native / "external/ios/libs/libwebp.a").touch()
            project = root / "Project.xcodeproj"
            project.mkdir()
            pbx = project / "project.pbxproj"
            pbx.write_text('OTHER_LDFLAGS = ("/old/device-only/libwebp.a");')
            output = root / "output"
            output.mkdir()
            builder = Builder(lambda _: None, lambda _: None)
            with patch.object(builder, "run") as run:
                builder.compatibility(project, creator, output, "x86_64")
            self.assertIn(json.dumps(str(output / "compat-libs/libwebp.a")), pbx.read_text())
            self.assertNotIn("/old/device-only", pbx.read_text())
            self.assertIn("x86_64", list(map(str, run.call_args_list[0].args[0])))

    def test_arguments_are_not_interpreted_by_a_shell(self):
        logs = []
        builder = Builder(logs.append, lambda _: None)
        value = "$(touch /tmp/should-never-exist-9723); spaces `false`"
        builder.run([sys.executable, "-c", "import sys;print(sys.argv[1])", value], Path.cwd())
        self.assertIn(value, logs)

    def test_nonzero_exit_propagates(self):
        builder = Builder(lambda _: None, lambda _: None)
        with self.assertRaisesRegex(BuildError, "mã 7"):
            builder.run([sys.executable, "-c", "raise SystemExit(7)"], Path.cwd())

    def test_failed_build_streams_stderr_and_stops_before_next_step(self):
        logs = []
        builder = Builder(logs.append, lambda _: None)
        with tempfile.TemporaryDirectory() as folder:
            marker = Path(folder) / "installed"
            with self.assertRaisesRegex(BuildError, "mã 65"):
                builder.run([sys.executable, "-c", "import sys; print('compile error: bad symbol', file=sys.stderr); sys.exit(65)"], Path(folder))
                marker.touch()
            self.assertFalse(marker.exists())
        self.assertTrue(any("compile error: bad symbol" in line for line in logs))
        self.assertIsNone(builder.process)

    def test_build_timeout_reports_build_command_not_usb(self):
        builder = Builder(lambda _: None, lambda _: None)
        with self.assertRaisesRegex(BuildError, "timeout.*0.1"):
            builder.run([sys.executable, "-c", "import time;time.sleep(30)"], Path.cwd(), timeout=0.1)
        self.assertIsNone(builder.process)

    def test_cocos_build_success_exit_36_is_explicitly_allowed(self):
        builder = Builder(lambda _: None, lambda _: None)
        builder.run([sys.executable, "-c", "raise SystemExit(36)"], Path.cwd(), success_codes=(0, 36))
        with self.assertRaisesRegex(BuildError, "mã 36"):
            builder.run([sys.executable, "-c", "raise SystemExit(36)"], Path.cwd())

    def test_cancel_terminates_process_and_preserves_cancel_state(self):
        builder = Builder(lambda _: None, lambda _: None)
        errors = []
        def run():
            try:
                builder.run([sys.executable, "-c", "import time;time.sleep(60)"], Path.cwd())
            except BuildError as error:
                errors.append(str(error))
        thread = threading.Thread(target=run)
        thread.start()
        deadline = time.monotonic() + 5
        while builder.process is None and time.monotonic() < deadline:
            time.sleep(.01)
        builder.cancel()
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertIn("Đã dừng", errors[0])
        with self.assertRaisesRegex(BuildError, "Đã dừng"):
            builder.run([sys.executable, "-c", "print('must not execute')"], Path.cwd())


class DiscoveryTests(unittest.TestCase):
    def test_physical_device_json_uses_udid_for_xcode(self):
        def fake_capture(args, **kwargs):
            output = Path(args[args.index("--json-output") + 1])
            output.write_text(json.dumps({"result": {"devices": [{"identifier": "core-id",
                "hardwareProperties": {"platform": "iOS", "reality": "physical", "udid": "usb-id"},
                "deviceProperties": {"name": "iPhone", "developerModeStatus": "enabled"},
                "connectionProperties": {"transportType": "wired"}}]}}))
            return ""
        with patch("backend.capture", fake_capture):
            devices = scan_devices()
        self.assertEqual(devices[0]["udid"], "usb-id")
        self.assertEqual(devices[0]["id"], "core-id")

    def test_simulator_runtime_architecture_is_preserved(self):
        def fake_capture(args):
            if "runtimes" in args:
                return json.dumps({"runtimes": [{"identifier": "ios", "name": "iOS 26.5", "supportedArchitectures": ["arm64"]}]})
            return json.dumps({"devices": {"ios": [{"udid": "sim", "name": "iPhone", "isAvailable": True}]}})
        with patch("backend.capture", fake_capture):
            devices = scan_simulators()
        self.assertEqual(devices[0]["architectures"], ["arm64"])
        self.assertEqual(devices[0]["kind"], "simulator")


class BuildFlowTests(unittest.TestCase):
    def exercise(self, simulator, build_only=False):
        with tempfile.TemporaryDirectory(prefix="cocos flow spaces ") as temp:
            root = Path(temp)
            creator = root / "Cocos Creator"
            creator.touch()
            options = {"debug": True, "platform": "ios", "packages": {"ios": {}}}
            output = root / "build/ios-builder" / ("simulator" if simulator else "device")
            proj = output / "ios/proj"
            info_file = proj / "CMakeFiles/Example-mobile.dir/Info.plist"
            commands = []
            builder = Builder(lambda _: None, lambda _: None)
            def run(args, cwd, timeout=None, success_codes=(0,)):
                args = list(map(str, args))
                commands.append(args)
                if args[0] == str(creator):
                    self.assertEqual(timeout, 1800)
                    xcode = proj / "Example.xcodeproj"
                    schemes = xcode / "xcshareddata/xcschemes"
                    schemes.mkdir(parents=True)
                    (schemes / "Example-mobile.xcscheme").touch()
                    info_file.parent.mkdir(parents=True)
                    info_file.write_bytes(plistlib.dumps({"CFBundleIdentifier": "com.old.literal"}))
                    (xcode / "project.pbxproj").write_text(f'INFOPLIST_FILE = "{info_file}";')
                elif args[0] == "/usr/bin/xcodebuild":
                    self.assertEqual(timeout, 1800)
                    self.assertEqual(plistlib.loads(info_file.read_bytes())["CFBundleIdentifier"], "com.new.debug")
                    app = output / "artifacts/Example-mobile.app"
                    app.mkdir(parents=True, exist_ok=True)
                    (app / "Info.plist").write_bytes(info_file.read_bytes())
                elif "--json-output" in args:
                    Path(args[args.index("--json-output") + 1]).write_text(json.dumps({"result": {"process": {"processIdentifier": 42}}}))
            def capture(args, **kwargs):
                if "launchctl" in args:
                    return "PID\tStatus\tLabel\n"
                if "listapps" in args:
                    return "{}"
                if "devicectl" in args and "apps" in args:
                    Path(args[args.index("--json-output") + 1]).write_text(json.dumps({"result": {"apps": []}}))
                    return ""
                if "simctl" in args and "devices" in args:
                    return json.dumps({"devices": {"ios": [{"udid": "core-or-sim-id", "state": "Booted"}]}})
                if "-showBuildSettings" in args:
                    return json.dumps([{"target": "Example-mobile", "buildSettings": {
                        "TARGET_BUILD_DIR": str(output / "artifacts"), "FULL_PRODUCT_NAME": "Example-mobile.app"}}])
                return "Xcode"
            device = {"id": "core-or-sim-id", "udid": "physical-udid", "name": "Test iPhone",
                      "kind": "simulator" if simulator else "device", "state": "Shutdown",
                      "architectures": ["x86_64", "arm64"]}
            with patch("backend.inspect_project", return_value={"version": "3.7.3"}), \
                 patch("backend.capture", side_effect=capture), \
                 patch.object(builder, "compatibility"), patch.object(builder, "run", side_effect=run):
                app = builder.build(str(root), options, str(creator), "" if simulator else "ABCDEFGHIJ",
                                    "com.new.debug", None if build_only else device, console=False,
                                    build_only=build_only, target_kind="simulator" if simulator else "device")
                first_commands = list(commands)
                commands.clear()
                builder.build(str(root), options, str(creator), "" if simulator else "ABCDEFGHIJ",
                              "com.new.debug", None if build_only else device, console=False,
                              build_only=build_only, target_kind="simulator" if simulator else "device")
                self.assertFalse(any(c[0] == str(creator) for c in commands), "Unchanged project must skip Cocos CLI")
                commands[:] = first_commands
            self.assertTrue(Path(app).is_dir())
            build = next(c for c in commands if c[0] == "/usr/bin/xcodebuild")
            if build_only:
                self.assertFalse(any("install" in c or "launch" in c or "boot" in c for c in commands))
                self.assertIn("generic/platform=iOS Simulator" if simulator else "generic/platform=iOS", build)
                self.assertTrue((output / "last-built.json").is_file())
                return
            if simulator:
                self.assertIn("CODE_SIGNING_ALLOWED=NO", build)
                self.assertIn("ARCHS=x86_64", build)
                self.assertTrue(any("install" in c and "simctl" in c for c in commands))
                self.assertTrue(any("--arch=x86_64" in c for c in commands))
                self.assertFalse(any("boot" in c for c in commands))
            else:
                self.assertIn("DEVELOPMENT_TEAM=ABCDEFGHIJ", build)
                self.assertIn("id=physical-udid", build)
                self.assertTrue(any("install" in c and "devicectl" in c for c in commands))

    def test_build_only_simulator_without_device(self):
        self.exercise(True, build_only=True)

    def test_build_only_physical_without_device(self):
        self.exercise(False, build_only=True)

    def test_complete_device_pipeline(self):
        self.exercise(False)

    def test_complete_simulator_pipeline(self):
        self.exercise(True)


if __name__ == "__main__":
    unittest.main()


class DependencyTests(unittest.TestCase):
    def test_missing_creator_reports_exact_version(self):
        with patch("backend.Path.is_file", return_value=True), patch("backend.os.access", return_value=False), patch("backend.capture", return_value="/Applications/Xcode.app/Contents/Developer"):
            issues = check_dependencies("3.7.3", "/missing/CocosCreator")
        self.assertEqual([i["code"] for i in issues], ["cocos"])
        self.assertIn("3.7.3", issues[0]["message"])
        self.assertIn("Dashboard", issues[0]["message"])

    def test_command_line_tools_is_not_full_xcode(self):
        with patch("backend.Path.is_file", return_value=True), patch("backend.os.access", return_value=True), patch("backend.Path.glob", return_value=[]), patch("backend.capture", return_value="/Library/Developer/CommandLineTools"):
            issues = check_dependencies("3.7.3", "/creator")
        self.assertEqual(issues[0]["code"], "xcode")
        self.assertIn("Chưa tìm thấy Xcode", issues[0]["message"])

    def test_installed_xcode_not_selected(self):
        with patch("backend.Path.is_file", return_value=True), patch("backend.os.access", return_value=True), patch("backend.Path.glob", return_value=[Path("/Applications/Xcode.app")]), patch("backend.capture", return_value="/Library/Developer/CommandLineTools"):
            issues = check_dependencies("3.7.3", "/creator")
        self.assertIn("chưa được chọn", issues[0]["message"])

    def test_xcode_setup_error_is_actionable(self):
        with patch("backend.Path.is_file", return_value=True), patch("backend.os.access", return_value=True), patch("backend.capture", side_effect=["/Applications/Xcode.app/Contents/Developer", BuildError("license required")]):
            issues = check_dependencies("3.7.3", "/creator")
        self.assertIn("license", issues[0]["message"])

    def test_ready_tools_have_no_warnings(self):
        with patch("backend.Path.is_file", return_value=True), patch("backend.os.access", return_value=True), patch("backend.capture", return_value="/Applications/Xcode.app/Contents/Developer"):
            self.assertEqual(check_dependencies("3.7.3", "/creator"), [])


class SimulatorManagementTests(unittest.TestCase):
    def test_catalog_filters_arch_and_models(self):
        runtimes = {"runtimes": [
            {"name": "iOS 26.5", "version": "26.5", "identifier": "universal", "isAvailable": True,
             "supportedArchitectures": ["arm64", "x86_64"], "supportedDeviceTypes": [
                 {"name": "iPhone 14", "identifier": "phone"}, {"name": "iPad", "identifier": "pad"}]},
            {"name": "iOS 26.0", "identifier": "arm", "isAvailable": True, "supportedArchitectures": ["arm64"]},
            {"name": "iOS 25", "identifier": "missing", "isAvailable": False}]}
        with patch("backend.capture", side_effect=[json.dumps(runtimes), '{"devicetypes": []}']):
            catalog = simulator_catalog("3.7.3")
        self.assertEqual(catalog, [{"id": "universal", "name": "iOS 26.5", "types": [{"id": "phone", "name": "iPhone 14"}]}])

    def test_create_uses_validated_ids_and_literal_name(self):
        catalog = [{"id": "runtime", "types": [{"id": "phone"}]}]
        with patch("backend.simulator_catalog", return_value=catalog), patch("backend.capture", return_value="new-id\n") as run:
            self.assertEqual(create_simulator("Test $(literal)", "phone", "runtime", "3.7.3"), "new-id")
            self.assertEqual(run.call_args.args[0], ["/usr/bin/xcrun", "simctl", "create", "Test $(literal)", "phone", "runtime"])
            with self.assertRaises(BuildError):
                create_simulator("Test", "unknown", "runtime", "3.7.3")

    def test_delete_shuts_down_only_selected_device(self):
        uid = "11111111-2222-3333-4444-555555555555"
        with patch("backend.scan_simulators", return_value=[{"id": uid, "state": "Booted"}]), patch("backend.require_idle_simulator"), patch("backend.capture") as run:
            delete_simulator(uid)
            self.assertEqual([c.args[0] for c in run.call_args_list], [
                ["/usr/bin/xcrun", "simctl", "shutdown", uid], ["/usr/bin/xcrun", "simctl", "delete", uid]])
            with self.assertRaises(BuildError):
                delete_simulator("all")
            self.assertEqual(run.call_count, 2)


class SimulatorPowerTests(unittest.TestCase):
    uid = "11111111-2222-3333-4444-555555555555"

    def test_open_shutdown_device_boots_and_opens_viewer(self):
        with patch("backend.scan_simulators", return_value=[{"id": self.uid, "state": "Shutdown"}]), patch("backend.capture") as run:
            self.assertEqual(set_simulator_power(self.uid, True), self.uid)
        self.assertEqual(run.call_args_list[0].args[0][2], "boot")
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[-1].args[0][-1], self.uid)

    def test_open_booted_device_does_not_boot_twice(self):
        with patch("backend.scan_simulators", return_value=[{"id": self.uid, "state": "Booted"}]), patch("backend.capture") as run:
            set_simulator_power(self.uid, True)
        self.assertEqual(len(run.call_args_list), 1)
        self.assertEqual(run.call_args_list[0].args[0][0], "/usr/bin/open")

    def test_shutdown_targets_selected_device_only(self):
        with patch("backend.scan_simulators", return_value=[{"id": self.uid, "state": "Booted"}]), patch("backend.require_idle_simulator"), patch("backend.capture") as run:
            set_simulator_power(self.uid, False)
        self.assertEqual(run.call_args.args[0], ["/usr/bin/xcrun", "simctl", "shutdown", self.uid])

    def test_shutdown_already_off_does_nothing(self):
        with patch("backend.scan_simulators", return_value=[{"id": self.uid, "state": "Shutdown"}]), patch("backend.capture") as run:
            set_simulator_power(self.uid, False)
            run.assert_not_called()


class RunExistingTests(unittest.TestCase):
    def test_run_reuses_app_without_calling_build(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            app = root / "build/ios/proj/Debug-iphonesimulator/Game.app"
            app.mkdir(parents=True)
            (app / "Game").write_bytes(b"test")
            info = {"CFBundleIdentifier": "com.test.game", "CFBundleExecutable": "Game",
                    "CFBundleSupportedPlatforms": ["iPhoneSimulator"]}
            (app / "Info.plist").write_bytes(plistlib.dumps(info))
            builder = Builder(lambda _: None, lambda _: None)
            device = {"id": "target", "kind": "simulator", "architectures": ["x86_64"]}
            options = {"debug": True, "buildPath": "project://build", "outputName": "ios"}
            with patch("backend.capture", return_value="x86_64") as capture, patch.object(builder, "deploy", return_value=str(app)) as deploy, patch.object(builder, "build") as build:
                self.assertEqual(builder.run_existing(folder, options, "com.test.game", device, False), str(app))
                build.assert_not_called()
                self.assertEqual(capture.call_args.args[0][1:3], ["lipo", "-archs"])
                self.assertEqual(deploy.call_args.args[3:], (device, "x86_64", False))
            with patch("backend.capture", return_value="arm64"), patch.object(builder, "deploy") as deploy:
                with self.assertRaisesRegex(BuildError, "kiến trúc"):
                    builder.run_existing(folder, options, "com.test.game", device, False)
                deploy.assert_not_called()
            with patch.object(builder, "deploy") as deploy:
                with self.assertRaisesRegex(BuildError, "Build & Run"):
                    builder.run_existing(folder, options, "com.other.bundle", device, False)
                deploy.assert_not_called()

    def test_missing_app_does_not_start_build(self):
        with tempfile.TemporaryDirectory() as folder:
            builder = Builder(lambda _: None, lambda _: None)
            with patch.object(builder, "build") as build:
                with self.assertRaisesRegex(BuildError, "Build & Run"):
                    builder.run_existing(folder, {}, "com.test.game", {"id": "target", "kind": "simulator"}, False)
                build.assert_not_called()


class AppSafetyTests(unittest.TestCase):
    def test_shutdown_and_delete_block_running_game(self):
        import backend
        uid = "11111111-2222-3333-4444-555555555555"
        for operation in (lambda: backend.set_simulator_power(uid, False), lambda: backend.delete_simulator(uid)):
            with patch("backend.scan_simulators", return_value=[{"id": uid, "state": "Booted"}]), patch("backend.capture", return_value="PID\tStatus\tLabel\n123\t0\tUIKitApplication:com.game.test[abc][rb-legacy]\n") as run:
                with self.assertRaisesRegex(BuildError, "đang chạy app"):
                    operation()
                self.assertTrue(all("shutdown" not in c.args[0] and "delete" not in c.args[0] for c in run.call_args_list))

    def test_unknown_activity_blocks_power_actions(self):
        import backend
        with patch("backend.capture", return_value="unexpected output"):
            with self.assertRaises(BuildError):
                backend.require_idle_simulator("test")

    def test_running_game_deploy_does_not_install_or_launch(self):
        import backend
        with tempfile.TemporaryDirectory() as folder:
            b = Builder(lambda _: None, lambda _: None)
            log = Path(folder) / "session.log"
            with log.open("w") as b.logfile, patch("backend.capture", return_value=json.dumps({"devices": {"ios": [{"udid": "sim", "state": "Booted"}]}})), patch("backend.simulator_app_processes", return_value=[{"bundle": "com.game.test", "pid": 123}]), patch.object(b, "run") as run:
                b.deploy(Path(folder), Path(folder), "com.game.test", {"id": "sim", "kind": "simulator"}, "x86_64", False)
                commands = [c.args[0] for c in run.call_args_list]
                self.assertFalse(any("install" in c or "launch" in c for c in commands))
                self.assertFalse(any("--console" in c or "--terminate-running-process" in c for c in commands))

    def test_stopping_file_monitor_never_signals_process(self):
        import backend
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "stdout.log";path.write_text("hello\n")
            b = Builder(lambda _: None, lambda _: None)
            b.cancelled.set()
            with patch("backend.os.killpg") as kill:
                b.monitor_files([path], {"id": "sim"}, "com.game.test")
                kill.assert_not_called()
            self.assertFalse(b.monitoring)


class ExplicitShutdownTests(unittest.TestCase):
    def test_explicit_shutdown_allows_active_game_on_selected_device(self):
        import backend
        uid = "11111111-2222-3333-4444-555555555555"
        with patch("backend.scan_simulators", return_value=[{"id": uid, "state": "Booted"}]), patch("backend.require_idle_simulator", side_effect=BuildError("game running")) as guard, patch("backend.capture") as run:
            backend.set_simulator_power(uid, False, allow_running=True)
            guard.assert_not_called()
            run.assert_called_once_with(["/usr/bin/xcrun", "simctl", "shutdown", uid], timeout=60)


class RestartSimulatorTests(unittest.TestCase):
    def test_restart_powers_only_selected_device_off_then_on(self):
        import backend
        uid = "11111111-2222-3333-4444-555555555555"
        with patch("backend.set_simulator_power", return_value=uid) as power:
            self.assertEqual(backend.restart_simulator(uid), uid)
            self.assertEqual([call.args for call in power.call_args_list], [(uid, False), (uid, True)])
            self.assertTrue(power.call_args_list[0].kwargs['allow_running'])
