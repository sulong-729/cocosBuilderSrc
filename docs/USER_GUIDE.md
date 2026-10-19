# Cocos iOS Builder — User Guide

This guide covers version **1.0.1**. The UI is primarily Vietnamese; the
instructions below pair the visible labels with English explanations.

## 1. What the tool does

Cocos iOS Builder runs the normal Cocos and Apple build tools from a desktop UI:

1. Inspect a Cocos Creator project's saved iOS build configuration.
2. Export the iOS native project using the matching Cocos Creator CLI.
3. Apply the tool's compatibility and signing settings to generated output.
4. Compile the `*-mobile` application scheme using `xcodebuild`.
5. Optionally install and launch the app on the selected Simulator or iPhone.

It can also run a compatible existing build, observe Simulator logs, manage
Simulator devices, and inspect native crash reports. It does not replace Xcode
for signing setup, provisioning, native debugging, or distribution to Apple.

## 2. Compatibility and requirements

| Requirement | Details |
| --- | --- |
| Mac CPU | Apple Silicon arm64, including M-series Macs |
| macOS | 14.4 or newer for the bundled Qt app; the chosen Xcode may require a newer macOS |
| Packaged runtime | Python 3.15 and PySide6-Essentials 6.12.0 are included |
| Xcode | Full Xcode with usable iOS SDK and the `devicectl`/`simctl` tools; Command Line Tools alone are insufficient |
| Cocos Creator | Install the exact `creator.version` recorded by the project |
| Project layout | Creator 3.x project root containing `package.json` and `assets/` |
| Build task | Saved iOS task in `profiles/v2/packages/builder.json`, or `buildCmd/buildConfig_ios.json` |
| Physical iPhone | Paired/trusted, reachable, unlocked as needed, Developer Mode enabled, and development signing configured |
| Simulator | Installed and available iOS runtime compatible with the generated app architecture |

### Supported engine range

The tool accepts Creator **3.x** projects. Compatibility handling is focused
on Creator **3.7.x**, including 3.7.3. Custom extensions and native templates can
need additional work. “Accepted project” does not mean every Creator 3.x release
has been verified on a device.

The current architecture selection is:

| Target | Architecture chosen by the tool |
| --- | --- |
| Physical iPhone | arm64 |
| Simulator, Creator earlier than 3.8 | x86_64 |
| Simulator, Creator 3.8 or later | arm64 |

For Creator 3.7.x on Apple Silicon, use an iOS Universal Runtime that supports
x86_64 and install Rosetta as required by your system. An arm64-only runtime is
not sufficient for an x86_64 Simulator app. Runtime availability depends on the
installed Xcode and macOS; choose an installed compatible runtime instead of
assuming any particular iOS version is available.

### Outside the supported scope

- Mac Intel installers and universal Mac installers.
- Windows or Linux hosts, Cocos Creator 2.x, and Android targets.
- App Store Connect/TestFlight publishing, IPA export, and automatic certificate setup.
- Automatic Xcode, Cocos Creator, iOS runtime, or Rosetta installation.
- Independent live iPhone stdout/stderr streaming.
- LLDB attachment, breakpoints, sanitizers, and guaranteed source-level symbolication.
- Verification that a game is stable merely because the build or launch succeeded.

## 3. Download and verify the installer

Use the latest GitHub Release in the public download repository. Download the
`.pkg` and the matching `.sha256` file. Avoid old copies and GitHub's generated
“Source code” archives: those are not installers.

For the currently prepared development build, the files are:

```text
cocos-builder-1.0.1-macOS-arm64-development.pkg
cocos-builder-1.0.1-macOS-arm64-development.pkg.sha256
```

In Terminal, change to the folder containing both files and run:

```sh
shasum -a 256 -c cocos-builder-1.0.1-macOS-arm64-development.pkg.sha256
```

Expected result: the installer filename followed by `OK`. A checksum mismatch
means the files do not belong together or the download changed; download the
matching files again. Checksums check file integrity, not Apple notarization.

### Signing status of this build

The prepared 1.0.1 development build uses an ad-hoc app signature. The installer
is unsigned and has not been notarized by Apple. Gatekeeper may refuse it or
suggest moving the app to Trash after an Internet download. The tool cannot
approve its own security status.

For a normal end-user distribution, the maintainer must generate a Developer
ID signed and notarized installer. If macOS blocks a development copy, obtain
the signed release from the maintainer. Administrator authorization during
installation does not override Gatekeeper.

