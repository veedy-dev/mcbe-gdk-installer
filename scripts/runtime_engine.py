#!/usr/bin/env python3
"""Profile-aware wrapper around the shared MCBE GDK runtime."""

from __future__ import annotations

import sys
from pathlib import Path

try:
    # Managed installations keep the original implementation under this name.
    import runtime_base as base
except ModuleNotFoundError as exc:  # Source-tree execution.
    if exc.name != "runtime_base":
        raise
    import runtime as base

from auth.engine_profiles import installed_engine_profile
from auth.prefix import active_prefix
from auth.remote_login import remove_remote_login_request
from auth.game_profile import login_request_path
from auth.wine_registry import reg_delete, reg_dword, update_prefix_registry

GAMING_SERVICES_KEY = r"Software\Microsoft\GamingServices"
GAMING_SERVICES_VALUE = "IgnoreVersionMismatch"

_original_prepare = base.prepare
_original_supervise = base.supervise
_original_read_custom_engine_metadata = base.read_custom_engine_metadata


def reviewed_custom_engine_metadata(root: Path):
    """Expose custom metadata to auth logic only for a reviewed exact profile."""
    metadata = _original_read_custom_engine_metadata(root)
    return metadata if metadata and installed_engine_profile(root) else None


def prepare(game_dir: Path) -> None:
    """Run normal preparation, then apply the exact engine registry policy."""
    _original_prepare(game_dir)
    profile = installed_engine_profile(base.ROOT)
    change = (
        reg_dword(GAMING_SERVICES_KEY, GAMING_SERVICES_VALUE, 1)
        if profile and profile.ignore_gaming_services_version
        else reg_delete(GAMING_SERVICES_KEY, GAMING_SERVICES_VALUE)
    )
    try:
        update_prefix_registry(active_prefix(), machine=[change])
    except Exception as exc:
        raise base.BolError(
            "Could not apply the compatibility engine version policy."
        ) from exc


def supervise(umu: Path, game: Path, arguments: list[str]) -> int:
    """Preserve login.json while the game listens, then remove it on exit."""
    profile = installed_engine_profile(base.ROOT)
    request = (
        login_request_path(game.resolve().parent, profile)
        if profile and profile.authentication == "remote-connect-json"
        else None
    )
    try:
        return _original_supervise(umu, game, arguments)
    finally:
        if request is not None:
            try:
                remove_remote_login_request(request)
            except base.BolError as exc:
                print(
                    f"Remote login cleanup: {exc}",
                    file=sys.stderr,
                    flush=True,
                )


# base.main and the original prepare function resolve these module globals at
# call time, so unprofiled custom archives retain the stable authentication
# behavior instead of silently disabling it.
base.read_custom_engine_metadata = reviewed_custom_engine_metadata
base.prepare = prepare
base.supervise = supervise

# scripts/gui.py imports these names from the installed ``runtime`` module.
login = base.login
logout = base.logout


if __name__ == "__main__":
    raise SystemExit(base.main(sys.argv))
