#!/usr/bin/env bash
set -euo pipefail

ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/mcbe-gdk-linux"
export MCBE_GDK_ROOT="$ROOT"
export BOL_HOME="$ROOT/profile"
export PYTHONPATH="$ROOT/lib"

usage() {
  cat <<'EOF'
Usage: mcbe-gdk-linux [COMMAND] [ARGS]

Commands:
  gui                 Open the installer
  launch [ARGS]       Launch Minecraft (default)
  stop                Stop the running Minecraft session
  install PACKAGE     Install or update Minecraft from an authorized package
  uninstall [--remove-user-data] [--yes]
                      Remove Minecraft; optionally worlds, settings, and account
  update              Install selected installer and engine updates
  engine [ENGINE]     Show or switch engine (version, latest, or GitHub asset URL)
  login               Connect a Microsoft/Xbox account
  logout              Disconnect the saved account
  status              Show account status
  recover             Acknowledge GPU recovery after troubleshooting
  setup-env [--fish]  Print the COM_MOJANG environment command
  help                Show this help
EOF
}

command="${1:-launch}"
(( $# )) && shift
case "$command" in
  gui)
    exec "$ROOT/lib/gui-launch.sh" "$@"
    ;;
  launch)
    exec "$ROOT/lib/launch.sh" "$@"
    ;;
  login|logout|status)
    exec "$ROOT/lib/auth.sh" "$command" "$@"
    ;;
  update)
    mkdir -p "$BOL_HOME"
    exec 9>"$BOL_HOME/.desktop-launch.lock"
    flock -n 9 || {
      echo "Minecraft or another MCBE GDK command is running; try again after it closes." >&2
      exit 1
    }
    tool_root="$(cat "$ROOT/source-dir" 2>/dev/null || true)"
    [[ -n "$tool_root" && -f "$tool_root/VERSION" ]] || {
      echo "MCBE GDK Installer source is missing; reinstall the installer." >&2
      exit 1
    }
    exec python3 "$ROOT/lib/updates.py" install "$tool_root" "$ROOT"
    ;;
  install)
    mkdir -p "$BOL_HOME"
    exec 9>"$BOL_HOME/.desktop-launch.lock"
    flock -n 9 || {
      echo "Minecraft or another MCBE GDK command is running; try again after it closes." >&2
      exit 1
    }
    tool_root="$(cat "$ROOT/source-dir" 2>/dev/null || true)"
    [[ -n "$tool_root" && -f "$tool_root/easy-install.sh" ]] || {
      echo "MCBE GDK Installer source is missing; reinstall the installer." >&2
      exit 1
    }
    exec "$tool_root/easy-install.sh" "$@"
    ;;
  stop|uninstall)
    exec python3 "$ROOT/lib/removal.py" "$ROOT" "$command" "$@"
    ;;
  engine)
    mkdir -p "$BOL_HOME"
    exec 9>"$BOL_HOME/.desktop-launch.lock"
    flock -n 9 || {
      echo "Minecraft or another MCBE GDK command is running; try again after it closes." >&2
      exit 1
    }
    exec python3 "$ROOT/lib/updates.py" engine "$ROOT" "$@"
    ;;
  recover)
    exec "$ROOT/lib/recover.sh" "$@"
    ;;
  setup-env)
    exec "$ROOT/lib/rgl-env.sh" "$@"
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    echo "Unknown command: $command" >&2
    usage >&2
    exit 2
    ;;
esac
