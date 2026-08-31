#!/usr/bin/env bash
set -euo pipefail

REPO="veedy-dev/mcbe-gdk-installer"
SOURCE_DIR="${MCBE_GDK_SOURCE_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/mcbe-gdk-installer/source}"
ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/mcbe-gdk-linux"

usage() {
  cat <<USAGE
Usage: bootstrap.sh [--gui|--cli]

Without an option, interactively choose the graphical or command-line install.
--gui  Install desktop UI dependencies and open the setup application.
--cli  Install command-line dependencies without the setup application.
USAGE
}

INSTALL_MODE=""
set_install_mode() {
  local requested="$1"
  if [[ -n "$INSTALL_MODE" && "$INSTALL_MODE" != "$requested" ]]; then
    echo "Choose only one install mode: --gui or --cli." >&2
    exit 2
  fi
  INSTALL_MODE="$requested"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --gui) set_install_mode gui ;;
    --cli) set_install_mode cli ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

select_install_mode() {
  local input output choice using_tty=0
  if [[ -t 0 ]]; then
    input="/dev/stdin"
    output="/dev/stdout"
  elif { exec 3<>/dev/tty; } 2>/dev/null; then
    input="/dev/fd/3"
    output="/dev/fd/3"
    using_tty=1
  else
    INSTALL_MODE="gui"
    return
  fi

  while true; do
    cat >"$output" <<'PROMPT'
Install MCBE GDK:
  1) Graphical setup (GUI)
  2) Command line only (CLI)
Choose [1]: 
PROMPT
    IFS= read -r choice <"$input" || choice=""
    case "${choice,,}" in
      ""|1|g|gui)
        INSTALL_MODE="gui"
        if (( using_tty )); then exec 3>&-; fi
        return
        ;;
      2|c|cli)
        INSTALL_MODE="cli"
        if (( using_tty )); then exec 3>&-; fi
        return
        ;;
      *) echo "Enter 1 for GUI or 2 for CLI." >"$output" ;;
    esac
  done
}

[[ -n "$INSTALL_MODE" ]] || select_install_mode

run_root() {
  if (( EUID == 0 )); then
    "$@"
  elif command -v sudo >/dev/null; then
    sudo "$@"
  else
    echo "sudo is required to install dependencies." >&2
    exit 1
  fi
}

runtime_dependencies_ready() {
  local command
  for command in python3 curl tar sha256sum flock; do
    command -v "$command" >/dev/null || return 1
  done
  python3 - <<'PY' >/dev/null 2>&1
from cryptography.fernet import Fernet
PY
}

gui_dependencies_ready() {
  local command
  for command in unzip 7z; do
    command -v "$command" >/dev/null || return 1
  done
  python3 - <<'PY' >/dev/null 2>&1
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk
PY
}

dependencies_ready() {
  runtime_dependencies_ready || return 1
  [[ "$INSTALL_MODE" == "cli" ]] || gui_dependencies_ready
}

install_dependencies() {
  local -a packages
  echo "Installing $INSTALL_MODE dependencies..."
  if command -v pacman >/dev/null; then
    packages=(python python-cryptography curl tar coreutils util-linux)
    if [[ "$INSTALL_MODE" == "gui" ]]; then
      packages+=(
        unzip 7zip gtk4 libadwaita python-gobject qrencode
      )
    fi
    run_root pacman -S --needed "${packages[@]}"
  elif command -v dnf >/dev/null; then
    packages=(
      python3 python3-cryptography curl tar coreutils util-linux
    )
    if [[ "$INSTALL_MODE" == "gui" ]]; then
      packages+=(
        unzip p7zip p7zip-plugins gtk4 libadwaita python3-gobject qrencode
      )
    fi
    run_root dnf install -y "${packages[@]}"
  elif command -v apt-get >/dev/null; then
    packages=(
      python3 python3-cryptography curl tar coreutils util-linux
    )
    if [[ "$INSTALL_MODE" == "gui" ]]; then
      packages+=(
        unzip 7zip python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 qrencode
      )
    fi
    run_root apt-get update
    run_root apt-get install -y "${packages[@]}"
  else
    echo "Unsupported package manager. Install the dependencies listed at:" >&2
    echo "https://github.com/$REPO#requirements" >&2
    exit 1
  fi
}

[[ "$(uname -m)" == "x86_64" ]] || {
  echo "MCBE GDK Installer currently requires x86_64 Linux." >&2
  exit 1
}

dependencies_ready || install_dependencies
dependencies_ready || {
  echo "Required dependencies are still missing." >&2
  exit 1
}

parent="$(dirname "$SOURCE_DIR")"
mkdir -p "$parent"
stage="$(mktemp -d "$parent/.bootstrap.XXXXXX")"
trap 'rm -rf "$stage"' EXIT

echo "Downloading MCBE GDK Installer..."
curl -fsSL --retry 3 \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  "https://api.github.com/repos/$REPO/releases/latest" \
  -o "$stage/release.json"
mapfile -t release < <(
  python3 - "$stage/release.json" "$REPO" <<'PY'
import json
import re
import sys
from urllib.parse import urlparse

data = json.load(open(sys.argv[1], encoding="utf-8"))
repo = sys.argv[2]
tag = str(data["tag_name"])
if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
    raise SystemExit("The latest installer release has an invalid version.")
names = [
    f"mcbe-gdk-installer-{tag}.tar.gz",
    f"mcbe-gdk-installer-{tag}.tar.gz.sha256",
]
assets = {
    str(asset["name"]): str(asset["browser_download_url"])
    for asset in data.get("assets", [])
}
print(tag)
for name in names:
    url = assets.get(name, "")
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or f"/{repo}/releases/download/{tag}/" not in parsed.path
    ):
        raise SystemExit(f"The latest installer release is missing {name}.")
    print(url)
PY
)
tag="${release[0]}"
archive="mcbe-gdk-installer-$tag.tar.gz"
curl -fL --retry 3 "${release[1]}" -o "$stage/$archive"
curl -fL --retry 3 "${release[2]}" -o "$stage/$archive.sha256"
(cd "$stage" && sha256sum -c "$archive.sha256")
tar -xzf "$stage/$archive" -C "$stage"
source="$stage/mcbe-gdk-installer"
[[ "$(<"$source/VERSION")" == "$tag" ]] || {
  echo "Installer archive version does not match $tag." >&2
  exit 1
}
touch "$source/.mcbe-managed-source"

backup="$SOURCE_DIR.previous"
rm -rf "$backup"
[[ ! -e "$SOURCE_DIR" ]] || mv "$SOURCE_DIR" "$backup"
if mv "$source" "$SOURCE_DIR"; then
  rm -rf "$backup"
else
  [[ ! -e "$backup" ]] || mv "$backup" "$SOURCE_DIR"
  exit 1
fi

echo "Installing MCBE GDK launchers..."
launcher_args=("$ROOT" "$SOURCE_DIR")
if [[ "$INSTALL_MODE" == "cli" ]]; then
  launcher_args+=(--no-gui)
else
  launcher_args+=(--gui)
fi
"$SOURCE_DIR/scripts/install-launchers.sh" "${launcher_args[@]}"

if [[ "$INSTALL_MODE" == "gui" ]]; then
  echo "Opening MCBE GDK Installer..."
  exec "$SOURCE_DIR/gui.sh"
fi

echo
echo "MCBE GDK command-line tools installed."
echo "Run: mcbe-gdk-linux help"
