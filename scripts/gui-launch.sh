#!/usr/bin/env bash
set -euo pipefail

ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/mcbe-gdk-linux"
export MCBE_GDK_ROOT="$ROOT"
MCBE_GDK_TOOL_ROOT="$(cat "$ROOT/source-dir" 2>/dev/null || true)"
export MCBE_GDK_TOOL_ROOT
export PYTHONPATH="$ROOT/lib"
exec python3 "$ROOT/lib/gui_engine.py"
