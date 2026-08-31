#!/usr/bin/env bash
set -uo pipefail
ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/mcbe-gdk-linux"
export BOL_HOME="$ROOT/profile"
export MCBE_GDK_ROOT="$ROOT"
export PYTHONPATH="$ROOT/lib"
export PROTON_USE_WOW64=1
CONTENT="$(cat "$ROOT/game-dir" 2>/dev/null || true)"
GAME="$CONTENT/Minecraft.Windows.exe"
ENGINE="$ROOT/engine/GDK-Proton-mcbe-gdk"
UMU="$BOL_HOME/umu/umu-run"
RUNTIME="$ROOT/lib/runtime.py"
LOG="$BOL_HOME/logs/desktop-launch.log"
CACHE="$BOL_HOME/graphics-cache"
LOCK="$BOL_HOME/.desktop-launch.lock"
PID_FILE="$BOL_HOME/.desktop-launch.pid"
GPU_MARKER="$BOL_HOME/.gpu-launch-in-progress.json"
RECOVER_CMD="mcbe-gdk-linux recover"

notify() {
  if command -v notify-send >/dev/null 2>&1; then
    notify-send --app-name='MCBE GDK Installer' --icon=minecraft \
      "$1" "$2" >/dev/null 2>&1 || true
  fi
}

ntsync_preflight() {
  local status
  local wineserver="$ENGINE/files/bin/wineserver"
  local grep_status

  if ! test -f "$wineserver" || ! test -r "$wineserver"; then
    status='NTSync preflight: engine wineserver is missing or unreadable; update or reinstall the engine.'
  else
    grep -aFq -- '/dev/ntsync' "$wineserver" 2>/dev/null
    grep_status=$?
    if (( grep_status == 1 )); then
      status='NTSync preflight: engine wineserver lacks /dev/ntsync support; update or reinstall the engine.'
    elif (( grep_status != 0 )); then
      status='NTSync preflight: could not inspect engine wineserver; update or reinstall the engine.'
    elif ! test -e /dev/ntsync; then
      status='NTSync preflight: /dev/ntsync is missing; use Linux 6.14+ or a distribution NTSync backport and load the module.'
    elif ! test -c /dev/ntsync; then
      status='NTSync preflight: /dev/ntsync is not a character device; repair the distribution device node.'
    elif ! test -r /dev/ntsync; then
      status='NTSync preflight: /dev/ntsync is unreadable; repair the distribution device permissions.'
    else
      status='NTSync preflight: static prerequisites present.'
    fi
  fi

  printf '%s\n' "$status" >> "$LOG"
  if [[ "$status" != 'NTSync preflight: static prerequisites present.' ]]; then
    notify 'NTSync performance path unavailable' \
      "Minecraft will still launch. See $LOG"
  fi
  return 0
}

[[ -f "$GAME" ]] || {
  notify 'MCBE GDK Installer' \
    'Minecraft.Windows.exe is missing; rerun install.sh.'
  exit 1
}
[[ -x "$ENGINE/proton" ]] || {
  notify 'MCBE GDK Installer' \
    'The compatibility engine is missing; rerun install.sh.'
  exit 1
}
[[ -f "$RUNTIME" ]] || {
  notify 'MCBE GDK Installer' \
    'The standalone runtime is missing; rerun install.sh.'
  exit 1
}
command -v python3 >/dev/null 2>&1 || {
  notify 'MCBE GDK Installer' 'Python 3 is required.'
  exit 1
}
command -v flock >/dev/null 2>&1 || {
  notify 'MCBE GDK Installer' 'flock is required.'
  exit 1
}

mkdir -p "$BOL_HOME/logs" "$CACHE/vkd3d" "$CACHE/dxvk" "$CACHE/nvidia"
exec 9>"$LOCK"
if ! flock -n 9; then
  notify 'Minecraft is already starting or running' \
    'Wait for the game window instead of clicking the launcher again.'
  exit 0
fi
cleanup_pid() {
  [[ "$(cat "$PID_FILE" 2>/dev/null || true)" == "$$" ]] && rm -f "$PID_FILE"
}
printf '%s\n' "$$" > "$PID_FILE.$$"
mv -f "$PID_FILE.$$" "$PID_FILE"
trap cleanup_pid EXIT

if [[ -f "$GPU_MARKER" ]]; then
  current_boot="$(cat /proc/sys/kernel/random/boot_id 2>/dev/null || true)"
  marker_boot="$(
    grep -o '"boot_id":"[^"]*"' "$GPU_MARKER" 2>/dev/null |
      head -1 | cut -d'"' -f4 || true
  )"
  marker_pid="$(
    grep -o '"launcher_pid":[0-9]*' "$GPU_MARKER" 2>/dev/null |
      head -1 | cut -d: -f2 || true
  )"
  if [[ "$marker_pid" =~ ^[0-9]+$ ]] &&
      kill -0 "$marker_pid" 2>/dev/null; then
    notify 'Minecraft is already running' \
      'Close the existing game session before launching it again.'
  elif [[ -n "$current_boot" && "$marker_boot" == "$current_boot" ]]; then
    notify 'MCBE GDK Installer needs one reboot' \
      "A previous GPU session was interrupted. Reboot Linux, then run: $RECOVER_CMD"
  else
    notify 'MCBE GDK Installer recovery required' \
      "Run: $RECOVER_CMD"
  fi
  exit 3
fi

printf '\n[%(%F %T)T] Launch requested\n' -1 >> "$LOG"
ntsync_preflight
performance_output="$(python3 "$RUNTIME" performance 2>> "$LOG" || true)"
if [[ -n "$performance_output" ]]; then
  printf '%s\n' "$performance_output" >> "$LOG"
  notify 'Performance settings may slow Minecraft' "See $LOG"
