# Engine source

WineGDK source, attributed compatibility commits, pinned build inputs, release
manifests, and automated stable builds are maintained in
[veedy-dev/mcbe-gdk-engine](https://github.com/veedy-dev/mcbe-gdk-engine).

The host-side authentication and prefix setup use selected MIT-licensed
BedrockOnLinux modules pinned at commit
`27ade9259384828eb6d57d8dd6441720b2859f59`. They are included under
`auth/`; no BedrockOnLinux AppImage is installed.

## Custom engine archives

`mcbe-gdk-linux engine HTTPS_GITHUB_RELEASE_ASSET_URL` accepts `.tar.gz`
assets from GitHub releases. GitHub must publish a SHA-256 digest for the
asset. Archives are limited by compressed size, expanded size, member size,
member count, and path length, then extracted with Python's validated tar data
filter. The single archive root must contain executable `proton`,
`files/bin/wine`, and `files/bin/wineserver` files.

Custom URLs are exact, pinned selections and are not included in automatic
stable-engine update checks. Selecting `latest` or a `vX.Y.Z` release returns
to the normal `veedy-dev/mcbe-gdk-engine` release stream.

## Engine v0.2.0 and later

Releases `v0.2.0` and later from `veedy-dev/mcbe-gdk-engine` carry the
`mcbe-gdk-engine-v0.2-v1` profile. The installer records the release tag,
asset, digest, and profile beside the installed engine, and the profile
activates only when that record, the profile identifier, and the serialized
capabilities all match.

The profile:

- transactionally sets WineGDK's
  `Software\\Microsoft\\GamingServices/IgnoreVersionMismatch` registry value
  before launch and removes it when a different engine is prepared;
- uses the fixed DWORD reader covered by the engine's focused `xgameruntime`
  test for missing, wrong-type, zero, and enabled values;
- transactionally creates or updates `MicrosoftGame.Config` with the required
  Android identity and keeps original files under `profile/engine-state/`;
- reversibly disables the incompatible Windows App Runtime bootstrap DLL;
- starts Microsoft authentication only after the user selects **Sign In**
  inside Minecraft;
- pre-creates `login.json` as an owned `0600` regular file, validates the
  verification URL and code, and preserves the rendezvous file while the game
  listens;
- opens or displays the device-code prompt while a Python supervisor owns the
  monitor and game process, then removes `login.json` when the game exits;
- uses a protected `profile/device-code.txt` fallback when no dialog,
  notification, clipboard, or terminal presentation is available;
- applies or restores game changes during engine switching and again before
  launch for interrupted-operation recovery.

For these engines, `mcbe-gdk-linux login`, `logout`, and `status` explain that
account control is handled from Minecraft's Profile UI and return status 3
rather than reporting a state the launcher cannot observe. The launcher still
applies its XCurl payload and CA certificates.

The retired `v0.2.0-experimental` prerelease shipped the same runtime as a
custom asset URL. Its profile is retained so existing installations keep
working, and that selection now resolves to `latest`.
