"""Install a local Python 3.15 environment and create a double-clickable macOS app."""
import os
from pathlib import Path
import plistlib
import shlex
import shutil
import subprocess
import sys
from release_info import APP_NAME, VERSION, BUNDLE_ID, MIN_MACOS

SOURCE = Path(__file__).resolve().parent
OUTPUT = SOURCE / ".runtime"
PYTHON_HOME = OUTPUT / "python"
VENV = OUTPUT / "venv"
APP = SOURCE / f"{APP_NAME}.app"


def setup():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    interpreter = VENV / "bin/python"
    ready = False
    if interpreter.exists():
        ready = subprocess.run([str(interpreter), "-c",
            "import sys; from PySide6 import QtWidgets; assert sys.version_info[:2] == (3, 15)"],
            capture_output=True).returncode == 0
    if not ready:
        bootstrap = OUTPUT / "bootstrap"
        uv = bootstrap / "bin/uv"
        if not uv.exists():
            subprocess.run([sys.executable, "-m", "pip", "install", "--target", str(bootstrap), "uv"], check=True)
        env = os.environ.copy()
        env["UV_PYTHON_INSTALL_DIR"] = str(PYTHON_HOME)
        env["UV_CACHE_DIR"] = str(OUTPUT / "cache")
        subprocess.run([str(uv), "python", "install", "3.15", "--no-bin"], env=env, check=True)
        subprocess.run([str(uv), "venv", "--python", "3.15", str(VENV)], env=env, check=True)
        subprocess.run([str(uv), "pip", "install", "--python", str(interpreter),
                        "-r", str(SOURCE / "requirements.txt")], env=env, check=True)
    contents = APP / "Contents"
    resources, executables = contents / "Resources", contents / "MacOS"
    resources.mkdir(parents=True, exist_ok=True)
    executables.mkdir(exist_ok=True)
    for filename in ("app.py", "backend.py", "diagnostics.py", "crash_panel.py", "project_config.py", "autorotate.py", "build_config_panel.py", "release_info.py", "app-icon.png", "app-icon.icns", "arrow.svg", "icon-refresh.svg", "icon-reload.svg", "icon-create.svg", "icon-delete.svg", "icon-open.svg", "icon-power.svg"):
        shutil.copy2(SOURCE / filename, resources / filename)
    launcher = executables / "CocosBuilder"
    launcher.write_text('#!/bin/bash\nset -e\n' +
        f'exec {shlex.quote(str(interpreter))} "$(dirname "$0")/../Resources/app.py" "$@"\n')
    launcher.chmod(0o755)
    info = {"CFBundleName": APP_NAME, "CFBundleDisplayName": APP_NAME,
            "CFBundleIdentifier": BUNDLE_ID, "CFBundleVersion": VERSION,
            "CFBundleShortVersionString": VERSION, "CFBundleIconFile": "app-icon.icns", "CFBundlePackageType": "APPL",
            "CFBundleExecutable": "CocosBuilder", "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": MIN_MACOS}
    (contents / "Info.plist").write_bytes(plistlib.dumps(info))
    print(f"Ready: {APP}")
    return APP


if __name__ == "__main__":
    path = setup()
    if "--launch" in sys.argv:
        subprocess.run([str(path / "Contents/MacOS/CocosBuilder")], check=True)
