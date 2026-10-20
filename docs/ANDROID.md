# Android APK development workflow

Android support is included in the 1.0.2 development installer.

1. Select a project in the shared sidebar, then select the **Android** tab to the
   right of iOS. Android-only projects do not need an iOS task.
2. Expand **Công cụ Android**. Choose an installed Android Studio bundle, SDK,
   NDK and Java Home. Renamed Studio bundles are listed with full paths.
3. Use **Kiểm tra công cụ**. Install missing packages through Android Studio's
   SDK Manager: SDK Platform, Build Tools, Platform Tools, NDK (Side by side),
   Android Emulator, Command-line Tools and a suitable system image.
   Selecting a project or changing tool paths now checks dependencies automatically.
   Missing tools appear as yellow Warning lines in the log and in a visible setup
   banner naming the required package and installation menu. Use its setup buttons
   to open Android Studio or the appropriate download page. Attempting an action
   blocked by a missing dependency also opens an installation guidance dialog.

4. Choose the saved Android build task. If none exists, open Cocos, create and
   save an Android build task, and select the project again.
5. Expand **Cocos Android Build Config** to adjust scenes, package ID, Debug/
   Release, target API, optional min/compile SDK and version code/name, ABIs,
   orientations and native script options. Unknown extension fields are retained.
   Edits are saved in the tool's Android-specific settings, independently of iOS.
6. Build a Debug APK first. Use **Build APK** without a device, or select a ready
   device and use **Build & Run**. AAB output is disabled.
7. **Run APK đã build** validates the successful build record and installs/launches
   it without rebuilding. **Chọn APK** explicitly selects a separate APK instead.
   Its package ID must match the selected task. APK signature, device ABI and
   minSdk are checked before installation or destructive cleanup.
8. **Clean & Run** asks before uninstalling the chosen package and deleting its
   data on the selected device. Validate the APK before confirming installation.
9. Selecting a running Android device automatically streams its Logcat into the
   shared Android log panel. No Logcat button is needed. Logging continues during
   builds and launches; selecting another device switches the stream. Selecting a
   stopped AVD waits until it becomes available. This is the whole device's log,
   including other apps; existing search/severity filters apply. The separate
   crash-buffer action and Output/Studio shortcut buttons have been removed.

## Studio, Java and Gradle

Cocos 3.7.x generated wrappers commonly use Gradle 6.x and JDK 11. Selecting a
modern Studio with its JDK 21 does not make that old wrapper compatible. The
page prefers a locally available Studio JDK 11 for Cocos 3.6/3.7 and allows manual
selection. It checks the generated wrapper before compiling and reports an
incompatible Java selection, automatically selecting a compatible installed JDK. Missing compatible JDKs produce installation guidance.

SDK command-line packages can have a separate Java requirement. If avdmanager
reports UnsupportedClassVersionError, use an appropriate installed Java Home for
that SDK operation. The runner now selects an installed JDK 17+ for SDK commands independently of the build JDK.

## Emulators and phones

- One device dropdown lists stopped AVDs and running devices for the selected mode. All control actions use that exact selection. Inventory refreshes automatically after boot. Explicit Refresh selects a running emulator, keeping the current one when it is already running; background polling preserves the selected target. Running emulator rows show the same green indicator as iOS. Emulator controls are hidden in physical-phone mode. **Refresh thiết bị** also refreshes the list. **Tạo AVD** uses installed
  system images and device definitions; it does not silently download images or
  accept SDK licenses. Install missing images and command-line tools in Studio.
- **Mở AVD** requests launch and writes emulator startup output under
  `~/Library/Logs/Cocos Android Builder/emulator.log`. The list updates automatically after boot.
- **Tắt máy ảo** addresses the selected running emulator serial explicitly.
  **Xóa AVD** asks for confirmation and refuses to delete a running AVD.
- For USB phones enable Developer options / USB debugging, connect USB, unlock
  the phone and accept the RSA authorization prompt, then refresh devices.
