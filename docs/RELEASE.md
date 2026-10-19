# Release and Publication Guide

## Release states

There are two explicit profiles:

| Profile | Purpose | Signature/notarization |
| --- | --- | --- |
| `distribution` (default) | Installers intended for normal distribution to other Macs | Developer ID app signature, hardened runtime, timestamp, Developer ID Installer signature, notarization, stapling, Gatekeeper assessment |
| `development` | Local packaging and explicitly labeled preview builds | Ad-hoc app signature; unsigned, non-notarized installer |

The prepared 1.0.1 installer is a **development preview** because Developer ID
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
Git; do not commit its bundled Python/Qt files into the private source repository.

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

## 6. Separate private source from public downloads

GitHub does not provide public/private visibility per branch. Keep `main`/`dev`
in the private source repository and initialize the public repository separately
with the branch name **`dowload`** (this spelling is intentional).

The public branch contains only:

```text
README.md
USER_GUIDE.md
.gitignore
```

The public tree must have no `.py`, `.c`, signing credentials, project settings,
private source history, runtime directory, or previous installer. The app package
still contains inspectable Python modules; private Git hosting does not make
code inside a downloadable package secret.

A PKG of this tool exceeds GitHub's 100 MiB normal-file limit, so upload the PKG
as a **GitHub Release asset** rather than a normal Git blob. The branch stores
the user guides and links to the release assets. Release assets are
not part of the branch's Git history.

## 7. Publish only the newest build

### Keep source out of release archives

Publish version tags and Releases only in the public download repository. Do
not create version tags or Releases in the private source repository: GitHub
would automatically generate source archives from those commits.

The old source-repository release workflow has been removed. The private source
repository keeps its `main` and `dev` branches and source history; the independent
public `dowload` branch contains only user documentation. The public release's
Assets contain only the installer and its checksum, with usage instructions in
the release body and linked User Guide.

GitHub always displays automatic ZIP/TAR.GZ source archive links for tagged
Releases. In the public download repository those archives contain only the
README, User Guide, and ignore rules. They contain no application source files
or private repository history and are not installation packages.

### Public download-repository publication

The commands below require an authenticated GitHub CLI (`gh`) with write access.
Replace example owner/repository/version names with verified values. These are
maintainer instructions; they do not mean a remote publication has occurred.

1. Check the private source and public download repository visibility.
2. Commit verified source to the private `main`/`dev` workflow.
3. Update the independent `dowload` working copy with only current documentation,
   and installation instructions. Keep the installer and checksum in Release
   assets, and describe signing status/support in the release body.
4. Commit and push only `dowload` to the download repository.
5. Create the new release with its installer and matching checksum:

   ```sh
   gh release create v1.0.1 \
     build/cocos-builder-1.0.1-macOS-arm64-development.pkg \
     build/cocos-builder-1.0.1-macOS-arm64-development.pkg.sha256 \
     --repo OWNER/cocos-ios-builder-download \
     --target dowload \
     --title "Cocos iOS Builder 1.0.1 — Development Preview" \
     --notes-file RELEASE-1.0.1.md \
     --prerelease
   ```

   For a notarized distribution, use its actual filename and accurate signing
   notes. Remove `--prerelease` only when the release has the intended validation.
6. Verify the published page, asset size, and metadata. Download the asset again
   and verify its SHA-256 against the matching checksum.
7. List releases and explicitly identify older build releases in this download
   repository. Delete those releases/assets and their old release tags after
   confirming the newest download is valid. Example for a known obsolete tag:

   ```sh
   gh release delete OLD_RELEASE_TAG --cleanup-tag --yes --repo OWNER/cocos-ios-builder-download
   ```

   Use the exact obsolete tag; never apply this to the newest release or the
   private source repository. If releases are immutable and deletion is blocked,
   report that limitation rather than claiming old assets were removed.
8. Delete obsolete local generated `.pkg` files and `*-previous*.app` backups,
   retaining only the newest package/checksum and current built app. Exclude
   `.runtime/` and source files from this cleanup.

A fresh download repository starts without old installers or source history.
For future updates, deleting a tracked file in a new commit does not remove it
from older commits. Keeping binaries exclusively in Release assets makes the
latest-only asset policy manageable without rewriting source history.

## References

- [Apple: Signing with Developer ID](https://developer.apple.com/developer-id/)
- [Apple: Creating distribution-signed code](https://developer.apple.com/documentation/xcode/creating-distribution-signed-code-for-the-mac/)
- [Apple: Notarizing macOS software](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)
- [GitHub: Repository limits](https://docs.github.com/en/repositories/creating-and-managing-repositories/repository-limits)
