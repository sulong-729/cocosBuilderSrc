"""Cocos Creator 3.x -> xcodebuild -> physical iPhone. No shell commands."""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import signal
import subprocess
import tempfile
import threading
import time


class BuildError(RuntimeError):
    pass


def read_json(path: Path, default=None):
    if not path.exists():
        return {} if default is None else default
    return json.loads(path.read_text())


def capture(args, timeout=30):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise BuildError(result.stderr.strip() or result.stdout.strip() or str(args[0]))
    return result.stdout


def installed_creator_versions(creator=""):
    apps = list(Path("/Applications/Cocos/Creator").glob("*/CocosCreator.app"))
    if creator:
        executable = Path(creator).expanduser()
        if executable.is_file() and len(executable.parents) >= 3:
            apps.append(executable.parents[2])
    versions = set()
    for app in apps:
        try:
            version = plistlib.loads((app / "Contents/Info.plist").read_bytes()).get("CFBundleShortVersionString", "")
            if version and (app / "Contents/MacOS/CocosCreator").is_file():
                versions.add(version)
        except (OSError, ValueError, plistlib.InvalidFileException):
            continue
    return sorted(versions, key=lambda value: tuple(int(n) for n in re.findall(r"\d+", value)), reverse=True)


def check_dependencies(version, creator):
    """Read-only checks; return actionable warnings without installing anything."""
    issues = []
    executable = Path(creator).expanduser()
    if not executable.is_file() or not os.access(executable, os.X_OK):
        issues.append({"code": "cocos", "message":
            f"Thiếu Cocos Creator {version}. Cài đúng phiên bản này bằng Cocos Dashboard; "
            "nếu đã cài ở thư mục khác, vào Cài đặt → Chọn Cocos… để chọn executable CocosCreator."})
    try:
        selected = capture(["/usr/bin/xcode-select", "-p"], timeout=12).strip()
    except (BuildError, OSError, subprocess.TimeoutExpired):
        selected = ""
    if not selected or "CommandLineTools" in selected or not (Path(selected) / "usr/bin/xcodebuild").is_file():
        installed = list(Path("/Applications").glob("Xcode*.app"))
        message = ("Xcode đã có trên máy nhưng chưa được chọn làm bộ công cụ build. "
                   "Mở Xcode → Settings → Locations → Command Line Tools và chọn bản Xcode cần dùng."
                   if installed else
                   "Chưa tìm thấy Xcode đầy đủ. Cài Xcode từ App Store, mở Xcode một lần để hoàn tất thiết lập. "
                   "Nếu cài ở vị trí khác, chọn bản đó tại Xcode → Settings → Locations → Command Line Tools.")
        issues.append({"code": "xcode", "message": message})
    else:
        try:
            capture(["/usr/bin/xcodebuild", "-version"], timeout=12)
            capture(["/usr/bin/xcrun", "--sdk", "iphoneos", "--show-sdk-path"], timeout=12)
        except (BuildError, OSError, subprocess.TimeoutExpired) as error:
            issues.append({"code": "xcode", "message":
                "Xcode chưa sẵn sàng để build iOS. Mở Xcode để hoàn tất cài thành phần và chấp nhận license. "
                f"Chi tiết: {str(error)[:500]}"})
    return issues


def scan_devices():
    with tempfile.TemporaryDirectory(prefix="cocos-devices-") as folder:
        output = Path(folder) / "devices.json"
        capture(["/usr/bin/xcrun", "devicectl", "list", "devices", "--timeout", "15",
                 "--json-output", str(output)], timeout=25)
        devices = []
        for device in read_json(output).get("result", {}).get("devices", []):
            hardware = device.get("hardwareProperties", {})
            if hardware.get("platform") != "iOS" or hardware.get("reality") != "physical":
                continue
            props = device.get("deviceProperties", {})
            connection = device.get("connectionProperties", {})
            devices.append({"id": device["identifier"], "udid": hardware.get("udid", ""),
                            "name": props.get("name", "iPhone").strip(),
                            "transport": connection.get("transportType", "unknown"),
                            "state": connection.get("tunnelState", "unknown"),
                            "developerMode": props.get("developerModeStatus", "unknown")})
        return devices


def simulator_catalog(version):
    runtimes = json.loads(capture(["/usr/bin/xcrun", "simctl", "list", "runtimes", "-j"]))
    types = json.loads(capture(["/usr/bin/xcrun", "simctl", "list", "devicetypes", "-j"]))["devicetypes"]
    arch = "x86_64" if tuple(map(int, version.split(".")[:2])) < (3, 8) else "arm64"
    result = []
    for runtime in runtimes.get("runtimes", []):
        if not runtime.get("isAvailable") or not runtime.get("name", "").startswith("iOS "):
            continue
        if runtime.get("supportedArchitectures") and arch not in runtime["supportedArchitectures"]:
            continue
        supported = runtime.get("supportedDeviceTypes")
        if supported is None:
            parts = [int(n) for n in runtime["version"].split(".")]
            parts += [0] * (3 - len(parts))
            encoded = (parts[0] << 16) + (parts[1] << 8) + parts[2]
            supported = [t for t in types if t.get("minRuntimeVersion", 0) <= encoded <= t.get("maxRuntimeVersion", 0xffffffff)]
        phones = [{"id": t["identifier"], "name": t["name"]} for t in supported if t["name"].startswith("iPhone")]
        if phones:
            result.append({"id": runtime["identifier"], "name": runtime["name"], "types": phones})
    return result


