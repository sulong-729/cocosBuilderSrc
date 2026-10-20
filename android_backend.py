"""Android tools and APK workflows. All commands use argument lists and explicit targets."""
from __future__ import annotations

import copy
from collections import deque
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import signal
import shutil
import sys
import subprocess
import tempfile
import threading
import time

from backend import BuildError, export_folder, input_fingerprint, read_json

ABIS = ('arm64-v8a', 'armeabi-v7a', 'x86_64', 'x86')
SECRET = re.compile(r'password|passwd|xxteaKey|token|secret', re.I)


class AndroidDependencyError(BuildError):
    """Actionable dependency failures that the UI can display as setup notices."""

    def __init__(self, issues):
        self.issues = list(issues)
        super().__init__('\n'.join(self.issues))


class AndroidDeviceError(BuildError):
    """The exact selected target is missing or not ready for an operation."""


def sdk_install_message(name):
    package = ('Android SDK Command-line Tools (latest)' if name in ('avdmanager', 'sdkmanager')
               else 'Android Emulator' if name == 'emulator'
               else 'Android SDK Platform Tools' if name == 'adb'
               else 'Android SDK Build Tools')
    return f'Thiếu {name}. Mở Android Studio → Tools → SDK Manager → SDK Tools, cài {package}, rồi Kiểm tra công cụ / Refresh lại.'


def strip_secrets(value):
    if isinstance(value, dict):
        return {k: strip_secrets(v) for k, v in value.items() if not SECRET.search(k)}
    if isinstance(value, list):
        return [strip_secrets(v) for v in value]
    return value


def version_key(value):
    return tuple(int(n) for n in re.findall(r'\d+', str(value)))


def inspect_android_project(folder):
    root = Path(folder).expanduser().resolve()
    version = read_json(root / 'package.json').get('creator', {}).get('version', '')
    if not version.startswith('3.') or not (root / 'assets').is_dir():
        raise BuildError('Chọn project Cocos Creator 3.x có package.json và assets.')
    profiles = root / 'profiles/v2/packages'
    tasks = read_json(profiles / 'builder.json').get('BuildTaskManager', {}).get('taskMap', {})
    packages = {p.stem: read_json(p).get('builder', {}) for p in profiles.glob('*.json')}
    configs = []
    for key, task in tasks.items():
        options = copy.deepcopy(task.get('options', {}))
        if options.get('platform') != 'android':
            continue
        for name, package in packages.items():
            settings = copy.deepcopy(package.get('options', {}).get('android', {}))
            settings.update(package.get('taskOptionsMap', {}).get(key, {}))
            settings.update(options.get('packages', {}).get(name, {}))
            if settings:
                options.setdefault('packages', {})[name] = settings
        configs.append({'id': key, 'label': f'{options.get("name", "Android")} · {"Debug" if options.get("debug", True) else "Release"}', 'options': options})
    fallback = root / 'buildCmd/buildConfig_android.json'
    if not configs and fallback.is_file():
        configs.append({'id': 'file', 'label': fallback.name, 'options': read_json(fallback)})
    return {'root': str(root), 'version': version, 'configs': configs,
            'creator': f'/Applications/Cocos/Creator/{version}/CocosCreator.app/Contents/MacOS/CocosCreator'}


def discover_studios(directories=None):
    apps = []
    for directory in directories or [Path('/Applications'), Path.home() / 'Applications']:
        for path in Path(directory).glob('*.app'):
            try:
                info = plistlib.loads((path / 'Contents/Info.plist').read_bytes())
            except (OSError, ValueError, plistlib.InvalidFileException):
                continue
            if info.get('CFBundleIdentifier', '').startswith('com.google.android.studio'):
                java = next((str(path / part) for part in ('Contents/jbr/Contents/Home', 'Contents/jre/Contents/Home', 'Contents/jre/jdk/Contents/Home') if (path / part / 'bin/java').is_file()), '')
                apps.append({'path': str(path), 'version': info.get('CFBundleShortVersionString', '?'), 'java': java})
    return sorted(apps, key=lambda a: (version_key(a['version']), a['path']), reverse=True)


def discover_java_homes():
    homes = {s['java'] for s in discover_studios() if s['java']}
    for folder in (Path('/Library/Java/JavaVirtualMachines'), Path.home() / 'Library/Java/JavaVirtualMachines'):
        homes.update(str(p) for p in folder.glob('*/Contents/Home') if (p / 'bin/java').is_file())
    return sorted(homes, key=lambda p: (java_major(p) != 11, java_major(p), p))


def merge_android_targets(avds, devices):
    targets = {f'avd:{name}': {'id': f'avd:{name}', 'avd': name, 'kind': 'emulator',
                             'name': name, 'serial': '', 'state': 'stopped'} for name in avds}
    instances = {}
    for device in devices:
        if device.get('avd'): instances[device['avd']] = instances.get(device['avd'], 0) + 1
    for original in devices:
        device = dict(original)
        avd = device.get('avd') if device.get('kind') == 'emulator' else None
        key = f'avd:{avd}' if avd else f'serial:{device["serial"]}'
        if avd and instances.get(avd, 0) > 1:
            targets.pop(f'avd:{avd}', None)
            key = f'serial:{device["serial"]}'
        if key in targets and targets[key]['serial']:
            key = f'serial:{device["serial"]}'
        device['id'] = key
        if avd: device['name'] = avd
        targets[key] = device
    return list(targets.values())


def sdk_inventory(sdk):
    root = Path(sdk).expanduser()
    def directories(name):
        return sorted([str(p) for p in (root / name).glob('*') if p.is_dir()], key=version_key, reverse=True)
    return {name: directories(name) for name in ('ndk', 'platforms', 'build-tools', 'system-images')}


def default_sdk():
    for candidate in [os.environ.get('ANDROID_SDK_ROOT'), os.environ.get('ANDROID_HOME'), str(Path.home() / 'Library/Android/sdk')]:
        if candidate and Path(candidate).is_dir():
            return str(Path(candidate).expanduser())
    return str(Path.home() / 'Library/Android/sdk')


