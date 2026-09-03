# Contributing to MCBE GDK Installer

Thanks for helping. This guide covers the product boundary, repository layout,
the installer/engine contract, invariants, checks, and how releases work.
`AGENTS.md` is the same guide condensed for coding agents; keep the two in sync.

## Product boundary

This repository is the Linux installer, desktop UI, authentication/prefix
runtime, updater, and launcher for authorized Minecraft Bedrock GDK builds.
It does not contain Minecraft, credentials, private keys, or a DRM bypass.

The compatibility engine is maintained as the other half of this product in
[veedy-dev/mcbe-gdk-engine](https://github.com/veedy-dev/mcbe-gdk-engine).
Clone it next to this repository as `../mcbe-gdk-engine`. They are separate
Git repositories and separate release units; inspect both before changing a
shared contract. Matching version numbers or lockstep releases are not
required.

## Read first

- Installer overview and user contract: `README.md`
- Package extraction: `docs/DECRYPTION.md`
- Runtime troubleshooting: `docs/TROUBLESHOOTING.md`
- Vendored authentication provenance: `auth/README.md`
- Engine build/release contract: `../mcbe-gdk-engine/ENGINE.md`
- Engine pins and provenance: `../mcbe-gdk-engine/DEPENDENCIES.lock` and
  `../mcbe-gdk-engine/ATTRIBUTION.md`

## Runtime flow

```text
bootstrap.sh
  -> installs host dependencies and a verified installer release
  -> scripts/install-launchers.sh
  -> gui.sh / scripts/gui.py

easy-install.sh
  -> validates and decrypts an authorized /LT package
  -> atomically replaces game files
  -> install.sh
  -> scripts/updates.py engine (downloads and verifies an engine release)
  -> installs launchers and umu

scripts/launch.sh
  -> takes the single-instance/runtime lock
  -> scripts/runtime.py prepare
  -> auth/ prefix, Xbox, DLL, registry, and GPU-safety setup
  -> umu -> GDK-Proton-mcbe-gdk -> Minecraft.Windows.exe
```

The default installed state is
`${XDG_DATA_HOME:-$HOME/.local/share}/mcbe-gdk-linux`:

- `game/`: replaceable Minecraft files
- `engine/GDK-Proton-mcbe-gdk/`: replaceable engine release
- `engine-release`: selected engine (`latest`, `vX.Y.Z`, or a GitHub release
  asset URL)
- `profile/`: persistent Wine prefix, Xbox session, worlds/settings, caches
- `lib/`: installed copies of `auth/` and selected `scripts/*.py`
- `game-dir`, `source-dir`: pointers used by installed launchers

Normal game, installer, and engine updates must preserve `profile/`.
User-data deletion only happens through the explicit reset path.

## Source map

- `bootstrap.sh`: verified release bootstrap and host dependency install
- `easy-install.sh`: ZIP/MSIXVC/MSIXV inspection, public test-key extraction,
  decryption, staging, rollback, and game replacement
- `install.sh`: engine install via `updates.py`, settings, launchers, and umu
  setup
- `scripts/gui.py`: GTK4/Libadwaita UI and background-job coordination
- `scripts/runtime.py`: CLI bridge for auth, prefix preparation, and GPU recovery
- `scripts/updates.py`: validated GitHub metadata, checksums, safe extraction,
  engine selection, and atomic installer/engine replacement
- `scripts/removal.py`: locked stop/uninstall/reset operations
- `scripts/launch.sh`: launch environment, locking, recovery markers, and logging
- `scripts/install-launchers.sh`: installed runtime copies, commands, and XDG files
- `auth/`: pinned, adapted MIT-licensed BedrockOnLinux subset; preserve its
  provenance and license
- `tests/`: stdlib `unittest` coverage using temporary directories and mocks

If a new runtime Python module is imported after installation, also copy it
from `scripts/install-launchers.sh`; source-checkout imports alone are not
enough.

## Installer/engine contract

The installer consumes GitHub releases from `veedy-dev/mcbe-gdk-engine` and
expects:

- tag format `vX.Y.Z`
- assets `GDK-Proton-mcbe-gdk-vX.Y.Z.tar.gz` and matching `.sha256`
- archive root `GDK-Proton-mcbe-gdk/`
- `engine-manifest.json` whose `version` equals the tag
- executable `proton` and the current `files/bin/...` runtime layout

Custom engines are selected by a full GitHub release asset URL and verified
against the asset's SHA-256 digest from the GitHub API.

The engine repository owns Wine/WinRT/GameCore behavior and produces that
archive through `.engine/`. This repository owns package handling, host-side
auth/prefix orchestration, installation, updates, UI, and launch policy.

Review both repositories when changing:

- archive names, roots, manifest fields, or runtime file locations
- WineGDK registry/environment contracts or authentication handoff
- DLL/API behavior that could be fixed in Wine rather than worked around here
- dependency pins or a release transition consumed by the installer

Release an engine contract change first, then update/test the installer
consumer. Keep the old contract compatible during the transition when
practical. `MCBE_GDK_ENGINE_RELEASE=vX.Y.Z` (or an asset URL) pins installer
testing to an already-published engine release.

## Invariants

- Accept only authorized `/LT` test-crypted packages and keep all licensing
  language intact.
- Never add game files, credentials, private/decryption keys, or user data.
- Do not weaken pinned hashes, trusted-host checks, archive path/link checks,
  atomic replacement, or rollback behavior.
- Do not bypass launch locks, prefix locks, PID validation, or GPU recovery
  markers; they prevent corruption and unsafe relaunches.
- Preserve source attribution and licenses when updating `auth/` or engine
  code.
- Avoid new dependencies unless the existing shell, Python stdlib, GTK, or
  `cryptography` stack cannot do the job.

## Checks

Run the smallest relevant test first, then the repository checks before
opening a pull request:

```bash
python3 -m unittest discover -s tests -v
shellcheck bootstrap.sh easy-install.sh gui.sh install.sh uninstall.sh scripts/*.sh
python3 -m py_compile scripts/*.py auth/*.py
git diff --check
```

CI runs the same `shellcheck` set on every push. GUI and end-to-end package
tests may require GTK, network access, a real authorized package, and large
downloads; say so in the pull request instead of claiming coverage you did
not run.

For engine changes:

```bash
cd ../mcbe-gdk-engine
.engine/checks.sh
```

Any tracked engine source change makes `SOURCE-SHA256SUMS` stale. Regenerate
it with `.engine/source-manifest.py --write`, then rerun `.engine/checks.sh`.
The full engine build is the pinned GitHub Actions/Docker workflow in
`.github/workflows/engine.yml`.

## Editing style

- Follow existing Bash strict mode, quoting, staging, cleanup, and rollback
  patterns.
- Keep Python compatible with the versions exercised by CI and use stdlib
  `unittest`, temporary directories, and mocks for host/network behavior.
- Add one focused regression test for non-trivial fixes.
- Prefer a shared root-cause fix over guards in each caller.
- Keep diffs narrow; do not reformat or modernize unrelated vendored code.
- Use Conventional Commits (`fix:`, `feat:`, `chore(release):`, `test:`).

## Releases

`VERSION` is the installer release tag and must equal it. To release:

1. Commit `VERSION` as `vX.Y.Z` (`chore(release): prepare vX.Y.Z`).
2. Push to `main`. `.github/workflows/release.yml` packages the source
   archive, attests it, creates the `vX.Y.Z` tag and GitHub release, and
   uploads `mcbe-gdk-installer-vX.Y.Z.tar.gz` plus its `.sha256`.

Do not push the tag by hand; the workflow creates it. `bootstrap.sh` and
`scripts/updates.py` consume exactly those asset names.

`../mcbe-gdk-engine/VERSION` is Wine's source version, not the engine GitHub
release tag.
