#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/mcbe-gdk-linux"

XVD_VERSION="0.53.0.0"
XVD_URL="https://github.com/emoose/xvdtool/releases/download/v0.53/XVDTool-${XVD_VERSION}-linux-x64.zip"
XVD_SHA256="c3a992979fec2fa1d7d6adb2a5b3647617f79735fad551dd2bab008d873c1d98"
DOTNET_VERSION="8.0.29"
DOTNET_URL="https://builds.dotnet.microsoft.com/dotnet/Runtime/${DOTNET_VERSION}/dotnet-runtime-${DOTNET_VERSION}-linux-x64.tar.gz"
DOTNET_SHA256="dba346c5c4357e1befebf14de8c8ee7f09313cc12c7c0015a4cdd4dfd0efba81"
GDK_URL="https://github.com/microsoft/GDK/releases/download/April-2026-Update-2-v2604.2.7849/GDK_2604.2.7849.zip"
GDK_SHA256="dcf28e26ebf442e16fff05ab869e37534abd85111c8bfd22401905d647688adb"

usage() {
  cat <<USAGE
Usage: $0 [--no-gui] /path/to/Minecraft-build.zip
       $0 [--no-gui] /path/to/Minecraft-package.msixvc

Decrypts and installs an authorized /LT test-crypted MCBE GDK package entirely
on Linux. Retail or account-licensed MSIXVC packages are not supported.

--no-gui  Do not add the installer GUI to the application menu.
USAGE
}

download() {
  local url="$1" output="$2" digest="$3"
  mkdir -p "$(dirname "$output")"
  if [[ -f "$output" ]] && echo "$digest  $output" | sha256sum -c - >/dev/null 2>&1; then
    return
  fi
  echo "Downloading $(basename "$output")..."
  curl -fL --retry 3 "$url" -o "$output.part"
  echo "$digest  $output.part" | sha256sum -c -
  mv "$output.part" "$output"
}

INSTALLER_SHORTCUT=""
case "${1:-}" in
  --no-gui) INSTALLER_SHORTCUT="--no-gui"; shift ;;
  -h|--help) usage; exit 0 ;;
esac
[[ $# -eq 1 ]] || { usage; exit 2; }
PACKAGE="$(realpath "$1")"
[[ -f "$PACKAGE" ]] || { echo "Build package not found: $PACKAGE" >&2; exit 1; }
case "${PACKAGE,,}" in
  *.zip|*.msixvc|*.msixv) ;;
  *) echo "Expected a .zip, .msixvc, or .msixv package." >&2; exit 2 ;;
esac
for command in curl tar unzip grep sed find python3 sha256sum 7z; do
  command -v "$command" >/dev/null || { echo "$command is required." >&2; exit 1; }
done

ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/mcbe-gdk-linux"
# Ask about the GUI shortcut once; later installs keep the earlier choice.
if [[ -z "$INSTALLER_SHORTCUT" && ! -e "$ROOT/.no-gui-shortcut" && ! -e \
      "${XDG_DATA_HOME:-$HOME/.local/share}/applications/io.github.veedydev.MCBEGDKInstaller.desktop" ]]; then
  INSTALLER_SHORTCUT="--gui"
  if [[ -t 0 ]]; then
    printf 'Add the installer GUI to the application menu? [Y/n] '
    read -r answer || answer=""
    case "${answer,,}" in
      n|no) INSTALLER_SHORTCUT="--no-gui" ;;
    esac
  fi
fi

MCBE_GDK_ROOT="$ROOT" BOL_HOME="$ROOT/profile" \
PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}" \
  python3 "$SCRIPT_DIR/scripts/runtime.py" ensure-deps || {
    echo "Install python-cryptography with your distribution package manager." >&2
    exit 1
  }

if [[ -n "${MCBE_GDK_SETUP_DIR:-}" ]]; then
  STAGE="$MCBE_GDK_SETUP_DIR"
  [[ ! -e "$STAGE" ]] || { echo "Setup directory already exists: $STAGE" >&2; exit 1; }
  mkdir -p "$STAGE"