## 4. Install and open

1. Open the `.pkg` in Finder.
2. Read the Installer introduction and destination information.
3. Proceed with installation into `/Applications/cocos builder.app`.
4. When macOS Installer requests administrator authorization, authenticate using
   the system dialog. The system determines whether to request a password,
   Touch ID, or reuse an authorization already granted in the current session.
5. Open **cocos builder** from Applications.

No separate Python or Qt installation is needed for the packaged app. Internet
access may still be required for Apple's signing/provisioning services, project
dependencies, or installing external prerequisites.

The app itself runs as your user. It does not ask for permanent root access or
request administrator permission every time you launch it.

## 5. Prepare Xcode, Cocos, and your project

### Xcode

1. Install full Xcode compatible with your macOS and target iOS version.
2. Open Xcode once and finish its first-launch setup and license prompts.
3. In Xcode Settings, select the intended Xcode under Locations → Command Line Tools.
4. Install the required iOS Simulator runtime through Xcode if using Simulator.
5. For iPhone builds, add your Apple account and establish a working development
   certificate/provisioning setup in Xcode.

Useful diagnostic commands:

```sh
xcode-select -p
xcodebuild -version
xcrun --sdk iphoneos --show-sdk-path
xcrun simctl list runtimes
```

These commands inspect the active tools; they do not configure signing for you.

### Cocos Creator

1. Read `creator.version` in your project's `package.json`.
2. Install that exact version using Cocos Dashboard.
3. Open the project in Cocos and save an iOS build task at least once.
4. Configure scenes, startup scene, bundles, and extensions in Cocos as required.
5. Close or pause other builds of the same project before using this tool.

The default Creator executable path is:

```text
/Applications/Cocos/Creator/<version>/CocosCreator.app/Contents/MacOS/CocosCreator
```

If installed elsewhere, use **Chọn Cocos…** (Choose Cocos) to select the
executable. Selecting the project root is essential; do not select `assets/`,
the generated Xcode project, or an exported build folder.

### iPhone preparation

Connect and trust the Mac, enable Developer Mode, pair the device in Xcode,
and make sure its iOS version is supported by the selected Xcode. USB is the
simplest initial setup. Already paired network devices can appear when Apple's
tools report them as reachable; the tool does not perform initial pairing.

Simulator does not require Apple development signing. A physical iPhone does.
The Team ID and Bundle ID used to sign the iPhone game are separate from the
Developer ID certificates used to distribute this macOS tool.

## 6. Select the project and destination

1. Drop the Cocos project folder onto the tool, or use its project chooser.
2. Open **Cài đặt** (Settings).
3. Select the saved **Cấu hình Cocos** (Cocos configuration).
4. Under **Chạy trên** (Run on), choose physical iPhone or iOS Simulator.
5. Click the refresh icon and choose the destination under **Thiết bị** (Device).
6. Check the **Bundle ID**, **Apple Team ID** for physical builds, and Creator path.
7. Expand **Cocos iOS Build Config** to review the build options.

The tool checks for the matching Creator installation and full Xcode when the
project or Creator path changes and before building. Use **Kiểm tra lại**
(Check again) after installing or fixing a prerequisite.

Selections and edited options are remembered by project/task. Changing projects
restores that project's saved choices rather than applying a single global
configuration to every project.

## 7. Choose the correct action

| Action | Export/compile | Device required | Installed-app behavior |
| --- | --- | --- | --- |
| Build | Exports when needed and compiles | No | Saves a build on the Mac; does not install or launch |
| Build & Run | Exports when needed and compiles | Yes | Installs only when the app is absent; preserves an existing installation |
| Run | Uses an existing compatible build | Yes | Preserves the existing installed copy; no Cocos export or Xcode compile |
| Clean & Run | Uses an existing compatible build | Yes | After confirmation, uninstalls the selected app, deletes its device data, installs the build, and launches it |

### First launch on a Simulator

1. Select Simulator and a compatible device.
2. Leave native-only mode off for the first export.
3. Click **Build & Run**.
4. The tool exports through Cocos, compiles through Xcode, boots the selected
   Simulator if needed, installs the game if absent, and launches it.
5. If independent log capture is enabled, the tool follows the captured output.

### Deploy changed game code or assets

1. Save your project changes.
2. Click **Build**, or **Build & Run** if you also want the normal run flow.
3. Check the build result and selected device.
4. If the same Bundle ID is already installed, use **Clean & Run** to replace it
   with the newly built app. Read and confirm the data-deletion prompt.