def sdk_tool(sdk, name):
    root = Path(sdk).expanduser()
    if name == 'adb':
        return root / 'platform-tools/adb'
    if name == 'emulator':
        return root / 'emulator/emulator'
    if name in ('sdkmanager', 'avdmanager'):
        candidates = sorted((root / 'cmdline-tools').glob(f'*/bin/{name}'), key=lambda p: (p.parents[1].name == 'latest', version_key(p.parents[1].name)), reverse=True)
    else:
        candidates = sorted((root / 'build-tools').glob(f'*/{name}'), key=version_key, reverse=True)
    return candidates[0] if candidates else root / f'missing/{name}'


def creator_version(executable):
    path = Path(executable).expanduser()
    try:
        return plistlib.loads((path.parents[1] / 'Info.plist').read_bytes()).get('CFBundleShortVersionString', '')
    except (OSError, ValueError, IndexError, plistlib.InvalidFileException):
        return ''


def java_major(java_home):
    release = Path(java_home).expanduser() / 'release'
    match = re.search(r'JAVA_VERSION="(\d+)(?:\.(\d+))?', release.read_text() if release.is_file() else '')
    return (int(match[2]) if match[1] == '1' else int(match[1])) if match else 0


def check_android_tools(tools, version, build=True, include_avd=False):
    tools = {k: str(Path(v).expanduser()) if v and k in ('creator', 'sdk', 'ndk', 'java') else v for k, v in tools.items()}
    issues = []
    executable = Path(tools.get('creator') or '/missing')
    if build and not (executable.is_file() and os.access(executable, os.X_OK)):
        issues.append(f'Thiếu Cocos Creator {version}. Cài bằng Cocos Dashboard hoặc chọn executable đúng phiên bản.')
    elif build and creator_version(executable) != version:
        issues.append(f'Cocos đã chọn là {creator_version(executable) or "không xác định"}; project cần {version}.')
    sdk = Path(tools.get('sdk') or '/missing')
    if not sdk_tool(sdk, 'adb').is_file():
        issues.append(sdk_install_message('adb'))
    if build:
        if not (Path(tools.get('java') or '/missing') / 'bin/java').is_file():
            issues.append('Thiếu JDK. Chọn Java Home từ Android Studio hoặc JDK đã cài.')
        if not (Path(tools.get('ndk') or '/missing') / 'source.properties').is_file():
            issues.append('Thiếu NDK. Chọn bản đã cài hoặc cài NDK (Side by side) trong SDK Manager.')
        for name in ('aapt', 'apksigner'):
            if not sdk_tool(sdk, name).is_file():
                issues.append(sdk_install_message(name))
        if not list((sdk / 'platforms').glob('android-*/android.jar')):
            issues.append('Thiếu Android SDK Platform. Cài API phù hợp trong SDK Manager.')
    if include_avd:
        for name in ('emulator', 'avdmanager', 'sdkmanager'):
            if not sdk_tool(sdk, name).is_file(): issues.append(sdk_install_message(name))
    return issues


def android_environment(tools):
    env = dict(os.environ)
    for key, value in (('JAVA_HOME', tools.get('java')), ('ANDROID_HOME', tools.get('sdk')), ('ANDROID_SDK_ROOT', tools.get('sdk')), ('ANDROID_NDK_HOME', tools.get('ndk')), ('ANDROID_NDK_ROOT', tools.get('ndk'))):
        if value:
            env[key] = str(Path(value).expanduser())
    bins = [str(Path(tools[k]).expanduser() / part) for k, part in (('java', 'bin'), ('sdk', 'platform-tools'), ('sdk', 'emulator')) if tools.get(k)]
    env['PATH'] = os.pathsep.join(bins + [env.get('PATH', '')])
    return env


def validate_android_options(options):
    scenes = options.get('scenes', [])
    if not scenes or options.get('startScene') not in [s.get('uuid') for s in scenes]:
        return 'Chọn scene và scene khởi động trong danh sách build.'
    android = options.get('packages', {}).get('android', {})
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+', android.get('packageName', '')):
        return 'Package ID không hợp lệ, ví dụ com.company.game.'
    if not android.get('appABIs') or any(a not in ABIS for a in android['appABIs']):
        return 'Chọn ít nhất một ABI Android hợp lệ.'
    if not str(android.get('apiLevel', 27)).isdigit() or int(android.get('apiLevel', 27)) < 21:
        return 'Android API phải là số nguyên từ 21 trở lên.'
    orientation = android.get('orientation', {})
    if orientation and not any(orientation.values()):
        return 'Chọn ít nhất một hướng màn hình.'
    native = options.get('packages', {}).get('native', {})
    if native.get('encrypted') and not native.get('xxteaKey'):
        return 'Nhập khóa XXTEA để mã hóa script (khóa không được lưu trong settings tool).'
    override = options.get('builderAndroid', {})
    for key in ('minSdk', 'compileSdk', 'versionCode'):
        value = str(override.get(key, ''))
        if value and (not value.isdigit() or not 1 <= int(value) <= 2100000000):
            return f'{key} phải là số nguyên dương hợp lệ.'
    if override.get('minSdk') and int(override['minSdk']) > int(android.get('apiLevel', 27)):
        return 'Minimum SDK không được cao hơn target API.'
    if override.get('compileSdk') and int(override['compileSdk']) < int(android.get('apiLevel', 27)):
        return 'Compile SDK không được thấp hơn target API.'
    return ''


def make_android_config(options, tools, package):
    config = copy.deepcopy(options)
    config.update(platform='android')
    config.setdefault('buildPath', 'project://build/android-builder')
    config.setdefault('outputName', 'android')
    android = config.setdefault('packages', {}).setdefault('android', {})
    android.update(packageName=package, sdkPath=tools['sdk'], ndkPath=tools['ndk'], appBundle=False, androidInstant=False)
    return config


