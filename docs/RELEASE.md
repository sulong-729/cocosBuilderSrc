# Release and Publication Guide

## Release states

There are two explicit profiles:

| Profile | Purpose | Signature/notarization |
| --- | --- | --- |
| `distribution` (default) | Installers intended for normal distribution to other Macs | Developer ID app signature, hardened runtime, timestamp, Developer ID Installer signature, notarization, stapling, Gatekeeper assessment |
| `development` | Local packaging and explicitly labeled preview builds | Ad-hoc app signature; unsigned, non-notarized installer |

The prepared 1.0.2 installer is a **development preview** because Developer ID
identities are not currently configured on the build machine. Its filename
contains `-development`; do not describe it as Apple-approved or notarized.
If publishing this preview, mark its GitHub Release as a prerelease.

## 1. Prepare a signed distribution

1. Enroll in the Apple Developer Program and obtain the appropriate certificates.
2. Install **Developer ID Application** and **Developer ID Installer**, together
   with their corresponding private keys, in the build user's Keychain.
3. Confirm full Xcode and its command-line tools are available.
4. Save notarization credentials interactively in Keychain:

   ```sh
   xcrun notarytool store-credentials cocos-builder-notary
   ```

   Follow Apple's prompts for Apple ID, Team ID, and app-specific password.
   Do not put the password in TOML, shell history, or repository files.
5. Copy the shared configuration into an ignored local file:

   ```sh
   cp release-build.toml release-build.local.toml
   ```

6. Fill in the exact Keychain identity names and stored profile name:

   ```toml
   [distribution]
   application_identity = "Developer ID Application: Your Company (TEAMID)"
   installer_identity = "Developer ID Installer: Your Company (TEAMID)"
   notary_profile = "cocos-builder-notary"

   [development]
   ```

7. Validate before starting an expensive package build:

   ```sh
   .runtime/venv/bin/python build_release.py --config release-build.local.toml --check
   ```

Missing fields, identities, or unusable notarization credentials stop this
profile. It never silently downgrades to ad-hoc signing.

## 2. Version and verify source

Update `VERSION` in `release_info.py`, write the current release notes, and make
sure the user guide reflects the actual version and feature support.

Run:

```sh
QT_QPA_PLATFORM=offscreen .runtime/venv/bin/python -m unittest discover -s . -p 'test_*.py' -v
git diff --check
```

Record the source commit associated with the package. Save the installer outside
Git; do not commit its bundled Python/Qt files into the source repository.

## 3. Build

Signed distribution:

```sh
.runtime/venv/bin/python build_release.py --config release-build.local.toml
```

Explicit local/preview build:

```sh
.runtime/venv/bin/python build_release.py --profile development
```

The script bundles Python and Qt, compiles a native arm64 launcher, verifies
embedded Python/Qt creation, and signs code from inside out. Distribution mode
also signs the installer, waits for Apple's notarization result, staples the
accepted ticket onto the `.pkg`, validates it, and assesses the installer with
Gatekeeper. An Apple rejection stops the release and reports the submission ID
for retrieving the notarization log.

Outputs:

```text
dist/cocos builder.app
dist/release.json
build/cocos-builder-<version>-macOS-arm64.pkg
build/cocos-builder-<version>-macOS-arm64.pkg.sha256
```

Development filenames add `-development` before `.pkg`. The metadata identifies
the profile and signing state. The checksum is calculated after stapling.

The script preserves an existing output app as a backup and refuses to overwrite
an existing installer of the same name. Inspect and remove obsolete generated
outputs after verifying the new build. Do not delete source or the active runtime.

## 4. Administrator authorization

The installer targets `/Applications`, disables per-user/arbitrary installation,
uses recommended system ownership, and declares `auth="root"` on its package.
Opening the `.pkg` launches Apple's Installer, which requests administrator
authorization when necessary. macOS chooses the authentication mechanism and
can reuse authorization already granted in the current session.

This does not grant the app permanent administrator rights. It does not replace
Gatekeeper, make an unsigned app trusted, or automatically approve Apple signing.

## 5. Verify the actual artifact

For a distribution package, verify the final published `.pkg`:

