# cocos builder 1.0.2

- Add Android APK export, Gradle builds, install/launch and cached APK validation.
- Select installed Android Studio, SDK, NDK and JDK per project; automatically
  select compatible installed Java for Gradle and SDK command-line tools.
- Manage selected Android emulators or connect USB / Wi-Fi phones, including QR
  pairing. One target dropdown controls the selected device; Refresh prefers a
  running emulator. Running devices have green indicators and power actions use
  the same state colors as iOS.
- Automatically stream the selected device's Logcat into the shared Android log
  panel, including during builds. Remove separate Logcat, crash-buffer and
  output/Studio shortcut actions.
- Add platform icons, work spinners, connected-device counts and a four-second
  Refresh hint when no emulator is selected.
- Color normal logs white, errors red, warnings yellow and SDK/NDK diagnostics
  green. Dependency notifications identify missing packages and setup steps.

## Validation and limits

The full automated suite passes (132 checks). A fresh Cocos 3.7.3 ARM64 Debug
APK was built, installed and launched on an Android emulator. The Qt Build & Run
flow automatically switched Java 21 to installed Java 11 for Gradle 6.5.1.
Automatic Logcat was also verified against emulator-5554 without locking build
controls. This does not verify authenticated gameplay or physical-phone QR
pairing. AVD creation/deletion still needs native verification.

The installer remains a development preview: ad-hoc signed app, unsigned PKG,
no Developer ID or notarization. Apple Silicon / macOS 14.4+ only. The public
download branch is dowload-v102; source remains public in the separate source repo, as selected by the owner.