def parse_devices(text):
    devices = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2 or parts[1] not in ('device', 'unauthorized', 'offline', 'recovery', 'sideload', 'no'):
            continue
        fields = dict(p.split(':', 1) for p in parts[2:] if ':' in p)
        serial = parts[0]
        devices.append({'serial': serial, 'state': parts[1], 'name': fields.get('model', serial).replace('_', ' '), 'kind': 'emulator' if serial.startswith('emulator-') else 'device'})
    return devices


def parse_badging(text):
    package = re.search(r"^package: name='([^']+)'", text, re.M)
    activity = re.search(r"^launchable-activity: name='([^']+)'", text, re.M)
    abis = re.search(r'^native-code: (.*)', text, re.M)
    min_sdk = re.search(r"^sdkVersion:'(\d+)'", text, re.M)
    if not package:
        raise BuildError('Không đọc được Package ID từ APK.')
    return {'package': package[1], 'activity': activity[1] if activity else '', 'abis': re.findall(r"'([^']+)'", abis[1]) if abis else [], 'minSdk': int(min_sdk[1]) if min_sdk else 1}


def select_apk(folder, variant):
    files = sorted(p for p in Path(folder).rglob('*.apk') if 'outputs' in p.parts and 'apk' in p.parts and variant in p.parts and not p.name.endswith('-unsigned.apk'))
    if len(files) != 1:
        raise BuildError(f'Cần đúng một APK {variant} đã ký trong {folder}; tìm thấy {len(files)}. Kiểm tra output/split APK/signing trong Android Studio.')
    return files[0]


def apk_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def gradle_override_script(values):
    statements = []
    for key in ('minSdk', 'versionCode'):
        if values.get(key): statements.append(f'p.android.defaultConfig.{"minSdkVersion" if key == "minSdk" else key} = {int(values[key])}')
    if values.get('compileSdk'): statements.append(f'p.android.compileSdkVersion({int(values["compileSdk"])})')
    if values.get('versionName'):
        literal = str(values['versionName']).replace('\\', '\\\\').replace("'", "\\'").replace('\n', '\\n').replace('\r', '\\r')
        statements.append("p.android.defaultConfig.versionName = '" + literal + "'")
    # Register before project evaluation, hence before AGP registers its own
    # afterEvaluate callback to create variants and freeze the Android DSL.
    return 'gradle.beforeProject { p ->\n p.afterEvaluate {\n if (p.plugins.hasPlugin("com.android.application")) {\n' + '\n'.join(statements) + '\n }\n }\n}\n'