fi

# Custom engines are intentionally outside BOL's managed-engine cache path.
# Supply equivalent persistent caches explicitly and keep heavyweight Proton
# diagnostics off during normal play.
export BOL_DIAG="${BOL_DIAG:-0}"
export BOL_XCURL_LOG="${BOL_XCURL_LOG:-0}"
export VKD3D_SHADER_CACHE_PATH="$CACHE/vkd3d"
export DXVK_SHADER_CACHE_PATH="$CACHE/dxvk"
export __GL_SHADER_DISK_CACHE=1
export __GL_SHADER_DISK_CACHE_PATH="$CACHE/nvidia"
export __GL_SHADER_DISK_CACHE_SIZE=1073741824

if ! python3 "$RUNTIME" prepare "$CONTENT" >> "$LOG" 2>&1; then
  notify 'MCBE GDK Installer setup failed' "See $LOG"
  exit 1
fi
[[ -x "$UMU" ]] || {
  notify 'MCBE GDK Installer' 'umu-launcher setup failed.'
  exit 1
}

mkdir -p "$HOME/.steam/steam"

export PROTONPATH="$ENGINE"
export PROTON_VERB=run
export WINEPREFIX="$BOL_HOME/compatdata/pfx"
export STEAM_COMPAT_CLIENT_INSTALL_PATH="$HOME/.steam/steam"
export UMU_FOLDERS_PATH="$BOL_HOME"
export UMU_RUNTIME_UPDATE=0
export GAMEID="${GAMEID:-umu-default}"
export WINEDEBUG="${WINEDEBUG:--all}"
export PROTON_ENABLE_WAYLAND=0
export MICROSOFT_WINDOWSAPPRUNTIME_BOOTSTRAP_INITIALIZE_SHOWUI=0
export MICROSOFT_WINDOWSAPPRUNTIME_BOOTSTRAP_INITIALIZE_FAILFAST=0
export MICROSOFT_WINDOWSAPPRUNTIME_DEPLOYMENT_INITIALIZE_ONERRORSHOWUI=0
export WINEGDK_PREAUTH_DEVICE="Z:${BOL_HOME//\//\\}\\winegdk-preauth\\device.json"
vkd3d_config="${VKD3D_CONFIG:-}"
if [[ "${MCBE_GDK_DISABLE_DXR:-0}" == "1" &&
      ",${vkd3d_config//;/,}," != *,nodxr,* ]]; then
  vkd3d_config="${vkd3d_config:+$vkd3d_config,}nodxr"
fi
if [[ ",${vkd3d_config//;/,}," != *,force_raw_va_cbv,* ]]; then
  vkd3d_config="${vkd3d_config:+$vkd3d_config,}force_raw_va_cbv"
fi
export VKD3D_CONFIG="$vkd3d_config"
export WINEDLLOVERRIDES="cryptbase=n,b;vrclient=;vrclient_x64=;openvr_api=;wineopenxr=;amd_ags_x64=${WINEDLLOVERRIDES:+;$WINEDLLOVERRIDES}"
[[ -n "${WAYLAND_DISPLAY:-}" ]] && export WINE_DISABLE_VULKAN_OPWR=1

# Some GDK builds can expose a native assertion dialog during a Wine startup race.
# Suppress the dialog/debug break without disabling addon or script debugging.
options_dir="$BOL_HOME/compatdata/pfx/drive_c/users/steamuser/AppData/Roaming/Minecraft Bedrock/Users/Shared/games/com.mojang/minecraftpe"
mkdir -p "$options_dir"
touch "$options_dir/options.txt"
while IFS= read -r -d '' options; do
  grep -q '^dev_assertions_debug_break:' "$options" && \
    sed -i 's/^dev_assertions_debug_break:.*/dev_assertions_debug_break:0/' "$options" || \
    printf '\ndev_assertions_debug_break:0\n' >> "$options"
  grep -q '^dev_assertions_show_dialog:' "$options" && \
    sed -i 's/^dev_assertions_show_dialog:.*/dev_assertions_show_dialog:0/' "$options" || \
    printf 'dev_assertions_show_dialog:0\n' >> "$options"
done < <(find "$BOL_HOME/compatdata" -type f -name options.txt -print0 2>/dev/null || true)

start=$SECONDS

gpu_output="$(python3 "$RUNTIME" gpu-arm 2>> "$LOG")"
gpu_token="${gpu_output##*$'\n'}"
if [[ "$gpu_output" == *$'\n'* ]]; then
  printf '%s\n' "${gpu_output%$'\n'*}" >> "$LOG"
fi
if [[ ! "$gpu_token" =~ ^[0-9a-f]{32}$ ]]; then
  notify 'MCBE GDK Installer safety check failed' "See $LOG"
  exit 1
fi
cleanup_marker() {
  python3 "$RUNTIME" gpu-disarm "$gpu_token" >> "$LOG" 2>&1 || true
}
cleanup_launch() {
  cleanup_marker
  cleanup_pid
}
trap cleanup_launch EXIT
trap 'exit 130' HUP INT TERM


python3 "$RUNTIME" supervise "$UMU" "$GAME" "$@" >> "$LOG" 2>&1
rc=$?
cleanup_launch
trap - EXIT HUP INT TERM
elapsed=$((SECONDS - start))
printf '[%(%F %T)T] Launcher exited rc=%d elapsed=%ds\n' \
  -1 "$rc" "$elapsed" >> "$LOG"

if (( rc != 0 )); then
  notify 'Minecraft Bedrock failed to start' "See $LOG"
elif (( elapsed < 8 )); then
  notify 'Minecraft Bedrock exited before opening' "See $LOG"
fi
exit "$rc"
