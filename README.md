<p align="center">
  <img src="assets/mcbe-gdk-installer.png" width="128" alt="MCBE GDK Installer">
</p>

# MCBE GDK Installer

Install and run Minecraft Bedrock GDK builds on Linux, with working Xbox
sign-in. Bring your own authorized package; the installer handles decryption,
the compatibility engine, the isolated profile, and updates.

> [!IMPORTANT]
> This project does not include Minecraft files, credentials, licenses,
> decryption keys, or DRM bypasses. You must have authorized access to the
> build and Microsoft GDK. Only `/LT` test-crypted development packages are
> supported; retail and account-licensed packages are not.

## Quick start

1. Install the launcher (one line, no clone needed). It installs the
   distribution packages it needs and asks whether you want the desktop UI:

   ```bash
   curl -fsSL https://raw.githubusercontent.com/veedy-dev/mcbe-gdk-installer/main/bootstrap.sh | bash
   ```

2. Install your game package:

   - **Desktop UI**: open **MCBE GDK Installer** (or run `mcbe-gdk-linux gui`),
     click **Select…**, pick the `.zip`, `.msixvc`, or `.msixv`, then
     **Install**.
   - **Terminal**:

     ```bash
     mcbe-gdk-linux install "/path/to/Minecraft-package.zip"
     ```

3. Launch Minecraft from the app menu or with `mcbe-gdk-linux`, then choose
   **Sign In** inside the game. A Microsoft device-code prompt opens; complete
   it in your browser and you are signed in.

The first install downloads the compatibility engine and, once, the official
Microsoft GDK archive for the public test key. Everything lives under
`~/.local/share/mcbe-gdk-linux`, separate from any other Minecraft install.

## Updating

- **New game build**: repeat step 2 with the new package. Only the game files
  are replaced; your account, worlds, and settings stay.
- **Installer or engine**: the UI shows an update row when a release is
  available, or run `mcbe-gdk-linux update`. Profile data is preserved.

## Supported platforms

- x86_64 Linux with a Vulkan-capable GPU
- Python 3
- `curl`, `tar`, `sha256sum`, `flock`; `unzip` and `7z` for package installs
- Desktop UI only: GTK4, Libadwaita, PyGObject; `qrencode` optional

`bootstrap.sh` installs these on Arch, Fedora, and Ubuntu/Debian. To install
them yourself:

<details>
<summary>Arch Linux</summary>

```bash
sudo pacman -S --needed \
  gtk4 libadwaita python python-gobject python-cryptography \
  qrencode curl tar unzip 7zip
```
</details>

<details>
<summary>Fedora</summary>

```bash
sudo dnf install \
  gtk4 libadwaita python3 python3-gobject python3-cryptography \
  qrencode curl tar unzip p7zip p7zip-plugins
```
</details>

<details>
<summary>Ubuntu / Debian</summary>

```bash
sudo apt update
sudo apt install \
  python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 \
  python3-cryptography qrencode curl tar unzip 7zip
```
</details>

## Install options

### Unattended bootstrap

Pick the mode up front instead of answering the prompt:

```bash
curl -fsSL https://raw.githubusercontent.com/veedy-dev/mcbe-gdk-installer/main/bootstrap.sh | bash -s -- --cli
```

`--cli` skips the GTK stack, `unzip`, and `7z` and adds no UI shortcut;
`--gui` installs the desktop application and opens it.

### From a source checkout

```bash
git clone https://github.com/veedy-dev/mcbe-gdk-installer.git
cd mcbe-gdk-installer
./gui.sh                                   # desktop UI
./easy-install.sh "/path/to/package.zip"   # or terminal install
```

Terminal installs ask whether to add the UI to the application menu; pass
`--no-gui` before the package path to skip that. Rerun the same command after
`git pull` to update.

Already have decrypted game files? See
[Use existing game files](docs/EXISTING_FILES.md).

## Accounts and sign-in

Sign-in happens inside Minecraft: choose **Sign In**, and the launcher
presents the Microsoft URL and code the game requested. Sign out from the
game's Profile screen. The Xbox session is stored in the isolated profile and
survives game, engine, and installer updates.

Older engine releases sign in from the installer instead: use the **Sign in**
button in the UI or `mcbe-gdk-linux login`, which prints the device code in
the terminal.

## Compatibility engine

The compatibility engine is the Wine-based runtime that runs Minecraft. It is
built and released at
[mcbe-gdk-engine](https://github.com/veedy-dev/mcbe-gdk-engine); the newest
release is used by default and installed automatically.

To stay on a specific release or switch between them without reinstalling the
game, use the **Compatibility engine** selector in the UI or:

```bash
mcbe-gdk-linux engine            # show installed and selected engine
mcbe-gdk-linux engine VERSION    # use a specific release
mcbe-gdk-linux engine latest     # follow new releases again
```

`engine` also accepts a GitHub release asset URL for a custom `.tar.gz`
engine; see [docs/ENGINE.md](docs/ENGINE.md) for what is verified and how
engine profiles apply.

## Command reference

| Command | Purpose |
| --- | --- |
| `mcbe-gdk-linux` or `mcbe-gdk-linux launch` | Launch Minecraft |
| `mcbe-gdk-linux gui` | Open the setup UI |
| `mcbe-gdk-linux install [--no-gui] PACKAGE` | Install or update the game from a package |
| `mcbe-gdk-linux update` | Install available installer and engine updates |
| `mcbe-gdk-linux engine [VERSION\|latest\|URL]` | Show or switch the compatibility engine |
| `mcbe-gdk-linux login` / `logout` / `status` | Launcher account commands for older engines |
| `mcbe-gdk-linux recover` | Allow launching again after an interrupted GPU session (see [Troubleshooting](docs/TROUBLESHOOTING.md)) |
| `mcbe-gdk-linux setup-env` | Print the `COM_MOJANG` environment command |
| `mcbe-gdk-linux help` | Show all commands |
| `./uninstall.sh` | Remove launchers and shortcuts |

## Documentation

- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Use existing game files](docs/EXISTING_FILES.md)
- [How `/LT` packages are extracted](docs/DECRYPTION.md)
- [Compatibility engine and custom engines](docs/ENGINE.md)
- [Contributing](CONTRIBUTING.md)

## Credits and license

The compatibility engine source, build workflow, and release provenance live
in [mcbe-gdk-engine](https://github.com/veedy-dev/mcbe-gdk-engine).
Authentication and prefix setup use a pinned, MIT-licensed subset of
[BedrockOnLinux](https://github.com/Wyze3306/BedrockOnLinux); its launcher,
AppImage, GUI, and game-management code are not installed.

The installer and documentation are MIT licensed. Vendored and runtime
components retain their upstream licenses. This project is unofficial and is
not affiliated with Microsoft or Mojang.
