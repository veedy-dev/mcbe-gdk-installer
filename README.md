<p align="center">
  <img src="assets/mcbe-gdk-installer.png" width="128" alt="MCBE GDK Installer">
</p>

<h1 align="center">MCBE GDK Installer</h1>

<p align="center">Minecraft Bedrock GDK installer for Linux</p>

<p align="center">
  <a href="https://github.com/veedy-dev/mcbe-gdk-installer/releases"><img src="https://img.shields.io/github/v/release/veedy-dev/mcbe-gdk-installer" alt="Release"></a>
  <a href="https://github.com/veedy-dev/mcbe-gdk-installer/actions/workflows/shellcheck.yml"><img src="https://github.com/veedy-dev/mcbe-gdk-installer/actions/workflows/shellcheck.yml/badge.svg" alt="Checks"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/veedy-dev/mcbe-gdk-installer" alt="License"></a>
</p>

## About

MCBE GDK Installer sets up the Windows GDK build of Minecraft Bedrock on Linux
and runs it through Wine with working Xbox sign-in. You bring an authorized
game package. It takes care of the rest.

- Installs from `.zip`, `.msixvc`, or `.msixv` packages
- Decrypts `/LT` test-crypted packages locally
- Downloads and verifies the [compatibility engine](https://github.com/veedy-dev/mcbe-gdk-engine)
- Xbox sign-in from inside the game
- Keeps worlds, settings, and your account in their own profile
- Desktop app (GTK4) and a `mcbe-gdk-linux` command with the same features
- Updates the game, the engine, and itself

> [!IMPORTANT]
> This project does not include Minecraft files, credentials, licenses,
> decryption keys, or DRM bypasses. You must have authorized access to the
> build and Microsoft GDK. Only `/LT` test-crypted development packages are
> supported; retail and account-licensed packages are not.

## Installation

The bootstrap script installs the required packages on Arch, Fedora, Ubuntu,
and Debian, then installs the `mcbe-gdk-linux` command to `~/.local/bin`.

**Desktop app**

```bash
curl -fsSL https://raw.githubusercontent.com/veedy-dev/mcbe-gdk-installer/main/bootstrap.sh | bash -s -- --gui
```

**Command line only**

```bash
curl -fsSL https://raw.githubusercontent.com/veedy-dev/mcbe-gdk-installer/main/bootstrap.sh | bash -s -- --cli
```

Without `--gui` or `--cli`, the script asks. Run it again at any time to
switch.

<details>
<summary>Requirements and manual package installation</summary>

- x86_64 Linux with a Vulkan-capable GPU
- Python 3, `curl`, `tar`, `sha256sum`, `flock`
- `unzip` and `7z` (package installs)
- GTK4, Libadwaita, PyGObject (desktop app); `qrencode` optional

Arch Linux

```bash
sudo pacman -S --needed \
  gtk4 libadwaita python python-gobject python-cryptography \
  qrencode curl tar unzip 7zip
```

Fedora

```bash
sudo dnf install \
  gtk4 libadwaita python3 python3-gobject python3-cryptography \
  qrencode curl tar unzip p7zip p7zip-plugins
```

Ubuntu / Debian

```bash
sudo apt update
sudo apt install \
  python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 \
  python3-cryptography qrencode curl tar unzip 7zip
```
</details>

<details>
<summary>Running from source</summary>

```bash
git clone https://github.com/veedy-dev/mcbe-gdk-installer.git
cd mcbe-gdk-installer
./gui.sh                                            # desktop app
./easy-install.sh [--no-gui] "/path/to/package.zip" # terminal install
```

`easy-install.sh` installs the game together with the `mcbe-gdk-linux`
command. On first run it asks whether to add the desktop app to your
application menu; `--no-gui` skips both the question and the shortcut. Later
runs keep your choice. After `git pull`, run the same command again.

Already have decrypted game files? See
[Use existing game files](docs/EXISTING_FILES.md).
</details>

## Usage

### Install the game

**Desktop app:** open MCBE GDK Installer, click **Select…**, choose your
package, then click **Install**.

**Terminal:**

```bash
mcbe-gdk-linux install "/path/to/Minecraft-package.zip"
```

The first install downloads the compatibility engine and, once, the official
Microsoft GDK archive to extract the public test key. Files live in
`~/.local/share/mcbe-gdk-linux`, separate from any other Minecraft install.

### Play

Launch Minecraft from your application menu or run `mcbe-gdk-linux`. Choose
**Sign In** inside the game and complete the Microsoft device-code prompt in
your browser. You stay signed in across game, engine, and installer updates.
Sign out from the game's Profile screen.

### Update

- **New game build:** install the new package the same way. Worlds, settings,
  and your account are kept.
- **Installer and engine:** the desktop app shows an update row when a release
  is available. In the terminal, run `mcbe-gdk-linux update`.

### Choose an engine release

The newest engine release is used by default. To stay on a specific release or
try another one, use the **Compatibility engine** selector in the app or
`mcbe-gdk-linux engine VERSION`. Your choice is kept across updates. Custom
engine archives are covered in [docs/ENGINE.md](docs/ENGINE.md).

## Command line

`mcbe-gdk-linux` with no arguments launches Minecraft. Every action in the
desktop app is also available here.

| Command | Description |
| --- | --- |
| `launch` | Launch Minecraft. Only one session runs at a time. |
| `stop` | Stop the running Minecraft session. |
| `install PACKAGE` | Install the game from a package, or replace it with a newer build. Worlds, settings, and account are kept. |
| `uninstall [--remove-user-data] [--yes]` | Remove the game files. Add `--remove-user-data` to also delete worlds, settings, and the account. `--yes` skips the confirmation prompt. |
| `update` | Install available installer and engine updates. |
| `engine [VERSION\|latest\|URL]` | Show the installed engine, or switch to a release, back to `latest`, or to a custom engine archive from a GitHub release URL. |
| `login` / `logout` / `status` | Launcher-side account commands for older engine releases. Current releases sign in inside the game. |
| `gui` | Open the desktop app. |
| `recover` | Allow launching again after a crash or power loss interrupted a session. See [Troubleshooting](docs/TROUBLESHOOTING.md). |
| `setup-env [--fish]` | Print the `COM_MOJANG` environment line for external tools. |
| `help` | List all commands. |

To remove the `mcbe-gdk-linux` command and application menu entries, run
`./uninstall.sh` from a source checkout. The game and profile stay on disk.

## Documentation

- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Use existing game files](docs/EXISTING_FILES.md)
- [How `/LT` packages are extracted](docs/DECRYPTION.md)
- [Compatibility engine and custom engines](docs/ENGINE.md)
- [Contributing](CONTRIBUTING.md)

## Credits

- [mcbe-gdk-engine](https://github.com/veedy-dev/mcbe-gdk-engine) provides the
  compatibility engine, its build workflow, and release provenance.
- [BedrockOnLinux](https://github.com/Wyze3306/BedrockOnLinux) provides the
  authentication and prefix setup code, included as a pinned, MIT-licensed
  subset. Its launcher, AppImage, GUI, and game-management code are not
  installed.

## License

MIT. Vendored and runtime components retain their upstream licenses. This
project is unofficial and is not affiliated with Microsoft or Mojang.
