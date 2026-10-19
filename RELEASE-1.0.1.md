# Cocos iOS Builder 1.0.1

## Included changes

- Release configuration with separate distribution and development profiles.
- Distribution pipeline for Developer ID signing, hardened runtime, secure
  timestamps, installer signing, Apple notarization, and ticket stapling.
- Native arm64 launcher for the packaged Python/Qt app.
- System-wide installer metadata requesting administrator authorization.
- Release builds stop if signing or notarization configuration is missing.
- English user, development, and release documentation.
- Private source and separate public download repository preparation.

## Build and platform

- Apple Silicon arm64; macOS 14.4 or newer.
- Bundled Python 3.15 and PySide6-Essentials 6.12.0.
- Cocos Creator, Xcode, and compatible Simulator runtimes are external requirements.
- The currently prepared installer uses the **development** profile: ad-hoc
  app signature, unsigned installer, and **no Apple notarization**.
- Gatekeeper acceptance on another Mac is not established by a local ad-hoc
  signature check. This development build can be blocked after download.

## Validation scope

Automated checks cover backend/UI helper behavior, release configuration guards,
notarization rejection handling, signing order, and installer authorization XML.
The native launcher and an actual generated package's authorization metadata
were also checked locally. These checks do not establish successful installation
on another Mac, physical-iPhone gameplay stability, or Apple notarization.

Only the newest installer, checksum, metadata, and current documentation belong
in the download publication. Source code and previous installers are excluded
from the public repository tree.
