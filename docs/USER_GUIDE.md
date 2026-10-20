# Cocos Builder Duo Native — Installation and User Guide

**Version 1.0.2 · Apple Silicon macOS · iOS and Android APK**

The download repository is named **Cocos Builder Duo Native**. After installation,
the app appears in Applications as **cocos builder**. The UI is mainly Vietnamese;
this guide uses the exact visible labels alongside English explanations.

## Start here

1. [Check requirements](#requirements).
2. [Download, verify and install](#install-the-macos-app).
3. [Prepare your Cocos project](#prepare-your-cocos-project).
4. Follow either [Android](#android-build-and-run) or [iOS](#ios-build-and-run).
5. If an action fails, use [Troubleshooting](#troubleshooting).

An Android-only project does not need an iOS task or Apple signing configuration.
Choose the platform you need rather than completing both setup paths.

## Requirements

| Component | Required for |
| --- | --- |
| Apple Silicon Mac, macOS 14.4+ | This packaged macOS app; individual Xcode/Studio versions may require newer macOS |
| Exact project Cocos Creator version | Both platforms; read `creator.version` in `package.json` |
| Cocos project root with `package.json` and `assets/` | Both platforms |
| Saved Cocos build task for the selected platform | iOS or Android respectively |
| Full Xcode, selected Command Line Tools and usable iOS SDK | iOS builds |
| Installed compatible iOS Simulator runtime | iOS Simulator |
| Trusted iPhone, Developer Mode and working development signing | Physical iPhone |
| Android Studio / SDK Platform / Build Tools / Platform Tools / NDK / compatible JDK | Android APK builds |
| Emulator + Command-line Tools + an installed system image | Android emulators |
| USB debugging, or Wireless debugging with Mac and phone on the same Wi-Fi | Physical Android phone |

Python 3.15, PySide6/Qt and the QR library are bundled. You do not need to install
Python or Qt separately for the PKG. Platform tools, runtimes, SDK licenses and
project dependencies are separate. The app reports missing components and tells
you where to install them; it does not silently download or license them.

Creator 3.x projects are accepted; compatibility work mainly targets 3.7.x,
including 3.7.3. Every engine version, extension and native template has not been
verified. Windows/Linux hosts, Intel Mac installers, Creator 2.x, Android AAB,
IPA export, App Store/TestFlight/Play Store publishing and automatic certificate
setup are outside this release's scope.

## Install the macOS app

### Download the correct two files

Open the [download page](https://github.com/sulong-729/installer-cocos-builder-duo-native/tree/dowload-v102), then download:

- [cocos-builder-1.0.2-macOS-arm64-development.pkg](https://media.githubusercontent.com/media/sulong-729/installer-cocos-builder-duo-native/dowload-v102/cocos-builder-1.0.2-macOS-arm64-development.pkg?download=1)
- [cocos-builder-1.0.2-macOS-arm64-development.pkg.sha256](https://raw.githubusercontent.com/sulong-729/installer-cocos-builder-duo-native/dowload-v102/cocos-builder-1.0.2-macOS-arm64-development.pkg.sha256)

Use the direct PKG link. The installer is about **149.7 MB** and is stored with
Git LFS. A tiny text file beginning `version https://git-lfs.github.com/spec/v1`
is a pointer, not an installer. Do not use the repository's ZIP archive.

### Verify the download

Put both files in the same directory. If you used Downloads, open Terminal and run:

```sh
cd ~/Downloads
shasum -a 256 -c cocos-builder-1.0.2-macOS-arm64-development.pkg.sha256
```

Expected output:

```text
cocos-builder-1.0.2-macOS-arm64-development.pkg: OK
```

If the filename is different, or verification fails, download the matching pair
again. A checksum verifies integrity; it does not certify Apple notarization.

### Install and launch

1. Quit an older running copy of cocos builder before updating.
2. Double-click the PKG in Finder.
3. Follow Installer to install into `/Applications/cocos builder.app`.
4. Authorize installation through the macOS system dialog when requested.
   macOS may reuse authorization from the current session.
5. Open **Applications → cocos builder** and check version **1.0.2** in the title.

The app runs under your user account after installation. Existing project outputs
and settings are separate from the app bundle and can remain after an update.

### Installation problems

**Current signing status:** this is a development preview: ad-hoc signed app,
unsigned PKG, no Developer ID and no Apple notarization. Gatekeeper may refuse it
or suggest moving it to Trash. If blocked, verify the checksum and request a
signed/notarized build from the maintainer. Administrator authorization does not
override Gatekeeper. This guide does not require disabling macOS security.

If a download produces an HTML error page or a tiny LFS pointer, return to the
current README and use its direct installer link. If Installer says the package
is invalid, re-download and verify before trying again.

## Prepare your Cocos project

1. Find the game folder containing `package.json` and `assets/`.
2. Read `creator.version` from `package.json` and install that exact Creator
   version with Cocos Dashboard. A different installed Creator is not a substitute.
3. Open the project in Creator, open its Build panel, choose iOS or Android, and
   save a build task with scenes and a valid startup scene.
4. Add/select this project in the tool's left sidebar. You can also drop the
   project root onto the supported project drop area.
5. Choose **iOS** or **Android** at the top. The platform's saved task and settings
   are restored separately for each project.

Do not select `assets/`, the exported Xcode/Gradle project, or a generated output
folder as the project root. Avoid concurrent Cocos GUI or other tool builds that
write to the same project/output.

The usual Creator executable path is:

```text
/Applications/Cocos/Creator/<version>/CocosCreator.app/Contents/MacOS/CocosCreator
```

If Creator is installed elsewhere, choose the matching executable through the
platform's Cocos path selector. After installing a missing component, use its
check/refresh control again.

## Android build and run

### 1. Install and select Android tools

1. Install Android Studio and finish its initial setup.
2. Open Studio's **Tools → SDK Manager**. Install the required SDK Platform
   under SDK Platforms. Under SDK Tools install **Android SDK Build-Tools**,
   **Android SDK Platform-Tools**, and **NDK (Side by side)**.
3. For AVDs also install **Android Emulator**, **Android SDK Command-line Tools
   (latest)** and a suitable system image. Accept the required licenses in Studio.
4. In cocos builder, select **Android → Công cụ Android**. Choose the installed
   Studio bundle and check the SDK, NDK and Java Home fields.
5. Run **Kiểm tra công cụ**. Resolve the named missing package or path before
   building. Red/yellow logs and the setup notice explain what needs attention.

On a default macOS setup, the SDK is commonly `~/Library/Android/sdk` and an NDK
is under `~/Library/Android/sdk/ndk/<version>`. Select your actual installation.
Java Home must point to the JDK home, not directly to `bin/java`.

Selecting a newer Studio does not make an old Gradle wrapper compatible with its
newer Java. The tool checks the wrapper and chooses a compatible **installed**
JDK when available. The tested Gradle 6.5.1 project used JDK 11. New SDK utilities
can need JDK 17+; the tool selects their Java environment separately. If the
required Java is absent, install it and select/check the paths again.

### 2. Check the Android build task

Select the saved Android task and expand **Cocos Android Build Config**:

| Field | Check before building |
| --- | --- |
| Scenes / startup scene | Include the intended scene and select it as startup |
| Package ID | Use the app's real Java-style ID, for example `com.company.game` |
| Debug / Release | Use Debug for initial device testing |
| ABI | Match the target; the tested ARM64 emulator used `arm64-v8a` |
| Target API | Ensure the needed SDK Platform is installed |
| minSdk / compileSdk overrides | Set only when needed; minSdk cannot exceed target and compileSdk cannot be below target |
| Version code / name | Optional generated Gradle overrides |
| Orientations / native options | Confirm the intended Cocos settings |

Tool edits are stored separately from iOS. Keep **Chỉ build Gradle từ bản export
hiện tại** unchecked for a first build or after changing scripts/assets. Native-only
mode is for an existing matching Cocos export; the tool rejects stale build records
or requests a fresh export when needed.

### 3A. Use an Android emulator

1. Choose **Máy ảo Android**.
2. Click **Refresh**. It prefers an already running emulator, keeping the current
   selected one if that machine is already running. Running rows have green dots.
3. If no suitable AVD exists, click **＋ Tạo AVD**. Choose an installed system
   image/model and a name. Install missing images in Studio first.
4. Select the AVD in the single target dropdown. Its green power icon boots a
   stopped AVD; a red power icon shuts down a running AVD after confirmation.
5. Wait for Android to finish booting. Inventory updates automatically; use
   Refresh if needed. An AVD name without a running serial is not a ready device.
6. Confirm the selected row shows the intended machine, then click Build & Run.

All AVD actions address the selected dropdown target. **Mở AVD đã chọn** opens it;
the trash icon deletes the AVD and its data after confirmation and refuses running
AVDs. Power-off ends apps on that machine. Refresh highlights briefly every four
seconds when no emulator is selected. Background polling preserves your target;
it does not silently switch to another machine.

### 3B. Use a phone over USB

1. On the phone enable Developer options and **USB debugging**.
2. Connect a USB data cable, unlock the phone and accept its RSA / Allow USB
   debugging prompt for this Mac.
3. Choose **Điện thoại thật** in the tool. Emulator controls are replaced with
   phone connection controls.
4. Click **Kết nối USB / Quét lại** and select the phone in the target dropdown.
5. Resolve `unauthorized` on the phone, or reconnect if `offline`, before Run.

### 3C. Use a phone over Wi-Fi

Keep the Mac and phone on the same network and enable **Wireless debugging**.

**QR pairing:** on a compatible Android 11+ phone, open Developer options →
Wireless debugging → **Pair device with QR code**. In the tool click **Kết nối
Wi-Fi bằng QR…**, then scan that QR with the phone's Wireless debugging scanner.
Use the code within two minutes. Closing the dialog cancels the pairing session.
Pairing secrets are not saved in tool settings or printed in logs.

**Pairing code:** open **Pair device with pairing code** on the phone. Enter its
pairing `host:port` in the tool, click **Pair bằng mã…** and enter the six-digit
code. Then use the separate connection `host:port` shown by Wireless debugging
and click **Connect Wi-Fi**. Pairing and connection ports can be different.

Pairing alone does not prove the device is connected. Confirm a ready phone row
appears and select it. If discovery fails, check the network's mDNS support,
Wireless debugging, Platform Tools version and any Local Network permission.
QR pairing has automated protocol coverage but still needs physical-phone validation.

### 4. Build, install and run

| Action | Result |
| --- | --- |
| Build APK | Export through Cocos and build an APK with Gradle; no device needed |
| Build & Run | Build, validate the selected device, install the APK and launch it |
| Run APK đã build | Validate and run an existing recorded APK without rebuilding |
| Chọn APK… | Select a different local APK explicitly; it must match the task Package ID |
| Clean & Run… | Validate the APK, ask for confirmation, uninstall the selected package/data and reinstall/launch |
| Dừng | Cancel the current foreground task's owned process group |

Normal Android install uses `adb install -r`: it updates/reinstalls the package
and normally retains app data. Signature/package/version constraints can still
cause installation to fail. Clean & Run deletes data; use it intentionally.
The recorded APK is checked for signature, package, hash, matching build inputs,
device ABI and minimum Android API before the relevant run steps.

Build & Run remains clickable when setup is incomplete so a notification can
explain what is missing. It still requires a saved Android task and a ready
selected device to complete. Read the first actionable error in the log.

### 5. Read Android runtime logs

Selecting a running device automatically starts **Logcat in the shared Android
log panel**, even before Run. A stopped selected AVD is followed when it becomes
available. Switching the target switches the stream. Logs continue during builds.

This is the selected device's full Logcat and can include system/other-app logs.
Use search and severity filters to narrow it. There is no separate Logcat button,
Android crash-buffer action, Mở output button or Mở project trong Studio button.
To inspect generated output manually, use the project's selected Cocos export
folder in Finder or open its Gradle project directly in Studio.

## iOS build and run

### 1. Prepare Xcode and a destination

1. Install full Xcode compatible with your macOS and target iOS. Open it once and
   finish initial setup and license prompts.
2. In Xcode Settings → Locations, select the intended Command Line Tools.
3. For Simulator, install a compatible iOS runtime. For Creator before 3.8 the
   tool selects x86_64; Creator 3.8+ uses arm64. A Creator 3.7.x build therefore
   needs a runtime supporting x86_64, and Rosetta where required by the system.
4. For iPhone, connect/trust/pair it in Xcode, enable Developer Mode and establish
   working Apple development signing. Simulator does not need that signing.

### 2. Select task and build

1. Open **iOS → Cài đặt**, select the saved Cocos iOS task and correct Creator.
2. Set the game's Bundle ID. For iPhone, select the 10-character Apple Team ID.
3. Choose Simulator or iPhone mode. Refresh and select the intended destination.
   Refresh prefers a booted Simulator; green dots identify booted rows.
4. Check **Cocos iOS Build Config**, scenes and Debug/Release. Keep native-only
   mode off for the first export.
5. Click Build & Run. The tool exports Cocos, compiles with Xcode, prepares the
   selected destination and launches the app. Check the log and game window.

### 3. Choose the correct iOS deployment action

| Action | Compile? | Existing installed game |
| --- | --- | --- |
| Build | Yes | No device install/launch |
| Build & Run | Yes | Preserves an existing installation; installs only if absent |
| Run | No; requires a compatible existing build | Preserves an existing installation |
| Clean & Run | No new compile; build first | Asks before uninstalling the selected app/data and installing the built copy |

**To see changed iOS code/assets:** save changes → Build → confirm build success →
Clean & Run if the same Bundle ID is already installed and deleting its data is
acceptable. Normal Run can show the older installed game even after a new build.
This differs from Android's normal reinstall/update behavior.

Xcode certificate/provisioning failures must be resolved in Xcode. The game's
Apple development signing is separate from Developer ID/notarization used to
distribute this macOS tool.

### Simulator management and iOS observation

Create chooses an installed runtime/model. Power is green to boot and red to
shut down. Show/reload actions operate on the selected machine; restarting ends
its apps but keeps its data. Delete removes the selected Simulator/data after
confirmation and may refuse until running apps are closed.

**Thu log độc lập** enables independent Simulator observation after Run. The iOS
Device log source is separate from the Build/Run destination. **Ngắt log** or
closing the observer does not intentionally stop the game. Externally launched
apps may lack captured stdout/stderr; unified logs may omit JavaScript output.
Independent live iPhone console capture is not available in this version.

The iOS Crash / Native panel reads local `.ips` reports. For a phone, export the
report with Apple's tools and import it. Frame/source resolution needs matching
local symbols, UUID, architecture and source files; use Xcode/LLDB for deeper work.

## Shared status and log controls

| Indicator/control | Meaning |
| --- | --- |
| Platform icon | iOS or Android tab |
| Animated spinner | That platform has foreground work; log observation alone does not mean a build is active |
| Device icon + count | Running simulators/emulators and connected ready phones; not the number of games running |
| Green device dot | Device is booted/ready, not proof that gameplay is healthy |
| White log | Ordinary output |
| Yellow log | Warning or setup notice |
| Red log | Error/failure |
| Green Android parameters | Selected/installed SDK and NDK information |
| Search / Tất cả / Error / Warning | Filter the visible log text and severity |
| Clear log | Clear the in-app log view; does not delete existing saved build log files |

The log retains up to 5,000 recent lines. SDK/NDK information is emitted for
Android Build/Run attempts, including unsuccessful attempts. Installed version
ranges describe local availability, not a guaranteed supported SDK/NDK range.
Build completion, device launch and gameplay correctness are separate results.

## Advanced settings and generated files

Scenes, startup scene, Debug/Release, orientations, compression and supported
native options are edited in the platform's build config. Unknown extension
fields are retained. Relevant task settings are remembered per project; the tool
does not rewrite the original saved Cocos build profile.

For iOS, **Dùng output/cache hiện có** reuses the configured Cocos output.
**Buộc xuất lại Cocos** forces export when an incremental result is stale. Native-only
modes reuse generated content and should be left off after script/asset changes.
The incremental check uses metadata such as paths, sizes and timestamps; changes
preserving those values or involving linked content can require a forced export.

The iOS Auto Rotate option can modify supported generated
`native/engine/ios/ViewController.mm` methods with a reversible marked override.
Custom controllers may need manual work. Generated/native outputs, Info.plist and
signing configuration can change during builds; the installed Creator engine is
not rewritten by this tool.

| Data | Location |
| --- | --- |
| User settings | `~/Library/Application Support/Cocos iOS Builder/settings.json` |
| Android saved build logs | `<project>/build/android-builder/logs/` |
| Android APK | Under the chosen Cocos export's Gradle build output; the resulting path is printed in the log/APK field |
| Android emulator startup log | `~/Library/Logs/Cocos Android Builder/emulator.log` |
| Isolated iOS device/simulator metadata and logs | `<project>/build/ios-builder/device/` and `<project>/build/ios-builder/simulator/` |

Treat settings and game logs as potentially sensitive. XXTEA/keystore secrets
are stripped from tool settings, so enter required secret values again when
needed. Never upload credentials, private keys or generated secret-bearing
configs as a troubleshooting attachment.

To uninstall, quit the app and move `/Applications/cocos builder.app` to Trash.
Settings, project outputs, external SDKs, virtual devices and installed games
remain separate; remove them manually only if you intend to lose that data.

## Troubleshooting

| Symptom | Next action |
| --- | --- |
| PKG is tiny or contains Git LFS text | Use the README direct download link, not the repo ZIP or pointer |
| Checksum mismatch | Download the matching PKG/SHA-256 pair again; do not install that copy |
| macOS says damaged/unidentified or suggests Trash | Check the development-signing status under Installation problems and obtain a trusted signed build |
| Project/task list is empty | Select the real project root; open the matching Creator and save a task for the chosen platform |
| Creator version is missing/wrong | Install the exact `creator.version` or correct its executable path, then check again |
| `missing/avdmanager` / cannot create AVD | Install Command-line Tools (latest) in Studio SDK Manager; check SDK path and installed images |
| Missing adb / aapt / apksigner | Install Platform Tools / Build Tools in the selected SDK and rerun the tool check |
| No SDK Platform / NDK | Install the project's required versions in SDK Manager and select the actual paths |
| Gradle rejects Java 21 or reports unsupported class version | Let the tool select a compatible installed JDK, or install/select one matching the generated wrapper |
| avdmanager needs newer Java than the game | Install a suitable SDK-tool JDK; build Java and SDK-command Java are selected separately |
| AVD name is visible but Run fails | Boot the selected AVD and wait until Android/ADB is ready; Refresh and select the running row |
| Android phone is unauthorized/offline | Unlock it, accept RSA, check USB debugging/cable, or reconnect Wi-Fi |
| QR timeout / phone does not appear | Regenerate QR; use Wireless debugging's scanner; check same network, mDNS and Platform Tools; verify connection after pairing |
| APK does not match ABI / minimum API | Choose an ABI supported by the device or a compatible device/API; rebuild |
| APK signature/version install error | Use a compatible signing key/version, or intentionally Clean & Run if deleting the old app/data is acceptable |
| iOS runtime/architecture mismatch | Check the chosen Creator architecture and installed runtime; Creator 3.7.x needs x86_64 support |
| iPhone is missing or signing fails | Check Xcode pairing/trust, unlock/Developer Mode, Team ID, Bundle ID and provisioning |
| iOS shows an older installed game | Build first, then Clean & Run if data removal is acceptable |
| Export/build seems stale | Turn native-only off and force a fresh Cocos export where available |
| Project/output is locked | Finish/cancel the other owner of the same output; do not build it concurrently |
| Android log contains unrelated messages | Full-device Logcat is expected; use search/severity filters and check the selected device |

For a useful issue report, include tool version, Mac/macOS, Creator version,
platform tools, selected destination, the button used, and the first relevant
error with nearby logs. Distinguish build failure, install failure, launch failure
and a crash after launch. Remove credentials and private game data before posting.

## Verification scope for 1.0.2

The automated suite has 132 passing checks. Fresh Cocos 3.7.3 ARM64 Android APK
export/build/install/launch and automatic Logcat were verified on an emulator.
The Qt Build & Run flow selected installed JDK 11 instead of JDK 21 for Gradle
6.5.1. This does not verify authenticated gameplay, physical-phone QR pairing,
or native AVD creation/deletion. Those remaining checks are stated explicitly.
