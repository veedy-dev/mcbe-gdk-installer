#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:?usage: install-launchers.sh ROOT SOURCE}"
SOURCE="${2:?usage: install-launchers.sh ROOT SOURCE}"
SHORTCUT_POLICY="${3:-}"
BIN_DIR="$HOME/.local/bin"
APPLICATIONS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"

[[ $# -le 3 ]] || { echo "usage: install-launchers.sh ROOT SOURCE [--gui|--no-gui]" >&2; exit 2; }
mkdir -p "$ROOT/lib" "$ROOT/licenses" "$BIN_DIR" "$APPLICATIONS_DIR"
case "$SHORTCUT_POLICY" in
  --gui) rm -f "$ROOT/.no-gui-shortcut" ;;
  --no-gui) touch "$ROOT/.no-gui-shortcut" ;;
  "") ;;
  *) echo "usage: install-launchers.sh ROOT SOURCE [--gui|--no-gui]" >&2; exit 2 ;;
esac
rm -rf "$ROOT/lib/auth" "$ROOT/lib/bol"
cp -a "$SOURCE/auth" "$ROOT/lib/auth"
install -m755 "$SOURCE/scripts/runtime.py" "$ROOT/lib/runtime_base.py"
install -m755 "$SOURCE/scripts/runtime_engine.py" "$ROOT/lib/runtime.py"
install -m755 "$SOURCE/scripts/gui.py" "$ROOT/lib/gui.py"
install -m755 "$SOURCE/scripts/gui_engine.py" "$ROOT/lib/gui_engine.py"
install -m755 "$SOURCE/scripts/updates.py" "$ROOT/lib/updates.py"
install -m644 "$SOURCE/scripts/removal.py" "$ROOT/lib/removal.py"
install -m755 "$SOURCE/scripts/launch.sh" "$ROOT/lib/launch.sh"
install -m755 "$SOURCE/scripts/gui-launch.sh" "$ROOT/lib/gui-launch.sh"
install -m755 "$SOURCE/scripts/auth.sh" "$ROOT/lib/auth.sh"
install -m755 "$SOURCE/scripts/recover.sh" "$ROOT/lib/recover.sh"
install -m755 "$SOURCE/scripts/rgl-env.sh" "$ROOT/lib/rgl-env.sh"
install -m644 "$SOURCE/auth/LICENSE" "$ROOT/licenses/BedrockOnLinux-LICENSE"
printf '%s\n' "$SOURCE" >"$ROOT/source-dir"

rm -f "$BIN_DIR/mcbe-gdk-linux" \
  "$BIN_DIR/mcbe-gdk-linux-gui" \
  "$BIN_DIR/mcbe-gdk-linux-auth" \
  "$BIN_DIR/mcbe-gdk-linux-login" \
  "$BIN_DIR/mcbe-gdk-linux-logout" \
  "$BIN_DIR/mcbe-gdk-linux-config" \
  "$BIN_DIR/mcbe-gdk-linux-recover" \
  "$BIN_DIR/mcbe-gdk-linux-regolith-env" \
  "$BIN_DIR/mcbe-gdk-linux-rgl-env"
install -m755 "$SOURCE/scripts/cli.sh" "$BIN_DIR/mcbe-gdk-linux"

ICON="$ROOT/mcbe-gdk-installer.png"
ICON_VALUE="applications-games"
if [[ -f "$SOURCE/assets/mcbe-gdk-installer.png" ]]; then
  install -m644 "$SOURCE/assets/mcbe-gdk-installer.png" "$ICON"
  ICON_VALUE="$ICON"
fi

MINECRAFT_ICON="$ROOT/minecraft-bedrock.png"
MINECRAFT_ICON_VALUE="applications-games"
if [[ -f "$ROOT/game/StoreLogo.png" ]]; then
  install -m644 "$ROOT/game/StoreLogo.png" "$MINECRAFT_ICON"
  MINECRAFT_ICON_VALUE="$MINECRAFT_ICON"
elif [[ -f "$MINECRAFT_ICON" ]]; then
  MINECRAFT_ICON_VALUE="$MINECRAFT_ICON"
fi

rm -f "$APPLICATIONS_DIR/mcbe-gdk-linux.desktop" \
  "$APPLICATIONS_DIR/io.github.veedydev.MCBEGDKInstaller.desktop"
if [[ ! -f "$ROOT/.no-gui-shortcut" ]]; then
  cat >"$APPLICATIONS_DIR/io.github.veedydev.MCBEGDKInstaller.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=MCBE GDK Installer
GenericName=Minecraft Bedrock GDK Installer
Comment=Install, authenticate, and launch Minecraft Bedrock GDK builds on Linux
Exec=$BIN_DIR/mcbe-gdk-linux gui
Icon=$ICON_VALUE
Terminal=false
Categories=Game;
Keywords=Minecraft;Bedrock;GDK;Xbox;Installer;Linux;
X-KDE-Keywords=minecraft,bedrock,gdk,xbox,installer
StartupNotify=true
StartupWMClass=io.github.veedydev.MCBEGDKInstaller
EOF
fi

cat >"$APPLICATIONS_DIR/io.github.veedydev.MinecraftBedrock.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Minecraft Bedrock
Comment=Launch Minecraft Bedrock
Exec=$BIN_DIR/mcbe-gdk-linux launch
Icon=$MINECRAFT_ICON_VALUE
Terminal=false
Categories=Game;
Keywords=Minecraft;Bedrock;Xbox;Game;
StartupNotify=true
EOF

if command -v update-desktop-database >/dev/null; then
  update-desktop-database "$APPLICATIONS_DIR" >/dev/null 2>&1 || true
fi
if command -v kbuildsycoca6 >/dev/null; then
  kbuildsycoca6 --noincremental >/dev/null 2>&1 || true
fi