- For Wi-Fi enter the pairing host:port, click **Pair bằng mã**, and enter the
  six-digit pairing code. Then enter the separate connection host:port and use
  **Connect Wi-Fi**. Pairing codes are neither saved nor printed.
- **QR Wi-Fi** displays a pairing QR for the phone's Wireless debugging → Pair device with QR code camera. Credentials remain in memory; cancellation terminates pairing. A connected device is selected only after its identity is verified.
- Unauthorized/offline devices remain visible. **Build & Run** remains clickable and explains missing selection, dependencies or authorization through logs and notifications.
- Platform tabs show a platform icon, an animated spinner during work, and a device icon with the number of running emulators / connected phones. Counts refresh in the background for both tabs.
- Every Build/Run attempt logs SDK location, installed API range, project min/target/compile SDK, selected NDK and installed NDK range in green. Installed ranges describe availability, not a supported compatibility range. Missing tool errors remain red and warnings yellow.

## Cancellation and artifacts

Long operations run in workers. **Dừng** terminates the owned process group;
stop active Android work before changing projects or closing the window. Merely
switching platform tabs does not terminate a task. The window prevents concurrent
iOS and Android builds. Android output is locked against another tool instance.
The tool never kills the global adb server or closes an unrelated device app.

Build logs are under the project's `build/android-builder/logs`. A successful APK
record is stored in its export directory; a new build invalidates the old record
until that build succeeds. Signature/package/hash checks prevent accidental use
of a tampered or mismatched recorded APK. Explicitly selected APKs are always
checked again before installation.

Keystore passwords and XXTEA keys are stripped from tool settings. Enter an
XXTEA key again when an encrypted configuration needs it. Existing Cocos project
signing is retained for Release tasks; unsigned APKs cannot be installed. This
change does not introduce distribution signing or upload workflows.

## Verification status

Automated backend and offscreen Qt checks exercise configuration isolation,
discovery, device states, serial targeting, APK validation, failure paths,
cancellation and Gradle/JDK compatibility alongside the existing iOS suite.
A rendered Qt inspection covers the Android page and log severity colors. The native macOS debug app was also opened and its platform tabs, selected tools, Android task and controls were inspected through accessibility.

Local checks found Studio 2021.2/JDK 11 and two Studio 2025.2/JDK 21 bundles,
SDK/NDK/Build Tools, one AVD named Pixel_3_XL, and no connected Android devices.
The project's actual Gradle 6.5.1 wrapper runs with the selected JDK 11. A configuration-only Gradle check also confirmed that both Debug and Release variants receive the requested versionCode 42, versionName test.42 and minSdk 24 before compilation.
Command-line tool directories currently contain no avdmanager/sdkmanager, so
actual AVD creation/deletion is not verified here.

On 2026-10-20 the existing ARM64 AVD Pixel_3_XL (Android API 36) booted as
emulator-5554. The actual Origami Android task was exported through Cocos 3.7.3,
built as a fresh arm64-v8a Debug APK through the AndroidRunner backend, installed
with adb Success and launched with Status: ok. PID 15661 remained alive, Android
reported AppActivity resumed, and a device screenshot showed the login screen
rendering at 60 FPS. The APK was generated at
`build/android/proj/build/OrigamiAndoird/outputs/apk/debug/OrigamiAndoird-debug.apk`
in the game project (91,425,337 bytes, 2026-10-20 08:08:36 local time).
The AndroidRunner Logcat polling and cancellation were also exercised on that live process. A remote-shell quoting issue in its date command was fixed and covered by a regression test; the relevant regression tests pass.
This verifies build/install/launch to the login screen, not authenticated gameplay.
Physical phone behavior and AVD creation/deletion remain unverified.

A later offscreen Qt Build & Run check selected pixel6a, automatically changed
JDK 21 to installed JDK 11 for Gradle 6.5.1, completed a fresh APK build and
installed/launched AppActivity on emulator-5554 with Status: ok. SDK command-line
tools are now installed. Physical QR pairing and AVD creation/deletion remain
unverified on real devices. Automated checks cover QR identity, timeout,
cancellation and credential redaction.
