<p align="center">
  <img src="assets/mcbe-gdk-installer.png" width="128" alt="MCBE GDK Installer">
</p>

# MCBE GDK Installer

Minecraft Bedrock GDK builds installer on Linux with working Xbox authentication.

> Compatibility engine source and releases:
> [mcbe-gdk-engine](https://github.com/veedy-dev/mcbe-gdk-engine).

## What it does

- Accepts `.zip`, `.msixvc`, or `.msixv` packages
- Provides a desktop UI for installation, account login, and launching
- Notifies you about installer and compatibility-engine updates
- Decrypts `/LT` test-crypted development packages entirely on Linux
- Installs the latest verified MCBE-compatible GDK-Proton xuser engine
- Signs in from Minecraft's own Sign In button (launcher device-code sign-in for engines before v0.2.0)
- Launches through `umu`
- Keeps its profile separate from other Minecraft installations
- Installs XDG entries for the installer and Minecraft Bedrock

> [!IMPORTANT]
> This project does not include Minecraft files, credentials, licenses,
> decryption keys, or DRM bypasses. You must have authorized access to the
> build and Microsoft GDK.

## Requirements

### Command-line installation and launch

- x86_64 Linux
- Python 3 (`cryptography` is only needed for launcher sign-in with engines before v0.2.0)
- `curl`, `tar`, `sha256sum`, and `flock`
- `unzip` and `7z` only when installing from a package

You can install and launch the game entirely from the terminal. Engine
`v0.2.0` and later start authentication from Minecraft's own **Sign In**
button. With engines before `v0.2.0`, the login command prints the Microsoft
sign-in URL and code.

### Optional desktop UI

The graphical installer also needs GTK4, Libadwaita, and PyGObject. `qrencode`
is optional and shows a QR code during sign-in. The commands below install
everything needed for both terminal and graphical use.

### Arch Linux

```bash
sudo pacman -S --needed \
  gtk4 libadwaita python python-gobject python-cryptography \
  qrencode curl tar unzip 7zip
```

### Fedora

```bash
sudo dnf install \
  gtk4 libadwaita python3 python3-gobject python3-cryptography \
  qrencode curl tar unzip p7zip p7zip-plugins
```

### Ubuntu / Debian

```bash
sudo apt update
sudo apt install \
  python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 \
  python3-cryptography qrencode curl tar unzip 7zip
```

## Install

### Bootstrap installer

This command downloads the latest release and asks whether to install the
graphical setup application or command-line tools only:

```bash
curl -fsSL https://raw.githubusercontent.com/veedy-dev/mcbe-gdk-installer/main/bootstrap.sh | bash
```

The CLI choice skips GTK, Libadwaita, PyGObject, `qrencode`, `unzip`, and `7z`,
does not create the installer GUI shortcut, and does not open the GUI. Install
`unzip` and `7z` later if you use `easy-install.sh` with a game package.

For unattended installation, select the mode explicitly:

```bash
curl -fsSL https://raw.githubusercontent.com/veedy-dev/mcbe-gdk-installer/main/bootstrap.sh |
  bash -s -- --cli
```

Replace `--cli` with `--gui` to install the graphical setup application.

### Download the source

```bash
git clone https://github.com/veedy-dev/mcbe-gdk-installer.git
cd mcbe-gdk-installer
```

To open the graphical installer, run:

```bash
./gui.sh
```

For terminal-only use, choose one of the methods below instead.

## Use

Choose the authorized `.zip`, `.msixvc`, or `.msixv`, then click **Install**.
The installer selects the latest stable engine release, verifies its checksum,
extracts the public GDK test key locally, decrypts the package, and installs it.
The first run temporarily downloads the official Microsoft GDK archive.
Installing a newer build replaces only the game files; the isolated account,
worlds, and profile data are preserved.

Launch Minecraft and select **Sign In** inside the game. The launcher
supervises the engine's `login.json` request and presents the Microsoft URL
and code without moving the actual authentication back into the launcher or
CLI. With engines before `v0.2.0`, click **Sign in** in the installer instead
and complete the displayed Microsoft device-code flow.

When an installer or engine update is available, an update row appears above
the Package section. Select **Update** to review the release changelog, then choose
**Install updates** or **Later**. Minecraft, worlds, settings, and account data
are preserved.

The app is also available as **MCBE GDK Installer** in compatible
application launchers. Desktops that group XDG categories place it under
**Games**; launchers used with Hyprland usually expose it through search.

## Command-line install

### Install from a package

Give the installer your `.zip`, `.msixvc`, or `.msixv` package:

```bash
./easy-install.sh "/path/to/Minecraft-package.msixvc"
```

After the first install, update to a newer package without a source checkout:

```bash
mcbe-gdk-linux install "/path/to/Minecraft-package.zip"
```

Terminal installs ask whether to add the installer GUI to the application
menu. Pass `--no-gui` before the package path to skip both the prompt and that
shortcut; the Minecraft shortcut and `mcbe-gdk-linux` command are still added.

Already have the Minecraft game files? Follow
[Use existing game files](docs/EXISTING_FILES.md).

Rerun the same installation command after `git pull` to update an existing
installation.

The latest stable engine release is selected by default. Use
`mcbe-gdk-linux engine 0.1.5` to switch to `v0.1.5` without reinstalling the
game, or pick a release from the Compatibility engine selector in the setup
UI. Versions may include or omit the `v`; use `latest` to resume tracking new
stable engine releases.

### Engine v0.2.0 and later

Engine `v0.2.0` is built from the maintained public WineGDK tree with the same
pinned GDK-Proton, graphics, Debian, and Steam Runtime inputs as earlier
releases. It fixes the Gaming Services version-override reader, and the
installer applies its engine profile automatically: the Minecraft title
identity, the Windows App Runtime workaround, and WineGDK's Gaming Services
registry override are set transactionally before launch and restored when an
older engine is selected.

With these engines, `mcbe-gdk-linux login`, `logout`, and `status` do not
manage the account. Launch Minecraft, use its Profile/Sign In controls, and
complete the remote device-code prompt generated by the game. The private
`login.json` rendezvous file is preserved while the game listens and removed
after the supervised process exits.

Installations that selected the earlier `v0.2.0-experimental` asset URL now
track `latest` and receive `v0.2.0` through the normal update check.

## Commands

| Purpose | Command |
| --- | --- |
| Show command help | `mcbe-gdk-linux help` |
| Open setup UI | `./gui.sh` or `mcbe-gdk-linux gui` |
| Package-to-Linux setup | `./easy-install.sh /path/to/mcbe-gdk-build.msixvc` |
| Install or update from a package | `mcbe-gdk-linux install /path/to/mcbe-gdk-build.zip` |
| Launch Minecraft | `mcbe-gdk-linux launch` or `mcbe-gdk-linux` |
| Sign in/out (engine v0.2.0+) | Use the Profile controls inside Minecraft |
| Account status (engines before v0.2.0) | `mcbe-gdk-linux status` |
| Sign in (engines before v0.2.0) | `mcbe-gdk-linux login` |
| Sign out (engines before v0.2.0) | `mcbe-gdk-linux logout` |
| Install available updates | `mcbe-gdk-linux update` |
| Show or switch engine | `mcbe-gdk-linux engine [VERSION\|latest\|GITHUB_ASSET_URL]` |
| Recover after GPU troubleshooting | `mcbe-gdk-linux recover` |
| Print the `COM_MOJANG` environment command | `mcbe-gdk-linux setup-env` |
| Remove launchers | `./uninstall.sh` |

## Documentation

- [Use existing game files](docs/EXISTING_FILES.md)
- [Native `/LT` package extraction](docs/DECRYPTION.md)
- [Compatibility engine source](https://github.com/veedy-dev/mcbe-gdk-engine)
- [Troubleshooting](docs/TROUBLESHOOTING.md)

## Engine source

The compatibility engine source, build workflow, and release provenance live
in [mcbe-gdk-engine](https://github.com/veedy-dev/mcbe-gdk-engine). Releases
are built from the maintained source with pinned inputs, release checksums, a
manifest, focused Wine tests, and reproducible packaging.
Authentication and prefix setup use a pinned, MIT-licensed subset of
[BedrockOnLinux](https://github.com/Wyze3306/BedrockOnLinux). Its launcher,
AppImage, GUI, and game-management code are not installed.

## License

The installer and documentation are MIT licensed. Vendored and runtime
components retain their upstream licenses. This project is unofficial and is
not affiliated with Microsoft or Mojang.
