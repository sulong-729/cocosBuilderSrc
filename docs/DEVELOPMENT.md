# Development Guide

## Repository layout and privacy

Use two separate Git repositories:

| Repository | Visibility | Branches | Contents |
| --- | --- | --- | --- |
| `cocosBuilderSrc` | Public | `main`, `dev` | Application source, tests, assets, packaging configuration, and maintainer documentation |
| `cocos-ios-builder-download` | Public | `dowload-v102` | Installer through Git LFS, checksum, README, and User Guide |

These are the intended repository names; remote URLs must be verified before
pushing. The owner chose to keep source public for 1.0.2. GitHub visibility
applies to the whole repository.

The public repository must be initialized independently and have no parent
commit or shared source history from this repository. Push only the named refs;
do not use `git push --mirror` or push every local branch to a download remote.
The local download working copy is prepared under `.publishing/download/`, which
is ignored by this source repository.

A binary distribution is not an intellectual-property protection mechanism.
This Python app embeds Python modules and third-party runtimes. Downloaders
can inspect/extract the package, even when the development repository is private.

## Source structure

| File | Responsibility |
| --- | --- |
| `app.py` | Qt desktop UI, project/device selection, background operations, user confirmation |
| `backend.py` | Cocos export, Xcode compilation, device discovery, deployment, logs, Simulator management |
| `build_config_panel.py` | Editor for supported saved Cocos iOS build options |
| `project_config.py` | Per-project/task overrides and option validation |
| `autorotate.py` | Reversible generated iOS orientation override |
| `crash_panel.py` | Passive `.ips` monitor/import and crash UI |
| `diagnostics.py` | Report parsing, matching, symbol lookup, source excerpts |
| `setup_tool.py` | Project-local Python/Qt setup and local app wrapper |
| `build_release.py` | Portable macOS app and PKG build, signing, notarization, verification |
| `release_launcher.c` | Native arm64 entry point for bundled Python |
| `release_info.py` | Version, app name, Bundle ID, and minimum macOS |
| `release-build.toml` | Shareable release profile configuration without credentials |
| `requirements.txt` | Pinned Python dependency |
| `test_*.py` | Automated unit and isolated integration checks |

## Local setup

Start with a system Python that provides `pip` for bootstrap, full Xcode for
native packaging, and Internet access for the first runtime installation.

```sh
./Launch.command
```

Alternatively, prepare the runtime/app without launching the GUI:

```sh
python3 setup_tool.py
```

The setup creates `.runtime/python/`, `.runtime/venv/`, and `.runtime/bootstrap/`
inside the checkout. The generated `.app` is excluded from Git. Run the source
UI using the project runtime after setup:

```sh
.runtime/venv/bin/python app.py
```

The packaged app is Apple Silicon-only. Source setup and automated tests on a
machine do not establish support for an Intel distribution.

## Tests and checks

Run the suite from the source repository root:

```sh
QT_QPA_PLATFORM=offscreen .runtime/venv/bin/python -m unittest discover -s . -p 'test_*.py' -v
```

Use `QT_QPA_PLATFORM=offscreen` for Qt tests without opening test windows. The
suite isolates external build/device commands where appropriate; a green test
suite is not an actual iPhone installation, a successful notarization, or a
native gameplay pass.

Before a commit:

```sh
git diff --check
git status --short
git diff --cached --stat
```

Review the staged file list. `.runtime/`, generated `.app` bundles, `build/`,
`dist/`, ZIP/PKG/DMG files, caches, logs, local credentials, and `.publishing/`
are intentionally ignored. Never use `git add -f` to stage these directories.

## Branch workflow

`main` is the reviewed release baseline. `dev` is the development branch. The
initial preparation points both names at the same initial source commit and
leaves the checkout on `dev`.

For subsequent development:

```sh
git switch dev
# Edit, test, and review the staged source changes.
git add <reviewed-source-files>
git commit -m "Describe the source change"
git push origin dev
```

After review and verification, update `main` through your normal merge or pull
request process. Never push source commits to the public download repository.

Before pushing, verify the source destination and its chosen visibility:

```sh
gh repo view OWNER/cocosBuilderSrc --json nameWithOwner,visibility,url
```

For 1.0.2 the chosen source visibility is `PUBLIC`. Configure/push only the verified source remote:

```sh
git remote add origin git@github.com:OWNER/cocosBuilderSrc.git
git push -u origin main dev
```

Replace `OWNER` with the verified GitHub account or organization; it is an example,
not a configured remote. If `origin` already exists, inspect it rather than
blindly adding or replacing it.

## Secrets and release configuration

The checked-in `release-build.toml` has empty distribution identity/profile
fields. Put your machine-specific values in an ignored copy:

```sh
cp release-build.toml release-build.local.toml
```

Use `--config release-build.local.toml` when validating/building. Certificate
private keys, Apple ID passwords, app-specific passwords, Keychain data, `.env`
files, provisioning profiles, and game XXTEA settings do not belong in source or
public download commits. Notarization credentials belong in Keychain.

Read the [Release Guide](RELEASE.md) before generating or publishing an installer.