def create_simulator(name, type_id, runtime_id, version):
    if not name.strip() or len(name.strip()) > 100 or any(ord(c) < 32 for c in name):
        raise BuildError("Tên máy ảo cần từ 1 đến 100 ký tự, không chứa ký tự điều khiển.")
    options = simulator_catalog(version)
    if not any(r["id"] == runtime_id and any(t["id"] == type_id for t in r["types"]) for r in options):
        raise BuildError("Mẫu iPhone hoặc iOS runtime không còn khả dụng/tương thích. Mở lại phần Tạo máy ảo.")
    return capture(["/usr/bin/xcrun", "simctl", "create", name.strip(), type_id, runtime_id], timeout=90).strip()



def simulator_app_processes(device_id):
    output = capture(["/usr/bin/xcrun", "simctl", "spawn", device_id, "launchctl", "list"], timeout=25)
    if not isinstance(output, str):
        raise BuildError("Không xác minh được app đang chạy; giữ nguyên máy ảo.")
    if not re.search(r"PID\s+Status\s+Label", output):
        raise BuildError("Không xác minh được danh sách app đang chạy; giữ nguyên máy ảo.")
    apps = []
    for line in output.splitlines():
        parts = line.split(None, 2)
        if len(parts) != 3 or not parts[0].isdigit():
            continue
        label = parts[2]
        match = re.search(r"UIKitApplication:([^\[]+)", label)
        if match:
            bundle = match.group(1)
            if not bundle.startswith("com.apple."):
                apps.append({"bundle": bundle, "pid": int(parts[0])})
    return apps


def require_idle_simulator(device_id):
    apps = simulator_app_processes(device_id)
    if apps:
        raise BuildError("Máy ảo đang chạy app: " + ", ".join(a["bundle"] for a in apps) +
                         ". Tool không tắt/xóa máy này. Đóng app trên máy ảo trước nếu muốn tiếp tục.")


def delete_simulator(device_id):
    if not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", device_id):
        raise BuildError("ID máy ảo không hợp lệ.")
    device = next((d for d in scan_simulators() if d["id"] == device_id), None)
    if not device:
        raise BuildError("Máy ảo không còn tồn tại. Bấm Refresh.")
    if device["state"] == "Booted":
        require_idle_simulator(device_id)
        capture(["/usr/bin/xcrun", "simctl", "shutdown", device_id], timeout=60)
    elif device["state"] != "Shutdown":
        raise BuildError("Máy ảo đang chuyển trạng thái. Đợi máy bật/tắt xong rồi thử lại.")
    capture(["/usr/bin/xcrun", "simctl", "delete", device_id], timeout=90)


def set_simulator_power(device_id, powered, allow_running=False):
    if not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", device_id):
        raise BuildError("ID máy ảo không hợp lệ.")
    device = next((d for d in scan_simulators() if d["id"] == device_id), None)
    if not device:
        raise BuildError("Máy ảo không còn tồn tại. Bấm Refresh.")
    state = device["state"]
    if powered:
        if state == "Shutdown":
            capture(["/usr/bin/xcrun", "simctl", "boot", device_id], timeout=60)
        elif state not in ("Booted", "Booting"):
            raise BuildError("Máy ảo đang tắt. Đợi máy tắt xong rồi thử lại.")
        # Show startup immediately. Build & Run separately waits for full boot readiness.
        capture(["/usr/bin/open", "-a", "Simulator", "--args", "-CurrentDeviceUDID", device_id])
    elif state == "Booted":
        if not allow_running:
            require_idle_simulator(device_id)
        capture(["/usr/bin/xcrun", "simctl", "shutdown", device_id], timeout=60)
    elif state != "Shutdown":
        raise BuildError("Máy ảo đang chuyển trạng thái. Đợi máy bật/tắt xong rồi thử lại.")
    return device_id



def restart_simulator(device_id):
    # Explicit user action only: no erase, reinstall, or app relaunch.
    set_simulator_power(device_id, False, allow_running=True)
    return set_simulator_power(device_id, True)


def scan_simulators():
    runtimes = json.loads(capture(["/usr/bin/xcrun", "simctl", "list", "runtimes", "-j"]))
    runtime_map = {r["identifier"]: r for r in runtimes.get("runtimes", [])}
    devices = json.loads(capture(["/usr/bin/xcrun", "simctl", "list", "devices", "available", "-j"]))
    result = []
    for runtime_id, entries in devices.get("devices", {}).items():
        runtime = runtime_map.get(runtime_id, {})
        if "iOS" not in runtime.get("name", ""):
            continue
        for device in entries:
            if not device.get("isAvailable"):
                continue
            result.append({"id": device["udid"], "name": device["name"], "kind": "simulator",
                           "runtime": runtime.get("name", runtime_id),
                           "architectures": runtime.get("supportedArchitectures", []),
                           "state": device.get("state", "")})
    return result


