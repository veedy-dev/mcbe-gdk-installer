#!/usr/bin/env bash
set -euo pipefail

TOOL_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export MCBE_GDK_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/mcbe-gdk-linux"
export MCBE_GDK_TOOL_ROOT="$TOOL_ROOT"
export PYTHONPATH="$TOOL_ROOT${PYTHONPATH:+:$PYTHONPATH}"
exec python3 "$TOOL_ROOT/scripts/gui_engine.py"
