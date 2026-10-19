# Cocos iOS Builder

A macOS desktop tool for exporting, building, installing, and running Cocos
Creator 3.x iOS projects using Cocos CLI and Xcode command-line tools.

**Current version: 1.0.1.** The available development installer is ad-hoc signed,
not Developer ID signed or notarized. macOS Gatekeeper may block it on another
Mac. Signed distribution requires the release setup described below.

## Supported platforms and features

| Area | Support |
| --- | --- |
| Mac hardware | Apple Silicon, arm64 (M-series Macs) |
| macOS | 14.4 or newer for the packaged app; Xcode can require a newer macOS |
| Cocos projects | Creator 3.x projects with an existing iOS build task; the main compatibility work targets 3.7.x |
| iOS destinations | Physical iPhones and compatible installed iOS Simulator runtimes |
| Build modes | Debug and Release; build only, build and run, run existing build, clean and run |
| Export speed | Reuse an existing native output and skip Cocos export when tracked inputs are unchanged |
| Simulator management | Create, list, boot, show, shut down, restart, and delete selected simulators |
| Logs | Build logs; independent Simulator log observation; text and severity filters |
| Crash reports | Read Apple `.ips` reports; resolve native frames when matching local symbols exist |
| Configuration | Project/task-specific options, scenes, orientations, native script encryption, Team ID, and Bundle ID |

Not supported: Mac Intel installers, Windows/Linux hosts, Cocos Creator 2.x,
Android builds, App Store/TestFlight upload, universal Mac binaries, or automatic
installation of Xcode/Cocos/runtimes. Accepting a Creator 3.x project does not
guarantee that every engine version, extension, or custom native template works.
The app interface is currently primarily Vietnamese; the documentation is English.

## Download and install

The public download repository is separate from this private source repository.
Version 1.0.1 is distributed directly from the **`dowload-v101`** branch using
Git LFS, without a Release or version tag.

- [Download page and installation instructions](https://github.com/sulong-729/cocos-ios-builder-download/tree/dowload-v101)
- [Download the PKG](https://media.githubusercontent.com/media/sulong-729/cocos-ios-builder-download/dowload-v101/cocos-builder-1.0.1-macOS-arm64-development.pkg)
- [Public English User Guide](https://github.com/sulong-729/cocos-ios-builder-download/blob/dowload-v101/USER_GUIDE.md)

1. Confirm that your Mac has Apple Silicon and macOS 14.4 or newer.
2. Download the newest `.pkg` and its `.sha256` file together.
3. Verify the checksum as described in the [User Guide](docs/USER_GUIDE.md).
4. Open the `.pkg`, follow macOS Installer, and authorize installation when asked.
5. Launch **cocos builder** from `/Applications`.

Python 3.15 and Qt/PySide6 are included in the installer. Xcode, Cocos Creator,
and iOS Simulator runtimes are separate prerequisites. Installing the tool does
not configure your Apple development signing account.

## First build

1. Open Xcode once, finish setup, select its Command Line Tools, and install the
   required iOS runtime if using Simulator.
2. Install the exact Cocos Creator version specified in your project's
   `package.json` under `creator.version`.
3. Create and save an iOS build task in Cocos Creator at least once.
4. Open the tool and choose or drop the Cocos project root.
5. Open **Cài đặt** (Settings), select the saved iOS task, set the Bundle ID and
   Apple Team ID for a physical device, and check the build options.
6. Choose a compatible Simulator or connected iPhone.
7. Click **Build & Run**.

If the game is already installed, normal Run/Build & Run preserves the installed
copy. To deploy the newest build over an existing installation, use **Clean &
Run** after building; it uninstalls the selected app and deletes its device data
on the selected device after confirmation. See the guide before using it.

## Documentation

- [Detailed User Guide](docs/USER_GUIDE.md): installation, prerequisites, UI,
  build/run behavior, cache, logs, crash reports, and troubleshooting.
- [Development Guide](docs/DEVELOPMENT.md): source setup, tests, repository
  boundaries, and the `main`/`dev` workflow.
- [Release Guide](docs/RELEASE.md): signed packaging, notarization, administrator
  authorization, publishing, and keeping only the newest download.
- [Release notes](RELEASE-1.0.1.md): changes and validation limits for this version.

## Run from source

```sh
./Launch.command
```

The first run downloads a project-local Python 3.15 environment and installs
the pinned Qt dependency under `.runtime/`. Internet access is needed for this
setup. It does not replace the system Python.

Run the automated tests from the repository root:

```sh
QT_QPA_PLATFORM=offscreen .runtime/venv/bin/python -m unittest discover -s . -p 'test_*.py' -v
```

## Source and downloads

The source repository remains **private**, with `main` for the release baseline
and `dev` for ongoing changes. The separate public download repository contains
the latest installer, checksum, Git LFS configuration, and user documentation on
`dowload-v101`. Do not publish Releases or version tags for these downloads.

Repository visibility applies to the whole repository, not individual branches.
A separate download repository prevents source history from being pushed with
the downloads. The packaged Python app itself includes Python modules; a private
source repository does not prevent recipients from extracting code from the app.

The newest build is the only supported download. Previous generated installers
and app backups are excluded from source control and removed after the newest
installer has been verified. Publishing and cleanup steps are in the Release Guide.
