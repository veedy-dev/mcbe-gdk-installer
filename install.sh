#!/usr/bin/env bash
set -euo pipefail

ENGINE_REPO="veedy-dev/mcbe-gdk-engine"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/mcbe-gdk-linux"
export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"

usage() {
  cat <<USAGE
Usage: $0 /path/to/decrypted/Content [--version VERSION] [--gui|--no-gui]

The directory must contain Minecraft.Windows.exe from an authorized,
decrypted Minecraft Bedrock GDK installation. This installer does not
contain, download, decrypt, or bypass licensing for Minecraft game files.
USAGE
}

[[ $# -ge 1 ]] || { usage; exit 2; }
CONTENT="${1%/}"; shift
VERSION="local"
SHORTCUT_POLICY=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --version) VERSION="${2:?missing version}"; shift 2 ;;
    --gui|--no-gui) SHORTCUT_POLICY="$1"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done
CONTENT="$(realpath "$CONTENT")"
[[ -f "$CONTENT/Minecraft.Windows.exe" ]] || {
  echo "Error: $CONTENT/Minecraft.Windows.exe was not found." >&2; exit 1;
}
command -v curl >/dev/null || { echo "curl is required." >&2; exit 1; }
command -v tar >/dev/null || { echo "tar is required." >&2; exit 1; }
command -v sha256sum >/dev/null || { echo "sha256sum is required." >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required." >&2; exit 1; }

if [[ -n "${MCBE_GDK_ENGINE_RELEASE:-}" ]]; then
  ENGINE_SELECTION="$MCBE_GDK_ENGINE_RELEASE"
elif [[ -f "$ROOT/engine-release" ]]; then
  ENGINE_SELECTION="$(cat "$ROOT/engine-release")"
else
  ENGINE_SELECTION="latest"
fi
if [[ "$ENGINE_SELECTION" == "latest" ]]; then
  ENGINE_RELEASE="$(
    python3 "$SCRIPT_DIR/scripts/updates.py" latest-tag "$ENGINE_REPO"
  )"
else
  ENGINE_RELEASE="$ENGINE_SELECTION"
fi
[[ "$ENGINE_RELEASE" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
  echo "The engine release version is invalid: $ENGINE_RELEASE" >&2
  exit 1
}
ENGINE_ASSET="GDK-Proton-mcbe-gdk-${ENGINE_RELEASE}.tar.gz"

mkdir -p \
  "$ROOT/engine" "$ROOT/profile" "$ROOT/lib" "$ROOT/licenses"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

MCBE_GDK_ROOT="$ROOT" BOL_HOME="$ROOT/profile" \
PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}" \
  python3 "$SCRIPT_DIR/scripts/runtime.py" ensure-deps || {
    echo "Install python-cryptography with your distribution package manager." >&2
    exit 1
  }

json_escape() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  printf '%s' "$value"
}

# Restore the runtime DLL disabled by earlier installer releases.
if [[ ! -f "$CONTENT/Microsoft.WindowsAppRuntime.Bootstrap.dll" &&
      -f "$CONTENT/Microsoft.WindowsAppRuntime.Bootstrap.dll.disabled" ]]; then
  mv "$CONTENT/Microsoft.WindowsAppRuntime.Bootstrap.dll.disabled" \
     "$CONTENT/Microsoft.WindowsAppRuntime.Bootstrap.dll"
fi

echo "Downloading the MCBE GDK compatibility engine..."
RELEASE_URL="https://github.com/$ENGINE_REPO/releases/download/$ENGINE_RELEASE"
curl -fL --retry 3 "$RELEASE_URL/$ENGINE_ASSET" -o "$TMP/$ENGINE_ASSET"
echo "Verifying the MCBE GDK compatibility engine..."
curl -fL --retry 3 "$RELEASE_URL/$ENGINE_ASSET.sha256" -o "$TMP/$ENGINE_ASSET.sha256"
(cd "$TMP" && sha256sum -c "$ENGINE_ASSET.sha256")
echo "Installing the MCBE GDK compatibility engine..."
rm -rf "$ROOT/engine/GDK-Proton-mcbe-gdk"
tar -xzf "$TMP/$ENGINE_ASSET" -C "$ROOT/engine"
printf '%s\n' "$ENGINE_SELECTION" >"$ROOT/engine-release"

launcher_args=("$ROOT" "$SCRIPT_DIR")
[[ -z "$SHORTCUT_POLICY" ]] || launcher_args+=("$SHORTCUT_POLICY")
"$SCRIPT_DIR/scripts/install-launchers.sh" "${launcher_args[@]}"
printf '%s\n' "$CONTENT" > "$ROOT/game-dir"
ln -sfn "$CONTENT" "$ROOT/profile/content"

ROOT_JSON="$(json_escape "$ROOT")"
CONTENT_JSON="$(json_escape "$CONTENT")"
VERSION_JSON="$(json_escape "$VERSION")"
cat > "$ROOT/profile/settings.json" <<JSON
{
  "proton_source": "custom",
  "proton_dir": "$ROOT_JSON/engine/GDK-Proton-mcbe-gdk",
  "proton": "$ROOT_JSON/engine/GDK-Proton-mcbe-gdk",
  "proton_tag": "custom-dir",
  "game_dir": "$CONTENT_JSON",
  "mc_version": "$VERSION_JSON",
  "diagnostics": false,
  "input_backend": "x11"
}
JSON

MCBE_GDK_ROOT="$ROOT" BOL_HOME="$ROOT/profile" PYTHONPATH="$ROOT/lib" \
  python3 "$ROOT/lib/runtime.py" ensure-umu

echo
echo "Installed successfully."
echo "Run: mcbe-gdk-linux gui"
echo "Microsoft/Xbox sign-in is optional."