def scan_teams():
    """Read public certificate subjects; never export private keys."""
    identities = capture(["/usr/bin/security", "find-identity", "-v", "-p", "codesigning"])
    valid = set(re.findall(r"\b[A-Fa-f0-9]{40}\b", identities.upper()))
    text = capture(["/usr/bin/security", "find-certificate", "-a", "-p"])
    teams = {}
    for cert in re.findall(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", text, re.S):
        result = subprocess.run(["/usr/bin/openssl", "x509", "-noout", "-subject", "-fingerprint", "-sha1", "-nameopt", "RFC2253"],
                                input=cert, capture_output=True, text=True)
        if "Apple Development" not in result.stdout and "iPhone Developer" not in result.stdout:
            continue
        fingerprint = re.search(r"Fingerprint=([A-Fa-f0-9:]+)", result.stdout)
        if not fingerprint or fingerprint[1].replace(":", "").upper() not in valid:
            continue
        subject = result.stdout.splitlines()[0]
        team = re.search(r"(?:^|,)OU=([A-Z0-9]{10})(?:,|$)", subject)
        name = re.search(r"CN=([^,]+)", result.stdout)
        if team:
            teams[team[1]] = name[1] if name else team[1]
    return teams


def inspect_project(folder: str):
    root = Path(folder).expanduser().resolve()
    package = read_json(root / "package.json")
    version = package.get("creator", {}).get("version", "")
    if not version or not (root / "assets").is_dir():
        raise BuildError("Chọn thư mục gốc project Cocos Creator, có package.json và assets.")
    if not version.startswith("3."):
        raise BuildError("Bản tool này hỗ trợ Cocos Creator 3.x.")
    profile = read_json(root / "profiles/v2/packages/builder.json")
    tasks = profile.get("BuildTaskManager", {}).get("taskMap", {})
    package_profiles = {}
    for profile_file in (root / "profiles/v2/packages").glob("*.json"):
        builder_profile = read_json(profile_file).get("builder", {})
        if "taskOptionsMap" in builder_profile or "ios" in builder_profile.get("options", {}):
            package_profiles[profile_file.stem] = builder_profile
    configs = []
    for key, task in tasks.items():
        options = task.get("options", {})
        if options.get("platform") != "ios":
            continue
        config = copy.deepcopy(options)
        for name, package_profile in package_profiles.items():
            settings = copy.deepcopy(package_profile.get("options", {}).get("ios", {}))
            settings.update(package_profile.get("taskOptionsMap", {}).get(key, {}))
            settings.update(config.setdefault("packages", {}).get(name, {}))
            config["packages"][name] = settings
        configs.append({"id": key, "label": f'{config.get("name", "iOS")} · {"Debug" if config.get("debug") else "Release"}', "options": config})
    if not configs:
        fallback = root / "buildCmd/buildConfig_ios.json"
        if fallback.exists():
            configs.append({"id": "file", "label": "buildConfig_ios.json", "options": read_json(fallback)})
    if not configs:
        raise BuildError("Chưa có task iOS. Tạo cấu hình iOS một lần trong Cocos rồi chọn lại project.")
    app = Path(f"/Applications/Cocos/Creator/{version}/CocosCreator.app/Contents/MacOS/CocosCreator")
    built_apps = list((root / "build/ios/proj/Debug-iphoneos").glob("*.app/Info.plist"))
    suggested_bundle = ""
    if len(built_apps) == 1:
        suggested_bundle = plistlib.loads(built_apps[0].read_bytes()).get("CFBundleIdentifier", "")
    return {"root": str(root), "version": version, "creator": str(app), "configs": configs,
            "suggestedBundle": suggested_bundle}


def make_config(options, team, bundle, simulator=False, reuse_existing=False):
    config = copy.deepcopy(options)
    config.pop("builderAutoRotate", None)
    kind = "simulator" if simulator else "device"
    config["platform"] = "ios"
    if not reuse_existing:
        config.update(buildPath=f"project://build/ios-builder/{kind}", outputName="ios")
    ios = config.setdefault("packages", {}).setdefault("ios", {})
    ios.update(packageName=bundle, developerTeam=team, skipUpdateXcodeProject=False,
               osTarget={"iphoneos": not simulator, "simulator": simulator})
    return config


def export_folder(root, config):
    value = config.get("buildPath", "project://build")
    base = root / value[len("project://"):] if value.startswith("project://") else Path(value).expanduser()
    if not base.is_absolute():
        base = root / base
    name = config.get("outputName", "ios")
    if Path(name).name != name or name in (".", ".."):
        raise BuildError("outputName của cấu hình Cocos phải là tên thư mục đơn.")
    return (base / name).resolve()


def input_fingerprint(root, config):
    """Stat-based incremental check. Force Export remains available in the UI."""
    digest = hashlib.sha256(json.dumps(config, sort_keys=True).encode())
    ignored = {".git", "node_modules", "__pycache__", "library", "temp", "build"}
    for name in ("assets", "settings", "extensions", "native-templates"):
        for folder, dirs, files in os.walk(root / name):
            dirs[:] = sorted(d for d in dirs if d not in ignored)
            for file in sorted(files):
                if file in (".git", ".DS_Store"):
                    continue
                path = Path(folder) / file
                st = path.stat()
                digest.update(f"{path.relative_to(root)}:{st.st_size}:{st.st_mtime_ns}\n".encode())
    for name in ("package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"):
        path = root / name
        if path.exists():
            digest.update(path.read_bytes())
    return digest.hexdigest()


class Builder:
    def __init__(self, log, stage):
        self.log = log
        self.stage = stage
        self.cancelled = threading.Event()
        self.process = None
        self.lock = threading.Lock()
        self.logfile = None
        self.console_bundle = None
        self.console_announced = False
        self.monitoring = False
        self.active_device_id = None

    def cancel(self):
        self.cancelled.set()
        with self.lock:
            process = self.process
            if process and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                threading.Thread(target=self._kill_later, args=(process,), daemon=True).start()

    @staticmethod
    def _kill_later(process):
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def write(self, text):
        self.log(text)
        if self.console_bundle and not self.console_announced and (
                text.startswith(self.console_bundle + ": ") or "Launched application with" in text or
                re.match(r"\d{2}:\d{2}:\d{2} \[(?:INFO|DEBUG|WARN|ERROR)\]", text)):
            self.console_announced = True
            self.stage("App đang chạy · Đang thu log · Dừng để kết thúc phiên")
        if self.logfile:
            self.logfile.write(text + "\n")
            self.logfile.flush()

    def run(self, args, cwd, timeout=None, success_codes=(0,)):
        if self.cancelled.is_set():
            raise BuildError("Đã dừng theo yêu cầu.")
        started = time.monotonic()
        self.write("$ " + " ".join(map(str, args)))
        with self.lock:
            if self.cancelled.is_set():
                raise BuildError("Đã dừng theo yêu cầu.")
            self.process = subprocess.Popen(list(map(str, args)), cwd=cwd, stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT, text=True, errors="replace",
                                            start_new_session=True, bufsize=1)
            process = self.process
        timer = None
        expired = threading.Event()
        if timeout:
            def expire():
                expired.set()
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                threading.Thread(target=self._kill_later, args=(process,), daemon=True).start()
            timer = threading.Timer(timeout, expire)
            timer.start()
        try:
            for line in process.stdout:
                self.write(line.rstrip())
            code = process.wait()
        finally:
            process.stdout.close()
            if timer:
                timer.cancel()
            with self.lock:
                self.process = None
        if self.cancelled.is_set():
            raise BuildError("Đã dừng theo yêu cầu.")
        if expired.is_set():
            raise BuildError(f"Lệnh timeout sau {timeout} giây: {Path(str(args[0])).name}. Đã dừng tác vụ; xem log để kiểm tra nguyên nhân.")
        self.write(f"Thời gian {Path(str(args[0])).name}: {time.monotonic() - started:.1f}s · mã {code}")
        if code not in success_codes:
            raise BuildError(f"Lệnh thất bại (mã {code}). Xem log ở trên.")

    def compatibility(self, project, creator, output, arch="arm64"):
        """Fix generated output only; leave the installed engine untouched."""
        pbx = project / "project.pbxproj"
        original = pbx.read_text()
        text = original
        native = creator.parent.parent / "Resources/resources/3d/engine/native"
        if (native / "external/sources/enoki/half.h").exists():
            text = text.replace('WARNING_CFLAGS = ("$(inherited)");',
                                'WARNING_CFLAGS = ("$(inherited)", "-Wno-invalid-specialization");')
            text = text.replace('WARNING_CFLAGS = "$(inherited)";',
                                'WARNING_CFLAGS = "$(inherited) -Wno-invalid-specialization";')
        webp = native / "external/ios/libs/libwebp.a"
        webp_refs = re.findall(r'"[^"\n]*libwebp\.a"|/[^\s,;()"]*libwebp\.a', text)
        if webp.exists() and webp_refs:
            compat = output / "compat-libs"
            compat.mkdir(exist_ok=True)
            thin, fixed = compat / "webp-original.a", compat / "libwebp.a"
            source_stat = webp.stat()
            key = {"source": str(webp.resolve()), "size": source_stat.st_size,
                   "mtime": source_stat.st_mtime_ns, "arch": arch}
            manifest = compat / "webp-cache.json"
            try:
                previous = read_json(manifest)
            except (OSError, ValueError):
                previous = {}
            if not fixed.is_file() or previous != key:
                self.run(["/usr/bin/xcrun", "lipo", webp, "-thin", arch, "-output", thin], output)
                self.run(["/usr/bin/xcrun", "libtool", "-static", thin, "-o", fixed], output)
                if fixed.is_file():
                    manifest.write_text(json.dumps(key, sort_keys=True))
            else:
                self.write("Cache native: dùng lại libwebp đã sửa cho " + arch)
            text = re.sub(r'"[^"\n]*libwebp\.a"|/[^\s,;()"]*libwebp\.a',
                          lambda _: json.dumps(str(fixed), ensure_ascii=False), text)
        if text != original:
            pbx.write_text(text)

    def build(self, project, options, creator_path, team, bundle, device, native_only=False, console=True,
              reuse_existing=False, force_export=False, build_only=False, target_kind=None):
        root = Path(project)
        creator = Path(creator_path)
        simulator = device.get("kind") == "simulator" if device else target_kind == "simulator"
        version = inspect_project(project)["version"]
        arch = "x86_64" if simulator and tuple(map(int, version.split(".")[:2])) < (3, 8) else "arm64"
        if not creator.is_file():
            raise BuildError("Không tìm thấy Cocos Creator. Chọn file thực thi trong phần Cài đặt.")
        if not simulator and not re.fullmatch(r"[A-Z0-9]{10}", team):
            raise BuildError("Team ID phải gồm 10 ký tự, ví dụ ZJNZHW895X.")
        if not re.fullmatch(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", bundle):
            raise BuildError("Bundle ID không hợp lệ, ví dụ com.company.game.debug.")
        if not build_only and (not device or not device.get("id")):
            raise BuildError("Chọn iPhone trước khi build.")
        device = device or {"kind": "simulator" if simulator else "device", "id": ""}
        if not build_only and device.get("developerMode") == "disabled":
            raise BuildError("Bật Developer Mode trên iPhone trước khi chạy app.")
        capture(["/usr/bin/xcodebuild", "-version"])
        if not build_only and simulator and device.get("architectures") and arch not in device["architectures"]:
            raise BuildError(f"Cocos {version} cần simulator {arch}. Runtime này không hỗ trợ. "
                             "Cài iOS Universal Runtime trong Xcode Settings → Components rồi Refresh.")
        output = root / "build/ios-builder" / ("simulator" if simulator else "device")
        output.mkdir(parents=True, exist_ok=True)
        # One process owns a project build at a time, including separate app instances.
        import fcntl
        with (output.parent / "build.lock").open("w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise BuildError("Project này đang được build bởi một phiên tool khác.")
            stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
            logs = output / "logs"
            logs.mkdir(exist_ok=True)
            with (logs / f"{stamp}.log").open("w") as self.logfile:
                try:
                    self.write(f"Log: {self.logfile.name}")
                    config_path = output / "builder-config.json"
                    build_config = make_config(options, team, bundle, simulator, reuse_existing)
                    config_path.write_text(json.dumps(build_config, indent=2))
                    exported = export_folder(root, build_config)
                    marker = exported / ".cocos-ios-builder-export.json"
                    try:
                        baseline = read_json(marker)
                    except (OSError, ValueError):
                        baseline = {}
                    fingerprint = input_fingerprint(root, build_config)
                    cached = (not force_export and baseline.get("fingerprint") == fingerprint
                              and bool(list((exported / "proj").glob("*.xcodeproj"))))
                    self.write("Cache Cocos: " + ("HIT · bỏ qua export" if cached else "MISS · đầu vào thay đổi hoặc chưa có cache"))
                    if not native_only and not cached:
                        self.stage("1/4 · Cocos: xuất project iOS")
                        self.run([creator, "--nologin", "--project", root,
                                  "--build", f"configPath={config_path}"], root, timeout=1800, success_codes=(0, 36))
                    else:
                        self.stage("1/4 · Dùng bản xuất Cocos đã có" if native_only else
                                   "1/4 · Asset/script không đổi · Dùng cache Cocos")
                    self.write(f"Output Cocos: {exported}")
                    proj = exported / "proj"
                    projects = list(proj.glob("*.xcodeproj"))
                    if len(projects) != 1:
                        raise BuildError(f"Cần đúng một .xcodeproj trong {proj}. Chạy build Cocos trước.")
                    project_file = projects[0]
                    if not native_only and not cached:
                        marker.write_text(json.dumps({"fingerprint": input_fingerprint(root, build_config)}))
                    schemes = list((project_file / "xcshareddata/xcschemes").glob("*-mobile.xcscheme"))
                    names = [s.stem for s in schemes]
                    if not names:
                        listing = json.loads(capture(["/usr/bin/xcodebuild", "-list", "-json", "-project", str(project_file)], timeout=60))
                        names = [s for s in listing.get("project", {}).get("schemes", []) if s.endswith("-mobile")]
                    if len(names) != 1:
                        raise BuildError("Không xác định được scheme *-mobile. Kiểm tra output Cocos.")
                    scheme = names[0]
                    controller = root / "native/engine/ios/ViewController.mm"
                    if controller.is_file():
                        from autorotate import configure_rotation
                        before = controller.read_text()
                        try:
                            after = configure_rotation(before, options.get("builderAutoRotate", True),
                                                       build_config.get("packages", {}).get("ios", {}).get("orientation", {}))
                        except ValueError as error:
                            raise BuildError(str(error)) from error
                        if before != after:
                            controller.write_text(after)
                        self.write("Auto Rotate: " + ("ON · theo các hướng đã chọn" if options.get("builderAutoRotate", True) else "OFF · dùng logic native của game"))
                    elif options.get("builderAutoRotate", True):
                        self.write("Warning: Không tìm thấy native/engine/ios/ViewController.mm; chưa áp dụng Auto Rotate cho template này.")
                    self.compatibility(project_file, creator, output, arch)
                    # Cocos emits a literal CFBundleIdentifier. Command-line build setting alone
                    # does not override it, so update the generated source Info.plist as well.
                    pbx = (project_file / "project.pbxproj").read_text()
                    for value in set(re.findall(r'INFOPLIST_FILE\s*=\s*"?([^;"\n]+)"?;', pbx)):
                        info = Path(value)
                        if not info.is_absolute():
                            info = proj / info
                        info = info.resolve()
                        if not info.is_relative_to(exported) or not info.is_file():
                            raise BuildError(f"Info.plist không nằm trong output: {info}")
                        data = plistlib.loads(info.read_bytes())
                        if data.get("CFBundleIdentifier") != bundle:
                            data["CFBundleIdentifier"] = bundle
                            info.write_bytes(plistlib.dumps(data))
                    config = "Debug" if options.get("debug", True) else "Release"
                    self.stage("2/4 · Biên dịch app simulator" if simulator else "2/4 · Biên dịch và ký app")
                    build_args = ["/usr/bin/xcodebuild", "-project", project_file, "-scheme", scheme,
                                  "-configuration", config, "-sdk", "iphonesimulator" if simulator else "iphoneos",
                                  "-destination-timeout", "30", "-destination", "generic/platform=iOS Simulator" if simulator else
                                  ("generic/platform=iOS" if build_only else f'id={device.get("udid") or device["id"]}'),
                                  f"PRODUCT_BUNDLE_IDENTIFIER={bundle}", f"ARCHS={arch}", "ONLY_ACTIVE_ARCH=YES"]
                    if simulator:
                        build_args += ["CODE_SIGNING_ALLOWED=NO"]
                    else:
                        build_args += ["-allowProvisioningUpdates", "-allowProvisioningDeviceRegistration",
                                       f"DEVELOPMENT_TEAM={team}", "CODE_SIGN_STYLE=Automatic"]
                    self.run(build_args + ["build"], root, timeout=1800)
                    # Never override CONFIGURATION_BUILD_DIR globally: CMake's static-library
                    # references use the per-target archive directories. Ask Xcode for the app.
                    settings = json.loads(capture(build_args + ["-showBuildSettings", "-json"], timeout=60))
                    matches = [entry["buildSettings"] for entry in settings if entry.get("target") == scheme]
                    if len(matches) != 1:
                        raise BuildError("Không tìm được đường dẫn app trong Xcode build settings.")
                    app = Path(matches[0]["TARGET_BUILD_DIR"]) / matches[0]["FULL_PRODUCT_NAME"]
                    if not app.is_dir():
                        raise BuildError(f"Build xong nhưng không tìm thấy {app.name}.")
                    actual = plistlib.loads((app / "Info.plist").read_bytes())["CFBundleIdentifier"]
                    if actual != bundle:
                        raise BuildError(f"Bundle ID trong app ({actual}) chưa khớp với signing ({bundle}).")
                    artifact = {"app": str(app), "bundle": bundle,
                                "options": hashlib.sha256(json.dumps(options, sort_keys=True).encode()).hexdigest()}
                    (output / "last-built.json").write_text(json.dumps(artifact))
                    if build_only:
                        self.stage("Build hoàn tất · Có thể chọn thiết bị và bấm Run")
                        return str(app)
                    return self.deploy(root, app, bundle, device, arch, console)
                finally:
                    self.logfile = None


    def monitor_files(self, paths, device, bundle, from_end=False):
        self.monitoring = True
        self.stage("App đang chạy · Thu log độc lập · Dừng chỉ ngắt thu log")
        handles = []
        try:
            for path in paths:
                handle = Path(path).open("r", errors="replace")
                if from_end:
                    handle.seek(0, 2)
                handles.append(handle)
            next_check = 0
            while not self.cancelled.is_set():
                for handle in handles:
                    for line in handle.readlines(65536):
                        self.write(line.rstrip())
                if time.monotonic() >= next_check:
                    apps = simulator_app_processes(device["id"])
                    if not any(a["bundle"] == bundle for a in apps):
                        self.stage("App đã tự kết thúc · Tool không tự chạy lại · Xem log để tìm nguyên nhân")
                        return
                    next_check = time.monotonic() + 3
                self.cancelled.wait(0.15)
            self.stage("Đã ngắt thu log · App tiếp tục chạy độc lập")
        finally:
            for handle in handles:
                handle.close()
            self.monitoring = False

    def deploy(self, root, app, bundle, device, arch, console, run_only=False, clean=False):
        def stage(text):
            self.stage(text.replace("3/4", "1/2").replace("4/4", "2/2") if run_only else text)
        self.active_device_id = device["id"]
        if device.get("kind") == "simulator":
            stage("3/4 · Chuẩn bị simulator · Giữ nguyên app đã cài")
            latest = json.loads(capture(["/usr/bin/xcrun", "simctl", "list", "devices", "-j"]))
            current = next((entry for entries in latest.get("devices", {}).values()
                            for entry in entries if entry["udid"] == device["id"]), None)
            if current is None:
                raise BuildError("Simulator đã bị xóa. Bấm Refresh rồi chọn lại thiết bị.")
            if current.get("state") == "Shutdown":
                self.run(["/usr/bin/xcrun", "simctl", "boot", device["id"]], root, timeout=60)
            self.run(["/usr/bin/xcrun", "simctl", "bootstatus", device["id"], "-b"], root, timeout=180)
            self.run(["/usr/bin/open", "-a", "Simulator", "--args", "-CurrentDeviceUDID", device["id"]], root)
            if clean:
                stage("Clean & Run · Xóa app và dữ liệu trên " + device["name"])
                self.run(["/usr/bin/xcrun", "simctl", "uninstall", device["id"], bundle], root, timeout=90)
            running = simulator_app_processes(device["id"])
            existing = next((a for a in running if a["bundle"] == bundle), None)
            log_dir = Path(self.logfile.name).parent / "app-output" / device["id"]
            log_dir.mkdir(parents=True, exist_ok=True)
            record = log_dir / (bundle + ".json")
            paths = []
            if existing:
                self.write(f'Giữ nguyên app đang chạy · PID {existing["pid"]} · Không cài đè, không restart.')
                try:
                    paths = [Path(p) for p in read_json(record).get("paths", [])]
                except (OSError, ValueError):
                    paths = []
                if console and paths and all(p.is_file() for p in paths):
                    self.monitor_files(paths, device, bundle, from_end=True)
                elif console:
                    self.observe(root, bundle, device)
                else:
                    stage("App đang chạy · Giữ nguyên phiên hiện tại")
                return str(app)
            installed_output = capture(["/usr/bin/xcrun", "simctl", "listapps", device["id"]], timeout=30)
            try:
                installed = json.loads(installed_output)
            except ValueError:
                try:
                    installed = plistlib.loads(installed_output.encode())
                except Exception:
                    converted = subprocess.run(["/usr/bin/plutil", "-convert", "json", "-o", "-", "--", "-"],
                                               input=installed_output, text=True, capture_output=True, timeout=10)
                    if converted.returncode:
                        raise BuildError("Không đọc được app đã cài; dừng để tránh cài đè app.")
                    installed = json.loads(converted.stdout)
            if not isinstance(installed, dict):
                raise BuildError("Không xác minh được app đã cài; giữ nguyên máy ảo.")
            if bundle not in installed:
                self.run(["/usr/bin/xcrun", "simctl", "install", device["id"], app], root, timeout=90)
            else:
                self.write("App đã được cài · Không tự cài đè. Run dùng bản đang có trên máy ảo.")
            stage("4/4 · Mở app độc lập · Không gắn console vào tiến trình game")
            stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            paths = [log_dir / (stamp + "-stdout.log"), log_dir / (stamp + "-stderr.log")]
            for path in paths:
                path.touch()
            launch = ["/usr/bin/xcrun", "simctl", "launch", "--arch=" + arch,
                      "--stdout=" + str(paths[0]), "--stderr=" + str(paths[1]), device["id"], bundle]
            self.run(launch, root, timeout=90)
            record.write_text(json.dumps({"paths": [str(p) for p in paths]}))
            if console:
                self.monitor_files(paths, device, bundle)
            else:
                stage(f"Đã khởi chạy độc lập trên {device['name']}")
            return str(app)
        stage("3/4 · Kiểm tra app trên iPhone · Không cài đè app đã có")
        with tempfile.TemporaryDirectory() as folder:
            result = Path(folder) / "apps.json"
            capture(["/usr/bin/xcrun", "devicectl", "device", "info", "apps", "--device", device["id"],
                     "--bundle-id", bundle, "--json-output", str(result)], timeout=40)
            apps = read_json(result).get("result", {}).get("apps")
            if not isinstance(apps, list):
                raise BuildError("Không xác minh được app trên iPhone; dừng để tránh cài đè.")
            if clean and apps:
                stage("Clean & Run · Xóa app và dữ liệu trên " + device["name"])
                self.run(["/usr/bin/xcrun", "devicectl", "device", "uninstall", "app", "--device",
                          device["id"], bundle, "--timeout", "90"], root, timeout=105)
                apps = []
            if not apps:
                self.run(["/usr/bin/xcrun", "devicectl", "device", "install", "app", "--device",
                          device["id"], app, "--timeout", "120"], root, timeout=135)
            else:
                self.write("Giữ app đã cài trên iPhone · Không tự cài đè.")
            stage("4/4 · Mở app độc lập trên iPhone")
            result = Path(folder) / "launch.json"
            self.run(["/usr/bin/xcrun", "devicectl", "device", "process", "launch", "--device", device["id"],
                      "--json-output", result, bundle], root, timeout=60)
        if console:
            self.write("Không gắn console vào app trên iPhone để Dừng/đóng tool không truyền tín hiệu kết thúc game.")
        stage(f"Đã mở app độc lập trên {device['name']}")
        return str(app)


    def run_existing(self, project, options, bundle, device, console=True, reuse_existing=True, clean=False):
        if not device or not device.get("id"):
            raise BuildError("Chọn thiết bị trước khi Run.")
        root = Path(project)
        simulator = device.get("kind") == "simulator"
        kind = "simulator" if simulator else "device"
        # An already-running app needs neither build artifacts nor the build lock.
        # This also permits safe observation while another device has a legacy session.
        if not clean and simulator and device.get("state") == "Booted":
            active = next((a for a in simulator_app_processes(device["id"]) if a["bundle"] == bundle), None)
            if active:
                self.active_device_id = device["id"]
                self.run(["/usr/bin/open", "-a", "Simulator", "--args", "-CurrentDeviceUDID", device["id"]], root)
                if console:
                    return self.observe(project, bundle, device)
                self.stage(f'App đang chạy · Giữ nguyên PID {active["pid"]}')
                return "Giữ nguyên app đang chạy"
        output = root / "build/ios-builder" / kind
        output.mkdir(parents=True, exist_ok=True)
        import fcntl
        with (output.parent / "build.lock").open("w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise BuildError("Project đang có phiên build/run khác. Dừng phiên đó trước.")
            logs = output / "logs"
            logs.mkdir(exist_ok=True)
            with (logs / (dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-run.log")).open("w") as self.logfile:
                try:
                    self.stage("Run · Tìm app đã build · Bỏ qua Cocos và biên dịch")
                    signature = hashlib.sha256(json.dumps(options, sort_keys=True).encode()).hexdigest()
                    try:
                        artifact = read_json(output / "last-built.json")
                    except (OSError, ValueError):
                        artifact = {}
                    candidates = []
                    if artifact.get("options") == signature and artifact.get("bundle") == bundle:
                        candidates.append(Path(artifact["app"]))
                    config = make_config(options, "", bundle, simulator, reuse_existing)
                    exported = export_folder(root, config)
                    configuration = "Debug" if options.get("debug", True) else "Release"
                    sdk = "iphonesimulator" if simulator else "iphoneos"
                    candidates.extend((exported / "proj" / f"{configuration}-{sdk}").glob("*.app"))
                    platform = "iPhoneSimulator" if simulator else "iPhoneOS"
                    matches = []
                    for app in dict.fromkeys(candidates):
                        try:
                            info = plistlib.loads((app / "Info.plist").read_bytes())
                        except (OSError, ValueError, plistlib.InvalidFileException):
                            continue
                        if info.get("CFBundleIdentifier") == bundle and platform in info.get("CFBundleSupportedPlatforms", []):
                            matches.append((app, info))
                    if not matches:
                        raise BuildError(f"Chưa có app {configuration} phù hợp cho {kind} với Bundle ID {bundle}. Bấm Build & Run một lần trước.")
                    app, info = matches[0]
                    executable = app / info.get("CFBundleExecutable", "")
                    if not executable.is_file():
                        raise BuildError("Bản app không còn đầy đủ. Bấm Build & Run để tạo lại.")
                    architectures = capture(["/usr/bin/xcrun", "lipo", "-archs", str(executable)]).split()
                    supported = device.get("architectures", []) if simulator else ["arm64"]
                    arch = next((a for a in architectures if (not supported or a in supported) and a in ("arm64", "x86_64")), None)
                    if not arch:
                        raise BuildError("App đã build không tương thích kiến trúc máy đang chọn. Bấm Build & Run cho máy này.")
                    if device.get("developerMode") == "disabled":
                        raise BuildError("Bật Developer Mode trên iPhone trước khi Run.")
                    self.write(f"Run bản có sẵn: {app}\nBundle ID: {bundle} · Kiến trúc: {arch}")
                    return self.deploy(root, app, bundle, device, arch, console, run_only=True, clean=clean)
                finally:
                    self.logfile = None


    def observe(self, project, bundle, device):
        if device.get("kind") != "simulator":
            raise BuildError("Thu log độc lập hiện hỗ trợ Simulator; không gắn console vào iPhone để tránh truyền tín hiệu vào app.")
        self.active_device_id = device["id"]
        apps = simulator_app_processes(device["id"])
        app = next((a for a in apps if a["bundle"] == bundle), None)
        if not app:
            raise BuildError("App chưa chạy trên máy đã chọn. Device log không tự mở hoặc chạy lại app.")
        logs = Path(project) / "build/ios-builder/simulator/logs"
        logs.mkdir(parents=True, exist_ok=True)
        record = logs / "app-output" / device["id"] / (bundle + ".json")
        with (logs / (dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f") + "-observe.log")).open("w") as self.logfile:
            try:
                try:
                    paths = [Path(p) for p in read_json(record).get("paths", [])]
                except (OSError, ValueError):
                    paths = []
                self.write(f'Device log: {device["name"]} · PID {app["pid"]} · Chỉ đọc log')
                if paths and all(p.is_file() for p in paths):
                    self.monitor_files(paths, device, bundle, from_end=True)
                else:
                    self.monitoring = True
                    self.stage("App đang chạy · Thu log hệ thống độc lập · Dừng chỉ ngắt thu log")
                    self.write("App không có file stdout do tool tạo; đang đọc unified log của tiến trình, có thể không có đầy đủ console.log JavaScript.")
                    try:
                        self.run(["/usr/bin/xcrun", "simctl", "spawn", device["id"], "log", "stream", "--style", "compact",
                                  "--level", "debug", "--predicate", f'processIdentifier == {app["pid"]}'], Path(project))
                    except BuildError:
                        if not self.cancelled.is_set():
                            raise
                    self.stage("Đã ngắt thu log · App tiếp tục chạy độc lập")
            finally:
                self.monitoring = False
                self.logfile = None
        return "Đã ngắt thu log; không tác động app"
