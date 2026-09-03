<p align="center">
  <img src="assets/mcbe-gdk-installer.png" width="128" alt="MCBE GDK Installer">
</p>

# MCBE GDK Installer

Run Minecraft Bedrock GDK builds on Linux with working Xbox sign-in. You
supply an authorized game package. The installer decrypts it, installs the
compatibility engine, keeps a separate profile for worlds and settings, and
updates itself.

> [!IMPORTANT]
> This project does not include Minecraft files, credentials, licenses,
> decryption keys, or DRM bypasses. You must have authorized access to the
> build and Microsoft GDK. Only `/LT` test-crypted development packages are
> supported; retail and account-licensed packages are not.

## Step 1: install the installer

One command. It installs the packages your distribution needs (Arch, Fedora,
Ubuntu, Debian) and puts the `mcbe-gdk-linux` command in `~/.local/bin`.

With the desktop app:

```bash
curl -fsSL https://raw.githubusercontent.com/veedy-dev/mcbe-gdk-installer/main/bootstrap.sh | bash -s -- --gui
```

Command line only, no GTK:

```bash
curl -fsSL https://raw.githubusercontent.com/veedy-dev/mcbe-gdk-installer/main/bootstrap.sh | bash -s -- --cli
```

Run it without `--gui` or `--cli` and it asks which one you want. You can
change your mind later by running it again.

<details>
<summary>Install the packages yourself instead</summary>

Everything needs x86_64 Linux, a Vulkan-capable GPU, Python 3, `curl`, `tar`,
`sha256sum`, and `flock`. Package installs also need `unzip` and `7z`. The
desktop app needs GTK4, Libadwaita, and PyGObject; `qrencode` is optional.

Arch Linux:

```bash
sudo pacman -S --needed \
  gtk4 libadwaita python python-gobject python-cryptography \
  qrencode curl tar unzip 7zip
```

Fedora:

```bash
sudo dnf install \
  gtk4 libadwaita python3 python3-gobject python3-cryptography \
  qrencode curl tar unzip p7zip p7zip-plugins
```

Ubuntu / Debian:

```bash
sudo apt update
sudo apt install \
  python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 \
  python3-cryptography qrencode curl tar unzip 7zip
```
</details>

<details>
<summary>Run from a git checkout instead</summary>

```bash
git clone https://github.com/veedy-dev/mcbe-gdk-installer.git
cd mcbe-gdk-installer
./gui.sh                                            # desktop app
./easy-install.sh [--no-gui] "/path/to/package.zip" # terminal install
```

`easy-install.sh` installs the game and the `mcbe-gdk-linux` command. The
first run asks whether to add the desktop app to your application menu;
`--no-gui` skips the question and the shortcut. Later runs keep whatever you
chose. After `git pull`, run the same command again to update.

Already have decrypted game files? See
[Use existing game files](docs/EXISTING_FILES.md).
</details>

## Step 2: install the game

Desktop app: open MCBE GDK Installer from your application menu (or run
`mcbe-gdk-linux gui`), click Select, pick your `.zip`, `.msixvc`, or `.msixv`,
then click Install.

Terminal:

```bash
mcbe-gdk-linux install "/path/to/Minecraft-package.zip"
```

The first install downloads the compatibility engine and, once, the official
Microsoft GDK archive to extract the public test key. Everything is stored in
`~/.local/share/mcbe-gdk-linux`, apart from any other Minecraft install.

## Step 3: play

Start Minecraft from the application menu or run `mcbe-gdk-linux`. Choose
Sign In inside the game. A Microsoft device-code prompt opens; finish it in
your browser. The session is saved in the profile and survives game, engine,
and installer updates. Sign out from the game's Profile screen.

Older engine releases sign in from the installer instead, with the Sign in
button in the app or `mcbe-gdk-linux login`.

## Updating

New game build? Do step 2 again with the new package. Only the game files
change; worlds, settings, and your account stay.

Installer and engine updates show up as an update row in the app. In the
terminal, run `mcbe-gdk-linux update`.

## Compatibility engine

The engine is the Wine-based runtime that runs Minecraft. It is built and
released at [mcbe-gdk-engine](https://github.com/veedy-dev/mcbe-gdk-engine).
The newest release is used by default. To stay on a specific release, or to
try another one without reinstalling the game, use the Compatibility engine
selector in the app or `mcbe-gdk-linux engine`. The selection is kept across
updates. `docs/ENGINE.md` covers custom engine archives.

## Commands

`mcbe-gdk-linux` with no arguments launches Minecraft. Every action in the
desktop app has a terminal equivalent.

### Game

`mcbe-gdk-linux launch`
Start Minecraft. Refuses to start a second copy while one is running.

`mcbe-gdk-linux stop`
Stop the running Minecraft session.

`mcbe-gdk-linux install PACKAGE`
Install the game from a `.zip`, `.msixvc`, or `.msixv` package, or replace
the installed game with a newer build. Worlds, settings, and the account are
kept.

`mcbe-gdk-linux uninstall`
Remove the game files. Worlds, settings, and the account are kept, so a later
`install` picks them up again. Add `--remove-user-data` to delete those too.
The command asks for confirmation; add `--yes` to skip the question in
scripts.

### Updates and engine

`mcbe-gdk-linux update`
Check GitHub for a newer installer and engine release and install what is
available.

`mcbe-gdk-linux engine`
Show the installed engine and which release is selected.

`mcbe-gdk-linux engine VERSION`
Install a specific engine release and stay on it. `mcbe-gdk-linux engine
latest` goes back to following new releases. A GitHub release asset URL
installs a custom engine archive.

### Account

`mcbe-gdk-linux login`, `logout`, `status`
Launcher-side sign-in for older engine releases. Current releases sign in
inside Minecraft, and these commands tell you so.

### Other

`mcbe-gdk-linux gui`
Open the desktop app.

`mcbe-gdk-linux recover`
Allow launching again after a crash or power loss interrupted a game session.
The launcher blocks new launches until you confirm the graphics driver is
healthy; see [Troubleshooting](docs/TROUBLESHOOTING.md).

`mcbe-gdk-linux setup-env`
Print the `COM_MOJANG` environment line for tools like Regolith. Add
`--fish` for fish shell syntax.

`mcbe-gdk-linux help`
List these commands.

`./uninstall.sh`
From a git checkout: remove the `mcbe-gdk-linux` command and the application
menu entries. The game and profile stay on disk.

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