```sh
pkgutil --check-signature build/cocos-builder-<version>-macOS-arm64.pkg
xcrun stapler validate build/cocos-builder-<version>-macOS-arm64.pkg
spctl --assess --type install --verbose=2 build/cocos-builder-<version>-macOS-arm64.pkg
```

From the installer directory, verify the checksum:

```sh
shasum -a 256 -c cocos-builder-<version>-macOS-arm64.pkg.sha256
```

For a development build, the unsigned/not-notarized results are expected and
must remain visible in its notes. Check the app's ad-hoc signature separately:

```sh
codesign --verify --deep --strict "dist/cocos builder.app"
```

Also install and open the downloaded distribution on another supported Mac,
then test a representative Simulator and physical-iPhone project as appropriate.
Local tests, signature checks, or extracted payload checks cannot substitute for
that verification. Record exactly which checks were performed.

The notarization ticket in this pipeline is stapled to the **installer**, not
separately to the app in `dist/`. Distribute the validated `.pkg`; do not rename
an app ZIP as a notarized release.

## 6. Separate source from installer downloads

Keep `main` and `dev` in the public `cocosBuilderSrc` repository. The independent
public `installer-cocos-builder-duo-native` repository stores the installer and user
instructions on **`dowload-v102`** for version 1.0.2.

Do not create a GitHub Release or version tag in either repository for this
download flow. GitHub automatically adds ZIP/TAR.GZ archives to tagged Releases;
branch-based downloads avoid that confusing Assets list.

The current public branch contains only:

```text
.gitattributes
.gitignore
README.md
USER_GUIDE.md
cocos-builder-1.0.2-macOS-arm64-development.pkg
cocos-builder-1.0.2-macOS-arm64-development.pkg.sha256
```

There must be no application `.py`/`.c` files, private history, credentials,
project settings, runtime directories, or old installers in the public branch.
The distributed Python app itself remains inspectable; private Git hosting is
not a way to conceal code embedded inside a downloadable app.

## 7. Publish a versioned download branch

The PKG exceeds GitHub's normal 100 MiB Git-file limit. Install Git LFS on the
maintainer's machine, then configure it locally in the download working copy:

```sh
git -C .publishing/download lfs install --local
git -C .publishing/download lfs track '*.pkg'
```

For version 1.0.2 the download branch is `dowload-v102`. For a future version,
create a new version-named branch from the current download branch, replace the
previous PKG/checksum with the verified new pair, and update README/User Guide
version names, download links, support information, and signing status. Stage
only the installer/checksum, `.gitattributes`, ignore rules, and user guides.
The source repository must continue ignoring `.publishing/` and `build/`.

Before pushing, check that the staged PKG is an LFS pointer with the expected
SHA-256 and full package size, not a 143 MB normal Git blob:

```sh
git -C .publishing/download lfs ls-files
git -C .publishing/download diff --cached --check
git -C .publishing/download diff --cached --stat
```

Commit and push the named version branch using the already configured SSH
remote. The Git LFS pre-push hook uploads the real installer data before the
branch ref is published. A Git push without a successful LFS upload does not
establish a usable download.

Validate the public branch and download the actual installer anonymously through
the README link. Verify the downloaded file's SHA-256 against its matching
checksum. Only after this succeeds, remove superseded Release/tag downloads and
obsolete local installer copies. Set the latest version branch as the public
repository's default branch so the repository URL shows the current guide.

Use `media.githubusercontent.com/media/OWNER/REPO/BRANCH/FILENAME.pkg` for the
LFS package download, or open the file on GitHub and choose **Download raw file**.
The checksum can use its normal `raw.githubusercontent.com` URL. Do not recommend
the repository ZIP as an installer: without including LFS objects it can contain
only a small pointer file rather than the actual PKG. Browser users do not need
to install Git LFS when using the verified direct package link.

Git LFS storage and bandwidth are governed by the repository owner's GitHub
plan. Keep only the current installer in the active download tree; removing an
old file from a later commit does not automatically purge older Git/LFS objects.

## References

- [Apple: Signing with Developer ID](https://developer.apple.com/developer-id/)
- [Apple: Creating distribution-signed code](https://developer.apple.com/documentation/xcode/creating-distribution-signed-code-for-the-mac/)
- [Apple: Notarizing macOS software](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)
- [GitHub: Repository limits](https://docs.github.com/en/repositories/creating-and-managing-repositories/repository-limits)