Normal Run/Build & Run deliberately preserves an installed app. Seeing the old
version after a successful build is expected in this case. Clean & Run does not
compile changes for you; build first. Back up valuable game data before using it.
If the compatible build is missing, the tool stops before deleting the installed
app. Device deployment can still fail after an intentional uninstall, so local
build validation cannot guarantee reinstall success.

### Build for an iPhone

1. Choose physical iPhone mode and a reachable device for run actions.
2. Set the 10-character Apple Team ID and a Bundle ID that the team can sign.
3. Ensure Developer Mode and trust/pairing are enabled.
4. Click Build or Build & Run.
5. Resolve certificate/provisioning errors in Xcode if Apple rejects signing.

Build can compile for a generic physical-device destination without a selected
phone, but development signing is still required. Run checks the available app's
Bundle ID, platform, architecture, and selected Debug/Release configuration.

## 8. Build configuration reference

| Setting | Meaning |
| --- | --- |
| Debug / Release | Selects the native build configuration |
| Build name | Name copied into the generated Cocos configuration |
| Output directory / subdirectory | Controls the Cocos export location |
| MD5 Cache | Enables the corresponding Cocos build option |
| Source Maps | Requests Cocos source maps |
| Auto Atlas | Uses the Cocos auto-atlas build option |
| Skip texture compression | Uses Cocos's corresponding texture-compression option |
| Main bundle compression | Selects the Cocos main-bundle compression mode |
| Minimum iOS | Sets the target deployment version, subject to the SDK/toolchain |
| Auto Rotate | Adds a reversible override to supported generated iOS orientation methods |
| Orientation checkboxes | Select allowed portrait/landscape orientations; at least one is required for Auto Rotate |
| Metal | Selects the saved Cocos iOS Metal backend option |
| Script encryption / XXTEA key | Controls native script encryption in the generated game configuration |
| Native ZIP compression | Controls Cocos's native compression setting |
| Scenes / startup scene | Chooses included scenes and the startup scene from the available catalog |
| Restore Cocos configuration | Restores the saved Cocos task options for editing in the tool |

Auto Rotate changes the project's generated
`native/engine/ios/ViewController.mm` when compatible methods exist. Disabling
it removes the tool's marked override and restores the original method bodies.
The tool does not edit `native-templates` for this feature. Custom controllers
can require a different implementation.

Treat XXTEA keys and saved project settings as sensitive. Do not upload the
settings file or generated project configurations to the public download repo.

## 9. Cache and native-only builds

- **Dùng output/cache hiện có** (Reuse current output/cache) uses the selected
  Cocos task's existing output location, commonly `<project>/build/ios/`.
- When disabled, output is isolated under
  `<project>/build/ios-builder/device/ios/` or
  `<project>/build/ios-builder/simulator/ios/`.
- The normal incremental check uses configuration, paths, file sizes, and
  modification times to decide whether Cocos export can be skipped.
- **Buộc xuất lại Cocos** (Force Cocos export) bypasses the incremental hit for
  normal builds. Use it when uncertain about linked assets or stale exports.
- **Chỉ build native** (Native-only) reuses an existing export and skips Cocos
  export. Use it only when that export already contains your intended content.
- Editing relevant build options through the UI invalidates native-only for
  that changed configuration. After source/asset changes, normal export remains
  the appropriate workflow.

A stat-based cache is not a full content hash. Content changes that preserve
size/timestamps, or changes inside some symlinked content, can require forcing
export. Switching between simulator/device or Debug/Release can trigger native
recompilation even when Cocos export is reused. Avoid concurrent Cocos GUI or
other build-tool runs against the same project.

## 10. Simulator controls

| Control | Behavior |
| --- | --- |
| Refresh | Rescans available devices/runtimes |
| Create (+) | Chooses an installed compatible runtime, model, and name; selects the new Simulator |
| Show/open | Brings Simulator to the foreground; may boot the selected device |
| Power | Explicitly boots or shuts down the selected Simulator |
| Reload/restart | Reboots the selected Simulator while keeping its data; does not automatically run the game |
| Delete | Deletes the selected Simulator and its data after confirmation |

The running indicator describes Simulator/device state, not game stability.
Shutdown/restart ends apps on that selected Simulator. Deletion checks for
running apps and can refuse until they are closed. Management actions are
restricted while a build or conflicting log/action session is active.

