# Android support design

## Goal

Extend the existing macOS desktop tool with a complete Android build and run
workflow. The platform selector places iOS on the left and Android on the right.
Keep the current dark appearance, 90% initial window size, and white/red/yellow
log colors.

## Window layout

- Retain the project sidebar and introduce ordered platform tabs: iOS, Android.
- Each platform has its own controls, device selection, status and log view.
- Selecting an Android-only project must work without a saved iOS build task.
- Remember platform, Android configuration and tool selections per project.
- Switching tabs must not terminate a running build or device app. Display busy
  state and prevent simultaneous builds against the same project output.

## Android tools

- Discover Android Studio applications in standard application directories,
  including renamed application bundles, using bundle metadata rather than names
  alone. Show version and full path to distinguish duplicate installations.
- Offer a Studio selector, manual .app chooser, Open Studio and download button.
- Discover the Android SDK from configured paths, environment variables and the
  standard macOS SDK location; allow an explicit override.
- List installed NDKs, SDK platforms and build tools. Discover bundled Studio JDKs
  and allow a separate JDK override for older Gradle projects.
- Check actual executable availability and versions for Creator, Java, adb,
  emulator, sdkmanager and avdmanager. Report missing components individually.
- Validate Creator against the project version and explain detected mismatches.
- Select tool versions compatible with the generated Gradle project; never assume
  the newest Android Studio or its bundled Java is compatible with older Cocos.
- Provide actionable setup links and recheck controls. Installation and SDK
  license acceptance require explicit user action rather than silently accepting.

## Cocos Android configuration

- Read Android build tasks and package overrides from saved Cocos profiles, with
  buildCmd/buildConfig_android.json as a fallback.
- Show an actionable message when no Android task exists and offer opening Cocos
  to create one. Do not reuse iOS platform settings as Android defaults.
- Allow task selection, Debug/Release, output directory, application ID, app name,
  version name/code, supported ABIs, available SDK/API selections, orientation,
  scenes/start scene, texture/build options and native script encryption settings.
- Preserve unknown extension settings when editing known fields.
- Keep tool overrides separate from original Cocos profiles and isolate iOS and
  Android settings even when task IDs match.
- Artifact support is APK only, for installation and local testing, as explicitly
  selected by the user. AAB and distribution signing UI are outside this scope.
- Default to debug APKs with the generated project's debug signing. Preserve
  existing project signing configuration without adding a release signing flow;
  report missing signing requirements clearly if a Release task is selected.

## Devices and emulators

- Separate emulator and physical-device modes with a refresh button.
- List adb devices by serial/model/status, including unauthorized and offline
  states; explain USB debugging and the phone's RSA authorization prompt.
- Always target the selected serial explicitly for install/run/log operations.
- Support USB devices and explicit wireless pairing/connection by address/code.
- List AVDs and their running state. Provide create, start, stop and delete
  controls, plus entry points to Android Studio's device management.
- Create AVDs using installed compatible system images and device definitions.
  Missing images receive a clear setup action; do not claim creation succeeded
  when downloads or required SDK tools are missing.
- Confirm destructive deletion and data clearing with the selected device/AVD
  identified. Only control emulators started or explicitly selected by the user.

## Build, install and run

- Build: export using the project's Creator CLI, then compile with the generated
  project's Gradle wrapper and the selected SDK/NDK/JDK environment.
- Build & Run: build an installable APK, install it on the selected ready device,
  resolve its launchable activity and launch it.
- Run: validate and install a compatible existing APK, then launch it without a
  Cocos export or Gradle rebuild.
- Clean & Run: validate APK and target before confirming removal of app data.
- Build and Reveal Output operate on APK artifacts only.
- Open generated Android project in the selected Studio; reveal output files.
- Validate ABI/device compatibility and artifact package identity, build variant,
  freshness and output path before installation.
- Execute long operations in workers, stream output, provide progress and cancel,
  terminate only owned subprocesses, and restore controls on every exit path.
- Do not log a successful install or launch based only on a successful build.

## Logs

- Preserve plain text and apply white for normal, red for error and yellow for
  warning output. Understand Android logcat priorities as well as compiler output.
- Provide text/severity filtering, clear, log-file location and device selection.
- Scope application logcat to the selected device and application process; handle
  process restarts and missing processes visibly.
- Report native crash/Java exception evidence from Android sources separately
  from the existing iOS crash panel.

## Implementation boundaries and verification

- Add Android backend and UI modules; reuse shared styling/log components where
  appropriate without placing Android branching throughout the iOS backend.
- Update local launcher packaging and release packaging to include added modules.
- Add meaningful tests for discovery, profile isolation, tool validation, Gradle
  command/environment construction, adb targeting, failure/cancel paths and UI
  state transitions.
- Exercise the actual Qt UI and rerun existing iOS checks.
- Validate a real Android Cocos export/build, emulator installation/launch and
  logcat when a suitable project and device are available. Physical-device
  validation requires an authorized connected phone and is reported separately.
- Documentation must distinguish implemented, tested with fixtures, emulator
  verified, physical-device verified and blocked requirements.

## Observed local environment

Read-only inspection on 2026-10-19 found Android Studio.app (2025.2), Android
Studio 2.app (2025.2), Android Studio copy.app (2021.2), the standard Android SDK,
NDK 23.1.7779620 and 25.2.9519653, multiple API platforms, and command-line tools.
These observations do not establish that a Cocos Android project currently builds.