def prepare_creator_cli(executable, cache_root=None):
    """Use a private copy-on-write Creator agent without modifying its install.

    Electron helpers/frameworks must keep the original complete bundle topology.
    APFS cloning shares unchanged file data; signing changes only the private copy.
    """
    source = Path(executable).expanduser()
    if sys.platform != 'darwin' or not source.is_file(): return source
    contents = source.parents[1]
    info_path = contents / 'Info.plist'
    if not info_path.is_file() or not (contents / 'Resources/app.asar').is_file():
        raise BuildError('Cocos CLI cần executable trong CocosCreator.app hợp lệ; không mở editor thay thế.')
    archive = contents / 'Resources/app.asar'
    archive_stamp = archive.stat()
    identity = hashlib.sha256(b'agent-v5-cow' + str(source.resolve()).encode() + source.read_bytes() + info_path.read_bytes() + f'{archive_stamp.st_size}:{archive_stamp.st_mtime_ns}'.encode()).hexdigest()[:20]
    cache_root = Path(cache_root) if cache_root is not None else Path.home() / 'Library/Caches/Cocos Builder/creator-cli'
    destination = cache_root / identity / contents.parent.name
    worker = destination / 'Contents/MacOS' / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Other projects may request the same worker simultaneously. Publish it once,
    # then reuse it without replacing a bundle that another process is executing.
    with (destination.parent / '.prepare.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _prepare_creator_cli_locked(source, contents, info_path, destination, worker, identity)


def _prepare_creator_cli_locked(source, contents, info_path, destination, worker, identity):
    try:
        if worker.is_file() and read_json(destination.parent / 'ready.json').get('identity') == identity:
            metadata = plistlib.loads((destination / 'Contents/Info.plist').read_bytes())
            if metadata.get('LSUIElement') is True: return worker
    except (OSError, ValueError, plistlib.InvalidFileException):
        pass
    with tempfile.TemporaryDirectory(prefix='prepare-', dir=destination.parent) as folder:
        prepared = Path(folder) / destination.name
        try:
            subprocess.run(['/bin/cp', '-cR', str(contents.parent), str(prepared)], check=True, capture_output=True, text=True, timeout=180)
        except (subprocess.SubprocessError, OSError) as error:
            raise BuildError('Không tạo được bản sao copy-on-write của Cocos để build ẩn. Chọn Creator trên ổ APFS có quyền đọc; tool không mở thêm tab editor.') from error
        target = prepared / 'Contents'
        info = plistlib.loads(info_path.read_bytes())
        info.update(LSUIElement=True, CFBundleExecutable=source.name)
        info.pop('CFBundleURLTypes', None)
        info.pop('LSBackgroundOnly', None)
        (target / 'Info.plist').write_bytes(plistlib.dumps(info))
        try:
            subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', '--timestamp=none', str(prepared)], check=True, capture_output=True, text=True, timeout=30)
        except (subprocess.SubprocessError, OSError) as error:
            raise BuildError('Không chuẩn bị được Cocos build worker ẩn; đã dừng để tránh mở thêm tab Cocos.') from error
        if destination.exists(): shutil.rmtree(destination)
        prepared.rename(destination)
        (destination.parent / 'ready.json').write_text(json.dumps({'identity': identity}))
    return worker


def creator_engine_arguments(creator):
    source = Path(creator).expanduser()
    if not source.is_file(): return []
    engine = source.parents[1] / 'Resources/resources/3d/engine'
    if not (engine / 'native').is_dir(): return []
    # Respect custom JS/native engine selections made in Creator Preferences.
    preferences = Path.home() / '.CocosCreator/profiles/v2/packages/engine.json'
    try:
        version = creator_version(str(source)).replace('.', '')
        selection = read_json(preferences).get('engine', {}).get(version, {})
    except (OSError, ValueError): return []
    if any(isinstance(value, dict) and value.get('builtin') is False for value in selection.values()): return []
    return ['--engine', str(engine)]


def android_export_fingerprint(root, config, creator):
    """Stable export inputs, including selected editor and engine source identity.

    Creator rewrites preferences and native templates even when unchanged. Hash
    these by content; retain cheap stat checks for large project assets.
    Compare this snapshot before/after export before marking the output reusable.
    """
    root = Path(root)
    digest = hashlib.sha256(b'android-export-v2' + json.dumps(config, sort_keys=True).encode())
    output = export_folder(root, config)
    ignored = {'.git', 'node_modules', 'build', '.gradle', '.cxx', '__pycache__', 'library', 'temp', '.cache'}

    def add_file(path, label, content=False):
        if not path.is_file(): return
        digest.update(str(label).encode() + b'\0')
        if content:
            digest.update(path.read_bytes())
        else:
            stamp = path.stat()
            digest.update(f'{path.resolve()}:{stamp.st_size}:{stamp.st_mtime_ns}:{stamp.st_ctime_ns}'.encode())
        digest.update(b'\0')

    def add_tree(base, label, content=False):
        for folder, dirs, files in os.walk(base):
            dirs[:] = sorted(d for d in dirs if d not in ignored and (Path(folder) / d).resolve() != output)
            for filename in sorted(files):
                if filename in ('.DS_Store', '.git'): continue
                path = Path(folder) / filename
                add_file(path, str(label) + '/' + str(path.relative_to(base)), content)

    for name in ('assets', 'settings', 'extensions', 'native-templates', 'profiles', 'build-templates', 'native'):
        add_tree(root / name, name, content=name in ('settings', 'profiles', 'native'))
    for name in ('package.json', 'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml'):
        add_file(root / name, name, content=True)
    executable = Path(creator).expanduser()
    digest.update(str(executable.resolve()).encode())
    add_file(executable, 'creator-executable')
    preferences = Path.home() / '.CocosCreator/profiles/v2/packages/engine.json'
    add_file(preferences, 'engine-preferences', content=True)
    if executable.is_file():
        contents = executable.parents[1]
        add_file(contents / 'Info.plist', 'creator-info', content=True)
        add_file(contents / 'Resources/app.asar', 'creator-resources')
        add_tree(contents / 'Resources/resources/3d/engine', 'builtin-engine')
        try:
            version = creator_version(str(executable)).replace('.', '')
            selection = read_json(preferences).get('engine', {}).get(version, {})
        except (OSError, ValueError): selection = {}
        for kind, value in sorted(selection.items()):
            if isinstance(value, dict) and value.get('builtin') is False:
                for key, path in sorted(value.items()):
                    if isinstance(path, str) and Path(path).expanduser().is_dir():
                        add_tree(Path(path).expanduser(), f'custom-engine/{kind}/{key}')
    return digest.hexdigest()


def write_if_changed(path, text):
    if not path.is_file() or path.read_text() != text:
        path.write_text(text)


class AndroidRunner:
    def __init__(self, tools, log, stage, java_selected=None):
        self.tools = {key: str(Path(value).expanduser()) if value and key in ('sdk', 'ndk', 'java', 'creator', 'studio') else value for key, value in tools.items()}
        self.log = log
        self.stage = stage
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.process = None
        self.monitoring = False
        self.logfile = None
        self.secrets = []
        self.java_selected = java_selected
        self.toolchain_lines = []

    def write(self, text):
        for secret in self.secrets:
            if secret:
                text = text.replace(str(secret), '***')
        text = re.sub(r'(?i)((?:password|xxteaKey|token)\s*[=:]\s*)[^\s,;]+', r'\1***', text)
        self.log(text)
        if self.logfile:
            self.logfile.write(text + '\n'); self.logfile.flush()

    def log_toolchain(self, options=None):
        """Report installed versions separately from declared project requirements."""
        options = options or {}
        sdk = Path(self.tools.get('sdk') or '/missing')
        ndk = Path(self.tools.get('ndk') or '/missing')
        apis = sorted((p.name.removeprefix('android-') for p in (sdk / 'platforms').glob('android-*') if p.is_dir()), key=version_key)
        ndks = sorted((p.name for p in (sdk / 'ndk').glob('*') if p.is_dir()), key=version_key)
        revision = ''
        try:
            match = re.search(r'^Pkg.Revision\s*=\s*(.+)$', (ndk / 'source.properties').read_text(), re.M)
            if match: revision = match[1].strip()
        except OSError: pass
        android = options.get('packages', {}).get('android', {})
        override = options.get('builderAndroid', {})
        lines = [
            f'SDK: {sdk}',
            'SDK API đã cài: ' + (', '.join(apis) + f' (từ {apis[0]} → {apis[-1]})' if apis else 'chưa cài'),
            f'Project: minSdk={override.get("minSdk") or "theo export Cocos"}; targetSdk={android.get("apiLevel") or "theo export Cocos"}; compileSdk={override.get("compileSdk") or "theo export Cocos"}',
            f'NDK đang chọn: {revision or (ndk.name if ndk.is_dir() else "chưa cài")} · {ndk}',
            'NDK đã cài: ' + (', '.join(ndks) + f' (từ {ndks[0]} → {ndks[-1]})' if ndks else 'chưa cài'),
            'Khoảng SDK/NDK ở trên là các bản đã cài; project không khai báo khoảng NDK tối thiểu/tối đa trong cấu hình tool.',
        ]
        self.toolchain_lines = ['[Android Tools] ' + line for line in lines]
        for line in self.toolchain_lines: self.write(line)

    def cancel(self):
        self.cancelled.set()
        with self.lock:
            if self.process and self.process.poll() is None:
                self._terminate(self.process)

    @staticmethod
    def _terminate(process):
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        def kill_later():
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
        threading.Thread(target=kill_later, daemon=True).start()

    def command_environment(self, args):
        tools = self.tools
        if Path(str(args[0])).name in ('sdkmanager', 'avdmanager') and java_major(tools.get('java', '')) < 17:
            homes = [home for home in discover_java_homes() if java_major(home) >= 17]
            if not homes:
                raise AndroidDependencyError(['Android SDK Command-line Tools cần JDK 17 trở lên. Cài JDK 17+ hoặc Android Studio mới có JDK đi kèm; JDK build của project vẫn được giữ riêng.'])
            tools = {**tools, 'java': homes[0]}
            self.write(f'Info: Dùng JDK {java_major(homes[0])} cho công cụ SDK; giữ JDK build riêng.')
        return android_environment(tools)

    def run(self, args, cwd=None, timeout=120, input_text=None, success_codes=(0,), announce=True, emit_output=True):
        if self.cancelled.is_set():
            raise BuildError('Đã dừng tác vụ Android.')
        if announce:
            self.write('$ ' + ' '.join(str(a) for a in args))
        env = self.command_environment(args)
        with self.lock:
            if self.cancelled.is_set():
                raise BuildError('Đã dừng tác vụ Android.')
            process = subprocess.Popen([str(a) for a in args], cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL, text=True, errors='replace', start_new_session=True, bufsize=1)
            self.process = process
        expired = threading.Event()
        def expire():
            expired.set(); self._terminate(process)
        timer = threading.Timer(timeout, expire) if timeout else None
        if timer: timer.start()
        output = deque(maxlen=20000)
        try:
            if input_text is not None:
                process.stdin.write(input_text); process.stdin.close()
            for line in process.stdout:
                line = line.rstrip('\r\n')
                output.append(line)
                if emit_output: self.write(line)
            code = process.wait()
        finally:
            process.stdout.close()
            if timer: timer.cancel()
            with self.lock: self.process = None
        if self.cancelled.is_set(): raise BuildError('Đã dừng tác vụ Android.')
        if expired.is_set(): raise BuildError('Lệnh Android quá thời gian; đã dừng tiến trình.')
        if code not in success_codes:
            raise BuildError(f'Lệnh Android thất bại (mã {code}); xem log phía trên.')
        return '\n'.join(output)

    def tool(self, name):
        path = sdk_tool(self.tools.get('sdk', ''), name)
        if not path.is_file():
            raise AndroidDependencyError([sdk_install_message(name)])
        return path

    def adb(self, serial, args, **kwargs):
        if not serial or serial.startswith('-'):
            raise BuildError('Chọn serial Android cụ thể trước khi thao tác.')
        return self.run([self.tool('adb'), '-s', serial, *args], **kwargs)

    def scan(self):
        return parse_devices(self.run([self.tool('adb'), 'devices', '-l'], timeout=20, announce=False))

    def list_targets(self, known_avds=None):
        devices = self.scan()
        for device in devices:
            if device['kind'] != 'emulator': continue
            avd = (known_avds or {}).get(device['serial'], '')
            if device['state'] == 'device':
                try:
                    name = self.adb(device['serial'], ['emu', 'avd', 'name'], timeout=5, announce=False, emit_output=False).splitlines()
                    if name: avd = name[0].strip()
                    booted = self.adb(device['serial'], ['shell', 'getprop', 'sys.boot_completed'], timeout=5, announce=False, emit_output=False).strip() == '1'
                    if not booted: device['state'] = 'booting'
                except BuildError:
                    device['state'] = 'offline'
            if avd: device['avd'] = avd
        names = []
        if sdk_tool(self.tools.get('sdk', ''), 'emulator').is_file():
            try: names = self.avds()
            except BuildError as error: self.write('Warning: Không đọc được danh sách AVD: ' + str(error))
        return merge_android_targets(names, devices)

    def require_target(self, selected, require_boot=True):
        if not selected:
            raise AndroidDeviceError('Chưa chọn thiết bị. Chọn máy ảo hoặc điện thoại trong dropdown trước khi Run.')
        targets = self.list_targets()
        if selected.get('serial'):
            target = next((d for d in targets if d.get('serial') and d['serial'] == selected.get('serial')), None)
            if target and selected.get('avd') and target.get('avd') != selected['avd']:
                target = None
        else:
            target = next((d for d in targets if d['id'] == selected.get('id')), None)
            if not target and selected.get('avd'):
                instances = [d for d in targets if d.get('avd') == selected['avd']]
                if len(instances) > 1:
                    raise AndroidDeviceError('Có nhiều phiên của AVD này. Chọn đúng serial trong dropdown trước khi Run.')
                target = instances[0] if instances else None
        name = selected.get('name') or selected.get('avd') or selected.get('serial', 'đã chọn')
        if not target:
            raise AndroidDeviceError(f'Không tìm thấy {name}. Kết nối lại đúng thiết bị đã chọn rồi thử lại.')
        state = target['state']
        if state == 'unauthorized':
            raise AndroidDeviceError(f'{name} chưa cho phép USB debugging. Mở khóa điện thoại và xác nhận RSA / Allow USB debugging.')
        if state == 'booting' and require_boot:
            raise AndroidDeviceError(f'{name} đang khởi động. Chờ boot xong; danh sách sẽ tự cập nhật, rồi bấm Build & Run lại.')
        if state not in (('device',) if require_boot else ('device', 'booting')) or not target.get('serial'):
            action = 'Bấm Mở AVD cho máy đang chọn và đợi boot xong.' if target['kind'] == 'emulator' else 'Cắm USB hoặc ghép đôi Wi-Fi và xác nhận USB debugging.'
            raise AndroidDeviceError(f'{name} chưa sẵn sàng ({state}). {action}')
        return target

    def avds(self):
        text = self.run([self.tool('emulator'), '-list-avds'], timeout=20, announce=False)
        return [line.strip() for line in text.splitlines() if re.fullmatch(r'[A-Za-z0-9_.-]+', line.strip())]

    def avd_catalog(self):
        sdk = Path(self.tools['sdk'])
        images = [';'.join(p.relative_to(sdk).parts[:-1]) for p in (sdk / 'system-images').glob('*/*/*/package.xml')]
        text = self.run([self.tool('avdmanager'), 'list', 'device', '-c'], timeout=30, announce=False)
        return {'images': sorted(images, key=version_key, reverse=True), 'devices': [line.strip() for line in text.splitlines() if re.fullmatch(r'[A-Za-z0-9_.-]+', line.strip())]}

    def create_avd(self, name, image, device):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', name):
            raise BuildError('Tên AVD chỉ gồm chữ, số, dấu chấm, gạch ngang hoặc gạch dưới.')
        catalog = self.avd_catalog()
        if image not in catalog['images'] or device not in catalog['devices']:
            raise BuildError('Chọn system image và model đã cài trong SDK.')
        if name in self.avds(): raise BuildError('Tên AVD đã tồn tại; chọn tên khác.')
        self.run([self.tool('avdmanager'), 'create', 'avd', '-n', name, '-k', image, '-d', device], input_text='no\n', timeout=90)
        return name

    def start_avd(self, name):
        if name not in self.avds(): raise BuildError('AVD không còn tồn tại. Refresh lại.')
        existing = next((d for d in self.list_targets() if d.get('avd') == name and d.get('serial')), None)
        if existing:
            return f'{name} đã được mở; tool đang tự theo dõi trạng thái khởi động.'
        # emulator must outlive this short worker; never pipe an unread long-lived stdout.
        log = Path.home() / 'Library/Logs/Cocos Android Builder'
        log.mkdir(parents=True, exist_ok=True)
        with (log / 'emulator.log').open('a') as stream:
            subprocess.Popen([str(self.tool('emulator')), '-avd', name], env=android_environment(self.tools), stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        return f'Đã yêu cầu mở {name}; tool sẽ tự cập nhật khi Android khởi động xong.'

    def delete_avd(self, name):
        for device in self.scan():
            if device['kind'] == 'emulator' and device['state'] != 'device':
                raise AndroidDeviceError('Có máy ảo đang khởi động hoặc offline. Đợi ADB kết nối và tắt máy ảo trước khi xóa AVD.')
            if device['kind'] == 'emulator' and device['state'] == 'device':
                running = self.adb(device['serial'], ['emu', 'avd', 'name'], timeout=10).splitlines()
                if name in running: raise BuildError('Tắt AVD đang chạy trước khi xóa.')
        if name not in self.avds(): raise BuildError('AVD không còn tồn tại.')
        self.run([self.tool('avdmanager'), 'delete', 'avd', '-n', name], timeout=30)
        return f'Đã xóa AVD {name}.'

    def wireless(self, address, code=None):
        if not re.fullmatch(r'[A-Za-z0-9._-]+:\d{1,5}', address):
            raise BuildError('Nhập địa chỉ host:port từ Wireless debugging trên điện thoại.')
        args = [self.tool('adb'), 'pair' if code is not None else 'connect', address]
        if code is not None:
            if not re.fullmatch(r'\d{6}', code): raise BuildError('Mã ghép đôi phải có 6 chữ số.')
            self.secrets.append(code)
        result = self.run(args, input_text=code + '\n' if code else None, timeout=30)
        if not re.search(r'successfully paired|connected to|already connected', result, re.I):
            raise BuildError('Chưa kết nối được Android. Kiểm tra địa chỉ/cổng và mã ghép đôi trong log.')
        return 'Đã ghép đôi. Dùng Connect với cổng kết nối.' if code else 'Đã kết nối Android qua Wi-Fi.'

    def validate_gradle_java(self, proj):
        wrapper = proj / 'gradle/wrapper/gradle-wrapper.properties'
        text = wrapper.read_text() if wrapper.is_file() else ''
        version = re.search(r'gradle-(\d+)\.(\d+)', text)
        major = java_major(self.tools.get('java', ''))
        if not version or not major:
            raise AndroidDependencyError(['Không xác định được phiên bản Gradle/JDK. Chọn Java Home của JDK đã cài hoặc cài JDK phù hợp với Gradle của project.'])
        gradle = (int(version[1]), int(version[2]))
        minimum_gradle = {8: (2, 0), 9: (4, 3), 10: (4, 7), 11: (5, 0), 12: (5, 4), 13: (6, 0), 14: (6, 3), 15: (6, 7), 16: (7, 0), 17: (7, 3), 18: (7, 5), 19: (7, 6), 20: (8, 3), 21: (8, 5), 22: (8, 8), 23: (8, 10), 24: (8, 14), 25: (9, 1)}
        required = max((v for k, v in minimum_gradle.items() if major >= k), default=(0, 0))
        build_file = proj / 'build.gradle'
        plugin = re.search(r'com.android.tools.build:gradle:(\d+)', build_file.read_text() if build_file.is_file() else '')
        min_java = 17 if plugin and int(plugin[1]) >= 8 else 11 if plugin and int(plugin[1]) >= 7 else 8
        if gradle < required or major < min_java or (gradle >= (9, 0) and major < 17):
            raise AndroidDependencyError([f'JDK {major} không phù hợp Gradle {version[1]}.{version[2]}. Chọn JDK tương thích trong Công cụ Android → JDK đã cài, hoặc cài JDK phù hợp (Cocos 3.7.x thường dùng JDK 11).'])

    def ensure_gradle_java(self, proj):
        try:
            self.validate_gradle_java(proj)
            return
        except AndroidDependencyError as original:
            previous = self.tools.get('java', '')
            for home in discover_java_homes():
                if home == previous: continue
                self.tools['java'] = home
                try: self.validate_gradle_java(proj)
                except AndroidDependencyError: continue
                self.write(f'Info: Tự chọn JDK {java_major(home)} tương thích Gradle: {home}')
                if self.java_selected: self.java_selected(home)
                return
            self.tools['java'] = previous
            raise original

    def build_apk(self, root, options, native_only=False, force_export=False):
        started = time.monotonic()
        root = Path(root)
        if not self.toolchain_lines: self.log_toolchain(options)
        info = inspect_android_project(root)
        if not (Path(self.tools.get('java') or '/missing') / 'bin/java').is_file():
            homes = discover_java_homes()
            if homes:
                self.tools['java'] = homes[0]
                self.write(f'Info: Tự chọn JDK đã cài: {homes[0]}')
                if self.java_selected: self.java_selected(homes[0])
        issues = check_android_tools(self.tools, info['version'])
        error = validate_android_options(options)
        if issues: raise AndroidDependencyError(issues)
        if error: raise BuildError(error)
        config = make_android_config(options, self.tools, options['packages']['android']['packageName'])
        self.secrets += [v for p in config.get('packages', {}).values() if isinstance(p, dict) for k, v in p.items() if SECRET.search(k) and isinstance(v, str)]
        exported = export_folder(root, config)
        exported.mkdir(parents=True, exist_ok=True)
        marker = exported / '.android-builder-apk.json'
        with (exported / '.android-builder.lock').open('a') as lock:
            try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: raise BuildError('Output Android đang được build bởi phiên khác.')
            if native_only and read_json(marker).get('fingerprint') != input_fingerprint(root, config):
                raise BuildError('Asset/script/cấu hình đã đổi hoặc chưa có bản build khớp. Tắt chỉ build Gradle để export lại Cocos.')
            export_marker = exported / '.android-builder-export.json'
            export_config = copy.deepcopy(config)
            export_config.pop('builderAndroid', None)
            fingerprint = android_export_fingerprint(root, export_config, self.tools['creator'])
            try: baseline = read_json(export_marker)
            except (OSError, ValueError): baseline = {}
            cached = (not force_export and baseline.get('fingerprint') == fingerprint and (exported / 'proj/gradlew').is_file())
            marker.unlink(missing_ok=True)
            logs = root / 'build/android-builder/logs'; logs.mkdir(parents=True, exist_ok=True)
            with (logs / (dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.log')).open('w') as logfile:
                self.logfile = logfile
                try:
                    self.write('Log Android: ' + str(logfile.name))
                    for line in self.toolchain_lines: self.write(line)
                    reason = 'buộc export lại' if force_export else 'đầu vào/Creator thay đổi, output thiếu hoặc chưa có cache'
                    self.write('Cache Cocos: ' + ('HIT · bỏ qua export Android' if cached else 'MISS · ' + reason))
                    if not native_only and not cached:
                        export_marker.unlink(missing_ok=True)
                        export_started = time.monotonic()
                        self.stage('1/3 · Cocos: xuất project Android')
                        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', prefix='cocos-android-', delete=False) as temporary:
                            creator_config = copy.deepcopy(config)
                            creator_config.pop('builderAndroid', None)
                            json.dump(creator_config, temporary); config_path = Path(temporary.name)
                        try:
                            creator_cli = prepare_creator_cli(self.tools['creator'])
                            self.write('Cocos CLI: worker ẩn · không mở thêm cửa sổ / Dock tab')
                            self.run([str(creator_cli), '--nologin', *creator_engine_arguments(self.tools['creator']), '--project', root, '--build', f'configPath={config_path}'], cwd=root, timeout=1800, success_codes=(0, 36))
                        finally:
                            config_path.unlink(missing_ok=True)
                            self.write(f'Thời gian Cocos export: {time.monotonic() - export_started:.1f}s')
                        if (exported / 'proj/gradlew').is_file() and fingerprint == android_export_fingerprint(root, export_config, self.tools['creator']):
                            export_marker.write_text(json.dumps({'fingerprint': fingerprint}))
                        else:
                            self.write('Warning: Không ghi cache export vì đầu vào đã đổi trong lúc export hoặc output chưa đầy đủ; lần sau sẽ xuất lại.')
                    else:
                        self.stage('1/3 · Dùng bản xuất Cocos Android đã có')
                        self.write('Thời gian Cocos export: 0.0s · dùng output hiện có')
                    proj = exported / 'proj'
                    if not (proj / 'gradlew').is_file(): raise BuildError(f'Chưa có Gradle wrapper tại {proj}. Xuất Cocos Android trước.')
                    self.ensure_gradle_java(proj)
                    local = proj / 'local.properties'
                    text = local.read_text() if local.is_file() else ''
                    text = re.sub(r'^sdk\.dir=.*\n?', '', text, flags=re.M)
                    sdk_path = str(Path(self.tools['sdk']).expanduser()).replace('\\', '\\\\').replace(':', '\\:')
                    write_if_changed(local, text.rstrip() + '\nsdk.dir=' + sdk_path + '\n')
                    self.stage('2/3 · Gradle: build APK')
                    variant = 'debug' if config.get('debug', True) else 'release'
                    # Cocos 3.x uses named application modules, so assemble the selected
                    # variant through the wrapper instead of hardcoding :app.
                    args = ['/bin/sh', str(proj / 'gradlew'), 'assemble' + variant.title(), '--console=plain', '--daemon', '--build-cache', f'-PPROP_NDK_PATH={self.tools["ndk"]}', f'-Dorg.gradle.java.home={self.tools["java"]}']
                    # Apply optional application metadata without editing native templates.
                    init = exported / '.android-builder-gradle.gradle'
                    write_if_changed(init, gradle_override_script(config.get('builderAndroid', {})))
                    self.write('Cache Gradle: giữ output incremental · bật build cache và tái sử dụng daemon JDK tương thích')
                    gradle_started = time.monotonic()
                    try:
                        self.run([*args, '--init-script', init], cwd=proj, timeout=3600)
                    finally:
                        self.write(f'Thời gian Gradle: {time.monotonic() - gradle_started:.1f}s')
                    apk = select_apk(exported, variant)
                    metadata = self.apk_metadata(apk)
                    if metadata['package'] != config['packages']['android']['packageName']:
                        raise BuildError('Package ID trong APK không khớp cấu hình. Export lại Cocos.')
                    record = {'apk': str(apk.resolve()), 'sha256': apk_hash(apk), 'package': metadata['package'], 'variant': variant, 'config': strip_secrets(config), 'fingerprint': input_fingerprint(root, config)}
                    marker.write_text(json.dumps(record, indent=2))
                    self.stage('APK đã build thành công')
                    return str(apk)
                finally:
                    self.write(f'Thời gian Android tổng: {time.monotonic() - started:.1f}s')
                    self.logfile = None

    def existing_apk(self, root, options):
        config = make_android_config(options, self.tools, options.get('packages', {}).get('android', {}).get('packageName', ''))
        exported = export_folder(Path(root), config)
        record = read_json(exported / '.android-builder-apk.json')
        apk = Path(record.get('apk') or '/missing')
        if not apk.is_file() or not apk.is_relative_to(exported) or record.get('sha256') != apk_hash(apk):
            raise BuildError('Chưa có APK hợp lệ từ lần build thành công. Bấm Build APK hoặc chọn APK thủ công.')
        if record.get('config') != strip_secrets(config):
            raise BuildError('Cấu hình đã thay đổi so với APK. Build lại hoặc chọn APK thủ công.')
        if record.get('fingerprint') != input_fingerprint(Path(root), config):
            raise BuildError('Asset/script đã thay đổi từ lần build APK. Build lại hoặc chọn APK cũ thủ công nếu muốn chạy bản cũ.')
        return str(apk)

    def apk_metadata(self, apk):
        if not Path(apk).is_file(): raise BuildError('Không tìm thấy APK.')
        self.run([self.tool('apksigner'), 'verify', apk], timeout=60)
        return parse_badging(self.run([self.tool('aapt'), 'dump', 'badging', apk], timeout=60))

    def install_run(self, apk, serial, package, clean=False):
        if not self.toolchain_lines: self.log_toolchain()
        metadata = self.apk_metadata(apk)
        if metadata['package'] != package: raise BuildError('Package ID APK không khớp ứng dụng đã chọn.')
        devices = self.scan()
        if not any(d['serial'] == serial and d['state'] == 'device' for d in devices):
            raise BuildError('Thiết bị chưa sẵn sàng. Bật USB debugging, xác nhận RSA trên điện thoại rồi Refresh.')
        abis = self.adb(serial, ['shell', 'getprop', 'ro.product.cpu.abilist'], timeout=15).strip().split(',')
        if metadata['abis'] and not set(abis).intersection(metadata['abis']):
            raise BuildError(f'APK ABI {metadata["abis"]} không phù hợp thiết bị {abis}. Chọn lại ABI rồi build.')
        api = self.adb(serial, ['shell', 'getprop', 'ro.build.version.sdk'], timeout=15).strip()
        if not api.isdigit() or int(api) < metadata['minSdk']: raise BuildError('Android trên thiết bị thấp hơn minSdk của APK.')
        if clean:
            self.stage('Xóa dữ liệu app trên thiết bị đã chọn')
            installed = self.adb(serial, ['shell', 'pm', 'path', package], timeout=20)
            if 'package:' in installed:
                self.adb(serial, ['uninstall', package], timeout=60)
        self.stage('3/3 · Cài APK và chạy Android')
        installed = self.adb(serial, ['install', '-r', apk], timeout=180)
        if 'Success' not in installed: raise BuildError('adb chưa xác nhận cài APK thành công.')
        resolved = self.adb(serial, ['shell', 'cmd', 'package', 'resolve-activity', '--brief', '-a', 'android.intent.action.MAIN', '-c', 'android.intent.category.LAUNCHER', package], timeout=20)
        component = next((line.strip() for line in reversed(resolved.splitlines()) if re.fullmatch(r'[A-Za-z0-9_.$]+/[A-Za-z0-9_.$]+', line.strip())), '')
        if not component or not component.startswith(package + '/'):
            raise BuildError('Không tìm được launcher activity của ứng dụng đã cài.')
        output = self.adb(serial, ['shell', 'am', 'start', '-W', '-n', component], timeout=60)
        if re.search(r'Error:|Exception|Status:\s*(?!ok\b)\S+', output): raise BuildError('Android chưa xác nhận launch thành công; xem log.')
        if 'Status: ok' not in output and 'brought to the front' not in output: raise BuildError('Chưa xác nhận được trạng thái launch Android.')
        self.stage('Android đã cài và launch · Logcat ghi vào bảng log chung')
        return str(apk)

    def device_time(self, serial):
        # adb shell joins its arguments again on the device. Preserve the space
        # inside date's format string as one remote-shell argument.
        value = self.adb(serial, ['shell', 'date', "'+%m-%d %H:%M:%S.000'"], timeout=10, announce=False, emit_output=False).strip()
        if not re.fullmatch(r'\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}', value):
            raise BuildError('Không đọc được thời gian thiết bị để bắt đầu Logcat.')
        return value

    def logcat(self, serial, package=''):
        if package and not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+', package): raise BuildError('Nhập Package ID hợp lệ để xem Logcat.')
        since = self.device_time(serial)
        self.monitoring = True
        self.stage('Đang thu Logcat vào bảng log chung')
        last_pid = None
        seen = deque(maxlen=10000)
        seen_set = set()
        try:
            while not self.cancelled.is_set():
                if package:
                    pid = self.adb(serial, ['shell', 'pidof', package], timeout=10, success_codes=(0, 1), announce=False, emit_output=False).strip().split()
                    current = pid[0] if pid and pid[0].isdigit() else ''
                else:
                    current = '*'
                if current != last_pid:
                    self.write(('Logcat: thiết bị ' + serial if current == '*' else 'Logcat: PID ' + current) if current else 'Warning: App chưa chạy; đang chờ process Android…')
                    last_pid = current
                if current:
                    next_since = self.device_time(serial)
                    args = ['logcat', '-d', '-v', 'threadtime', '-T', since]
                    if package: args.append('--pid=' + current)
                    text = self.adb(serial, args, timeout=20, announce=False, emit_output=False)
                    for line in text.splitlines():
                        identity = (current, line)
                        if identity not in seen_set:
                            if len(seen) == seen.maxlen: seen_set.discard(seen[0])
                            seen.append(identity); seen_set.add(identity); self.write(line)
                    since = next_since
                self.cancelled.wait(1)
        finally:
            self.monitoring = False