The selected **Device log** source is independent of the Build/Run destination.
Showing another Simulator does not automatically move your log source or run a
game on it.

## 11. Logs and crash reports

### Build logs

The UI shows recent output and supports case-insensitive search and
All/Error/Warning filters. Clear log clears the view, not the saved file. The
view retains up to 5,000 recent lines.

Tool-generated logs and configuration are stored per project under:

```text
<project>/build/ios-builder/device/
<project>/build/ios-builder/simulator/
```

Subfolders include `logs/`; generated metadata includes `builder-config.json`
and `last-built.json`. Simulator stdout/stderr records are under the Simulator
log folder's `app-output/` directory.

### Independent Simulator observation

Enable **Thu log độc lập** (Independent log capture) to follow output after
launch. **Ngắt log** (Disconnect log) or closing the tool stops the observer;
it does not intentionally stop the game. If the game exits, the tool reports
that condition and does not automatically restart it.

Games launched outside the tool may have no captured stdout/stderr files.
Observation then uses unified logs by process ID, which may not include every
JavaScript `console.log`. Independent live iPhone log observation is currently
unavailable; the tool avoids attaching a `devicectl` console session to the game.

### Native crashes

The Crash tab scans local `.ips` reports roughly every three seconds. For a
physical iPhone, export a crash report using Apple's tools and open the `.ips`
file manually in the panel.

Frame resolution uses local symbols only when UUID and architecture match.
Source excerpts appear only when the resolved frame points to an existing
source file and line. Missing or mismatched symbols mean function names/lines
can remain unresolved. Use Xcode/LLDB for deep native debugging.

## 12. Settings, modified files, and removal

User settings are stored at:

```text
~/Library/Application Support/Cocos iOS Builder/settings.json
```

The tool creates generated build configs and metadata in the selected project,
uses Cocos's normal export/import/cache process, and applies compatibility,
Info.plist/signing, and supported rotation changes to generated/native output.
It does not rewrite the original saved Cocos build profile or the installed
Creator engine. Native generated files inside the project can change.

To remove the tool, quit it and move `/Applications/cocos builder.app` to Trash.
The settings folder and each project's generated outputs/logs are separate.
Keep any logs or builds you need before deleting those folders manually.
Uninstalling the tool does not remove Xcode, Cocos, Simulator devices, or the
games already installed on your devices.

## 13. Troubleshooting

| Symptom | What to check |
| --- | --- |
| macOS says the app is damaged or suggests Trash | Check release signing status and checksum. The current development build is not notarized; request a signed build. |
| Installer asks for a password | Expected for a system-wide `/Applications` installation; authenticate only through the macOS Installer dialog. |
| Installer does not ask again | macOS can reuse authorization in the current session; the tool cannot force the system to prompt every time. |
| Creator not found | Install the exact project version or correct the executable path, then click Check again. |
| Xcode not ready | Open full Xcode, finish setup, and select its Command Line Tools. |
| No saved iOS task | Create/save an iOS configuration in Cocos first, or supply the supported fallback file. |
| No Simulator runtime is offered | Install a runtime compatible with your Xcode, macOS, and required app architecture. |
| Creator 3.7.x Simulator architecture error | Verify x86_64 support/Universal Runtime and Rosetta availability. |
| iPhone is missing | Check USB/trust/pairing, Developer Mode, unlock state, and Xcode device support; refresh. |
| Signing/provisioning failure | Verify Team ID, Bundle ID, development certificate/private key, and provisioning in Xcode. |
| Build completed but old game appears | Normal deployment preserves an installed copy. Build first, then use Clean & Run if deleting its data is acceptable. |
| Run cannot find an app | Build the matching Debug/Release, Bundle ID, platform, and architecture first. |
| New asset/script is missing | Leave native-only mode off and force Cocos export if the incremental cache is stale. |
| Project is locked | Finish or stop the other build/run session using that project's tool lock. |
| Some JavaScript logs are absent | Unified logs are incomplete for some externally launched apps; launch through the tool with capture or use native debugging. |
| Crash frames have no source lines | Match the exact build's symbols and architecture; ensure referenced source paths exist. |

When reporting a problem, include the tool version, Mac CPU/macOS, Xcode and
Creator versions, destination/runtime, action used, relevant build-log section,
and `.ips` report if applicable. Remove credentials, encryption keys, and private
project content before sharing logs publicly.
