"""Build a self-contained Apple Silicon .app and a double-clickable macOS installer."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import tempfile
import tomllib
from xml.sax.saxutils import escape
from release_info import APP_NAME, VERSION, BUNDLE_ID, MIN_MACOS
import setup_tool

SOURCE = Path(__file__).resolve().parent
DIST = SOURCE / "dist"


def run(*args):
    subprocess.run([str(a) for a in args], check=True)


def load_config(path, profile):
    if profile not in ('distribution', 'development'):
        raise ValueError('Unknown release profile')
    config = tomllib.loads(Path(path).read_text())[profile]
    if profile == 'distribution':
        for key, prefix in (('application_identity', 'Developer ID Application:'),
                            ('installer_identity', 'Developer ID Installer:'),
                            ('notary_profile', '')):
            value = config.get(key, '').strip()
            if not value or not value.startswith(prefix):
                raise ValueError(f'Configure {key} in {path}; distribution requires Developer ID and notarization.')
    return config


def preflight(config, profile):
    if profile == 'development':
        return
    identities = subprocess.run(['/usr/bin/security', 'find-identity', '-v'],
                                check=True, capture_output=True, text=True).stdout
    for key in ('application_identity', 'installer_identity'):
        if config[key] not in identities:
            raise ValueError(f'Missing signing identity in Keychain: {config[key]}')
    # Confirm the Keychain profile works before the expensive packaging step.
    run('/usr/bin/xcrun', 'notarytool', 'history', '--keychain-profile', config['notary_profile'])


def signing_targets(app):
    magic = {bytes.fromhex(value) for value in
             ('feedface', 'cefaedfe', 'feedfacf', 'cffaedfe', 'cafebabe', 'bebafeca', 'cafebabf', 'bfbafeca')}
    targets = []
    for path in app.rglob('*'):
        if path.is_symlink():
            continue
        if path.is_dir() and path.suffix in ('.framework', '.app', '.xpc', '.bundle'):
            # Resource-only bundles have no executable to sign.
            info = next((p for p in (path / 'Contents/Info.plist', path / 'Resources/Info.plist',
                                    path / 'Info.plist', path / 'Versions/Current/Resources/Info.plist')
                         if p.is_file()), None)
            if path.suffix == '.framework' or (info and plistlib.loads(info.read_bytes()).get('CFBundleExecutable')):
                targets.append(path)
        elif path.is_file():
            with path.open('rb') as stream:
                if stream.read(4) in magic:
                    targets.append(path)
    return sorted(targets, key=lambda p: (-len(p.parts), str(p))) + [app]


def notarize(package, profile):
    result = subprocess.run(['/usr/bin/xcrun', 'notarytool', 'submit', str(package),
                             '--keychain-profile', profile, '--wait', '--output-format', 'json'],
                            check=True, capture_output=True, text=True)
    report = json.loads(result.stdout)
    if report.get('status') != 'Accepted':
        raise RuntimeError(f'Notarization {report.get("status")}; inspect with xcrun notarytool log '
                           f'{report.get("id")} --keychain-profile {profile}')
    run('/usr/bin/xcrun', 'stapler', 'staple', package)
    run('/usr/bin/xcrun', 'stapler', 'validate', package)
    run('/usr/sbin/spctl', '--assess', '--type', 'install', '--verbose=2', package)


def distribution_xml():
    return f'''<?xml version="1.0" encoding="utf-8"?>
<installer-gui-script minSpecVersion="2">
<title>{escape(APP_NAME)} {escape(VERSION)}</title>
<welcome file="welcome.html"/>
<options customize="never" require-scripts="false" hostArchitectures="arm64"/>
<allowed-os-versions><os-version min="{MIN_MACOS}"/></allowed-os-versions>
<domains enable_localSystem="true" enable_currentUserHome="false" enable_anywhere="false"/>
<choices-outline><line choice="main"/></choices-outline>
<choice id="main" visible="false"><pkg-ref id="{BUNDLE_ID}"/></choice>
<pkg-ref id="{BUNDLE_ID}" version="{VERSION}" auth="root" onConclusion="none">component.pkg</pkg-ref>
</installer-gui-script>'''


def build(config_path=SOURCE / 'release-build.toml', profile='distribution', check=False):
    config = load_config(config_path, profile)
    preflight(config, profile)
    if check:
        print(f'Release configuration OK: {profile}')
        return
    output_app = DIST / f'{APP_NAME}.app'
    backup = DIST / f'{APP_NAME}-{VERSION}-previous.app'
    if output_app.exists() and backup.exists():
        raise RuntimeError(f'Keep existing backup before rebuilding: {backup}')
    setup_tool.setup()
    DIST.mkdir(exist_ok=True)
    installers = SOURCE / "build"
    installers.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cocos-builder-release-") as temporary:
        work = Path(temporary)
        app = work / "payload/Applications" / f"{APP_NAME}.app"
        resources = app / "Contents/Resources"
        shutil.copytree(setup_tool.APP, app, symlinks=True)
        python = next((SOURCE / ".runtime/python").glob("cpython-3.15.*-macos-aarch64-none"))
        print("Bundling Python runtime and Qt…", flush=True)
        shutil.copytree(python, resources / "python", symlinks=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        packages = SOURCE / ".runtime/venv/lib/python3.15/site-packages"
        shutil.copytree(packages, resources / "site-packages", symlinks=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        launcher = app / "Contents/MacOS/CocosBuilder"
        # A native main executable supports a proper Developer ID signature.
        launcher.unlink()
        run('/usr/bin/xcrun', 'clang', '-arch', 'arm64', f'-mmacosx-version-min={MIN_MACOS}',
            '-O2', '-Wall', '-Wextra', '-Werror', SOURCE / 'release_launcher.c', '-o', launcher)
        launcher.chmod(0o755)
        print("Verifying embedded runtime…", flush=True)
        env = os.environ.copy()
        env.update(PYTHONHOME=str(resources / "python"), PYTHONPATH=str(resources / "site-packages"),
                   PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1", QT_QPA_PLATFORM="offscreen")
        subprocess.run([str(resources / "python/bin/python3.15"), "-c",
                        "import sys, qrcode; from PySide6.QtWidgets import QApplication; "
                        "a=QApplication([]); print('Embedded Python/Qt:', sys.version.split()[0])"],
                       env=env, check=True)
        print(f'Signing app ({profile})…', flush=True)
        identity = config['application_identity'] if profile == 'distribution' else '-'
        options = ('--timestamp', '--options', 'runtime') if profile == 'distribution' else ('--timestamp=none',)
        for target in signing_targets(app):
            run('/usr/bin/codesign', '--force', '--sign', identity, *options, target)
        run("/usr/bin/codesign", "--verify", "--deep", "--strict", app)
        components = work / "components.plist"
        run("/usr/bin/pkgbuild", "--analyze", "--root", work / "payload", components)
        config = plistlib.loads(components.read_bytes())
        for item in config:
            item["BundleIsRelocatable"] = False
            item["BundleIsVersionChecked"] = True
        components.write_bytes(plistlib.dumps(config))
        component = work / "component.pkg"
        run("/usr/bin/pkgbuild", "--root", work / "payload", "--component-plist", components,
            "--identifier", BUNDLE_ID, "--version", VERSION, "--install-location", "/",
            "--ownership", "recommended", component)
        welcome = work / "welcome.html"
        welcome.write_text(f'''<html><body style="font-family:-apple-system;padding:18px">
<h1>{APP_NAME} {VERSION}</h1><p>Build and run Cocos iOS and Android apps from one desktop tool.</p>
<p>Installs into <b>/Applications/{APP_NAME}.app</b>.</p>
<p>macOS Installer will request administrator authorization when required.</p>
<p>Apple Silicon Mac · macOS {MIN_MACOS} or newer.<br>Python and Qt are included.</p>
<p>Install your project's Cocos Creator version separately. iOS needs Xcode and a compatible runtime; Android needs Studio, SDK, NDK and JDK.</p>
</body></html>''')
        distribution = work / "distribution.xml"
        distribution.write_text(distribution_xml())
        suffix = '' if profile == 'distribution' else '-development'
        package = work / f"cocos-builder-{VERSION}-macOS-arm64{suffix}.pkg"
        print("Creating installer…", flush=True)
        signing = ('--sign', config['installer_identity'], '--timestamp') if profile == 'distribution' else ()
        run("/usr/bin/productbuild", "--distribution", distribution, "--resources", work,
            "--package-path", work, *signing, package)
        if profile == 'distribution':
            run('/usr/sbin/pkgutil', '--check-signature', package)
            notarize(package, config['notary_profile'])
        final_package = installers / package.name
        if final_package.exists():
            raise RuntimeError(f'Installer already exists; preserve it before rebuilding: {final_package}')
        shutil.move(str(package), final_package)
        package = final_package
        if output_app.exists():
            if backup.exists():
                raise RuntimeError(f"Keep existing backup before rebuilding: {backup}")
            output_app.rename(backup)
        shutil.move(str(app), output_app)
        with package.open('rb') as stream:
            checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
        (installers / (package.name + ".sha256")).write_text(checksum + "  " + package.name + "\n")
        (DIST / "release.json").write_text(json.dumps({"name": APP_NAME, "version": VERSION,
            "architecture": "arm64", "minimumMacOS": MIN_MACOS, "installer": package.name,
            "sha256": checksum, "profile": profile, "administratorAuthorization": True,
            "signing": "Developer ID; notarized and stapled installer" if profile == 'distribution'
                       else "ad-hoc app; installer not notarized"}, indent=2))
        print(f"INSTALLER_READY: {package}\nAPP_READY: {output_app}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=SOURCE / 'release-build.toml')
    parser.add_argument('--profile', choices=('distribution', 'development'), default='distribution')
    parser.add_argument('--check', action='store_true', help='Validate configuration and credentials only')
    args = parser.parse_args()
    try:
        build(args.config, args.profile, args.check)
    except (ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'Release build stopped: {error}\n')