else
  mkdir -p "$CACHE"
  STAGE="$(mktemp -d "$CACHE/setup.XXXXXX")"
fi
GAME_BACKUP=""
cleanup() {
  local status=$?
  trap - EXIT
  if [[ -n "$GAME_BACKUP" && -e "$GAME_BACKUP" ]]; then
    rm -rf "$ROOT/game"
    mv "$GAME_BACKUP" "$ROOT/game"
  fi
  rm -rf "$STAGE"
  exit "$status"
}
trap cleanup EXIT
mkdir -p "$STAGE/input" "$STAGE/output"

echo "Reading the package..."
case "${PACKAGE,,}" in
  *.zip)
    mapfile -t MSIX_LIST < <(unzip -Z1 "$PACKAGE" | grep -Ei '\.msixvc?$' || true)
    mapfile -t MANIFEST_LIST < <(unzip -Z1 "$PACKAGE" | grep -Ei 'appxmanifest\.xml$' || true)
    [[ ${#MSIX_LIST[@]} -eq 1 ]] || {
      echo "Expected exactly one MSIXVC in the archive; found ${#MSIX_LIST[@]}." >&2
      exit 1
    }
    unzip -p "$PACKAGE" "${MSIX_LIST[0]}" > "$STAGE/input/package.msixvc"
    if [[ ${#MANIFEST_LIST[@]} -ge 1 ]]; then
      unzip -p "$PACKAGE" "${MANIFEST_LIST[0]}" > "$STAGE/input/AppxManifest.xml"
    fi
    ;;
  *.msixvc|*.msixv)
    cp "$PACKAGE" "$STAGE/input/package.msixvc"
    ;;
esac

VERSION="local"
if [[ -f "$STAGE/input/AppxManifest.xml" ]]; then
  VERSION="$(grep -ioE '<Identity[^>]+Version="[^"]+"' "$STAGE/input/AppxManifest.xml" |
    head -1 | sed -E 's/.*Version="([^"]+)"/\1/' || true)"
fi
VERSION="${VERSION:-local}"
if [[ "$VERSION" =~ ^([0-9]+)\.([0-9]+)\.([0-9]{2})([0-9]{2})\.0$ ]]; then
  VERSION="${BASH_REMATCH[1]}.${BASH_REMATCH[2]}.$((10#${BASH_REMATCH[3]})).$((10#${BASH_REMATCH[4]}))"
fi

XVD_DIR="${MCBE_GDK_XVD_DIR:-$CACHE/xvdtool}"
if [[ ! -x "$XVD_DIR/XVDTool" || ! -x "$XVD_DIR/DurangoKeyExtractor" ]]; then
  download "$XVD_URL" "$CACHE/XVDTool-${XVD_VERSION}-linux-x64.zip" "$XVD_SHA256"
  mkdir -p "$XVD_DIR"
  unzip -oq "$CACHE/XVDTool-${XVD_VERSION}-linux-x64.zip" -d "$XVD_DIR"
fi

DOTNET_ROOT="${MCBE_GDK_DOTNET_ROOT:-$CACHE/dotnet}"
if [[ ! -f "$DOTNET_ROOT/host/fxr/${DOTNET_VERSION}/libhostfxr.so" ]]; then
  download "$DOTNET_URL" "$CACHE/dotnet-runtime-${DOTNET_VERSION}-linux-x64.tar.gz" "$DOTNET_SHA256"
  mkdir -p "$DOTNET_ROOT"
  tar -xzf "$CACHE/dotnet-runtime-${DOTNET_VERSION}-linux-x64.tar.gz" -C "$DOTNET_ROOT"
fi
export DOTNET_ROOT DOTNET_ROLL_FORWARD=Major

INFO="$("$XVD_DIR/XVDTool" -i -nd -ne "$STAGE/input/package.msixvc" 2>&1)"
if ! grep -qF "Test-crypted (/LT)" <<<"$INFO"; then
  echo "This package is not /LT test-crypted." >&2
  echo "Only authorized development packages using the public GDK test key can be processed on Linux." >&2
  exit 1
fi
KEY_GUID="$(sed -nE 's/.*Encryption Key [0-9]+ GUID: ([0-9a-fA-F-]+).*/\1/p' <<<"$INFO" | head -1)"
[[ "$KEY_GUID" =~ ^[0-9a-fA-F-]{36}$ ]] || {
  echo "Could not determine the package encryption-key ID." >&2
  exit 1
}

CIK="${MCBE_GDK_CIK_FILE:-$CACHE/keys/Cik/$KEY_GUID.cik}"
if [[ ! -f "$CIK" ]]; then
  GDK_ZIP="$CACHE/GDK_2604.2.7849.zip"
  GDK_DIR="$CACHE/gdk-2604.2.7849"
  download "$GDK_URL" "$GDK_ZIP" "$GDK_SHA256"
  mkdir -p "$GDK_DIR"
  7z e -y -o"$GDK_DIR" "$GDK_ZIP" 'Installers/GamingServices.appxbundle' >/dev/null
  X64_APPX="$(7z l -ba "$GDK_DIR/GamingServices.appxbundle" |
    sed -nE 's#.* ([^ ]+_x64\.appx)$#\1#p' | head -1)"
  [[ -n "$X64_APPX" ]] || { echo "Gaming Services x64 package was not found." >&2; exit 1; }
  7z e -y -o"$GDK_DIR" "$GDK_DIR/GamingServices.appxbundle" "$X64_APPX" >/dev/null
  mkdir -p "$GDK_DIR/x64" "$CACHE/keys"
  7z x -y -o"$GDK_DIR/x64" "$GDK_DIR/$X64_APPX" >/dev/null
  echo "Extracting the public GDK test key..."
  for binary in \
    "$GDK_DIR/x64/gamingservices.dll" \
    "$GDK_DIR/x64/Microsoft.Xbox.Packaging.Native.dll" \
    "$GDK_DIR/x64/drivers/xvdd.sys" \
    "$GDK_DIR/x64/xvdstreamsvc.dll"; do
    if [[ -f "$binary" ]]; then
      "$XVD_DIR/DurangoKeyExtractor" \
        -o "$CACHE/keys" "$binary" >/dev/null || true
    fi
  done
fi
[[ -f "$CIK" ]] || {
  echo "The public GDK test key required by this package was not found." >&2
  exit 1
}
if [[ -n "${GDK_DIR:-}" ]]; then
  rm -rf "$GDK_DIR"
  rm -f "$GDK_ZIP"
fi

echo "Decrypting the test package..."
"$XVD_DIR/XVDTool" -nd -cikfile "$CIK" \
  -o "$STAGE/decrypted.msixvc" -eu "$STAGE/input/package.msixvc"
echo "Extracting game content..."
mkdir -p "$STAGE/output/Content"
"$XVD_DIR/XVDTool" -nd -xf "$STAGE/output/Content" "$STAGE/decrypted.msixvc"
[[ -f "$STAGE/output/Content/Minecraft.Windows.exe" ]] || {
  echo "Extraction completed without Minecraft.Windows.exe." >&2
  exit 1
}

GAME_DIR="$ROOT/game"
mkdir -p "$(dirname "$GAME_DIR")"
NEW_GAME="$ROOT/.game-new-$$"
mv "$STAGE/output/Content" "$NEW_GAME"
if [[ -e "$GAME_DIR" ]]; then
  GAME_BACKUP="$ROOT/.game-backup-$$"
  echo "Updating the installed build; account, worlds, and profile data are preserved."
  mv "$GAME_DIR" "$GAME_BACKUP"
fi
mv "$NEW_GAME" "$GAME_DIR"
"${MCBE_GDK_INSTALLER:-$SCRIPT_DIR/install.sh}" \
  "$GAME_DIR" --version "$VERSION" ${INSTALLER_SHORTCUT:+"$INSTALLER_SHORTCUT"}
if [[ -n "$GAME_BACKUP" ]]; then
  rm -rf "$GAME_BACKUP"
  GAME_BACKUP=""
fi
echo
echo "End-to-end Linux setup complete."
