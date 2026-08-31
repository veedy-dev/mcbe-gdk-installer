#!/usr/bin/env python3
"""Standalone Microsoft/Xbox authentication and WineGDK preparation."""

from __future__ import annotations

from collections.abc import Mapping

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from threading import Event, Thread

ROOT = Path(os.environ["MCBE_GDK_ROOT"]).expanduser().resolve()
os.environ["BOL_HOME"] = str(ROOT / "profile")
_LIB = str(ROOT / "lib")
if _LIB not in sys.path:
    sys.path.append(_LIB)


from auth.auth import (  # noqa: E402
    NativeAuth,
    MsaRefreshRejected,
    msa_gamertag,
    msa_logout,
    msa_refresh,
    msa_save_for_account_epoch,
    msa_session_snapshot,
    msa_signed_in,
    wine_apply_winegdk_prereqs,
    wine_reg_set_refresh_token,
    xbl_preauth,
    xbl_preauth_error_message,
)
from auth.config import WINEGDK_REG  # noqa: E402
from auth.deps import ensure_login_deps  # noqa: E402
from auth.fixups import (  # noqa: E402
    _install_cryptbase_in_prefix,
    bump_stack_reserve,
    fix_curl_ssl,
    install_gdk_xbox_dlls,
)
from auth.engine_profiles import (  # noqa: E402
    installed_engine_profile,
    read_custom_engine_metadata,
)
from auth.game_profile import (  # noqa: E402
    apply_installed_engine_profile,
    login_request_path,
)
from auth.gameinput import install_gameinput  # noqa: E402
from auth.gpu_safety import (  # noqa: E402
    acknowledge_gpu_safety_incident,
    arm_gpu_launch,
    disarm_gpu_launch,
    require_safe_graphics_session,
)
from auth.log import BolError, ok  # noqa: E402
from auth.remote_login import (  # noqa: E402
    clear_remote_login_request,
    monitor_remote_login,
    present_device_code as _show_code,
    read_remote_login_request,
)
from auth.prefix import active_prefix, boot_prefix, ensure_umu, prefix_ready  # noqa: E402
from auth.wine_registry import (  # noqa: E402
    purge_registry_staging,
    reg_delete,
    update_prefix_registry,
)




def login(on_code=None) -> bool:
    if msa_signed_in():
        print(f"Already signed in{': ' + msa_gamertag() if msa_gamertag() else ''}.")
        return True
    auth = NativeAuth()

    def default_callback(url: str, code: str) -> None:
        if not _show_code(url, code):
            auth.stop()

    auth._flow(on_code or default_callback, None)  # Synchronous device-code flow.
    if auth._stop and not msa_signed_in():
        print("Sign-in cancelled.")
    return msa_signed_in()


def logout() -> None:
    prefix = active_prefix()
    try:
        if prefix_ready(prefix):
            purge_registry_staging(prefix)
            update_prefix_registry(
                prefix,
                machine=[reg_delete(WINEGDK_REG, "RefreshToken")],
            )
    except Exception as exc:
        raise BolError(
            "Could not safely clear the Microsoft token from the Wine prefix."
        ) from exc
    msa_logout()
    ok("Microsoft/Xbox account removed")


def recover_gpu() -> None:
    status = acknowledge_gpu_safety_incident()
    ok(status.message)


def performance_advisories(
    root: Path = ROOT,
    *,
    meminfo_path: Path = Path("/proc/meminfo"),
    environ: Mapping[str, str] = os.environ,
) -> list[str]:
    warnings: list[str] = []
    try:
        available_kib = next(
            int(line.split()[1])
            for line in meminfo_path.read_text(encoding="utf-8").splitlines()
            if line.startswith("MemAvailable:")
        )
        if available_kib < 3 * 1024**2:
            warnings.append(
                f"Only {available_kib // 1024} MiB memory is available; "
                "3072 MiB or more is recommended."
            )
    except (OSError, StopIteration, ValueError):
        pass

    try:
        free_mib = shutil.disk_usage(root).free // 1024**2
        if free_mib < 5 * 1024:
            warnings.append(
                f"Only {free_mib} MiB disk space is free; "
                "5120 MiB or more is recommended."
            )
    except OSError:
        pass

    max_viewdistance = 0
    windowed_vsync = False
    options_root = root / "profile/compatdata"
    for path in options_root.rglob("options.txt") if options_root.is_dir() else ():
        try:
            options = dict(
                line.split(":", 1)
                for line in path.read_text(encoding="utf-8").splitlines()
                if ":" in line
            )
            max_viewdistance = max(
                max_viewdistance, int(options.get("gfx_viewdistance", "0"))
            )
            windowed_vsync |= (
                options.get("gfx_vsync") == "1"
                and options.get("gfx_fullscreen") == "0"
            )
        except (OSError, ValueError):
            continue

    render_chunks = max_viewdistance // 16
    if render_chunks > 32:
        warnings.append(
            f"Render distance is {render_chunks} chunks; "
            "32 chunks or lower is recommended for consistent server time."
        )
    wayland = bool(environ.get("WAYLAND_DISPLAY")) or (
        environ.get("XDG_SESSION_TYPE", "").casefold() == "wayland"
    )
    if wayland and windowed_vsync:
        warnings.append(
            "In-game VSync is enabled in a window on Wayland; "
            "fullscreen or disabling in-game VSync may reduce compositor latency."
        )
    return warnings


def prepare(game_dir: Path) -> None:
    game_dir = game_dir.resolve()
    exe = game_dir / "Minecraft.Windows.exe"
    if not exe.is_file():
        raise BolError(f"Missing game executable: {exe}")
    profile = installed_engine_profile(ROOT)
    custom_engine = read_custom_engine_metadata(ROOT)
    apply_installed_engine_profile(ROOT, game_dir)
    signed_in = custom_engine is None and msa_signed_in()
    if signed_in and ensure_login_deps():
        raise BolError("Python package 'cryptography' is required for Xbox sign-in.")

    install_gdk_xbox_dlls(game_dir)
    fix_curl_ssl(game_dir)
    ensure_umu()
    if not boot_prefix():
        raise BolError("Could not initialise the Wine prefix.")
    prefix = active_prefix()
    try:
        purge_registry_staging(prefix)
    except OSError as exc:
        raise BolError("Could not clear stale Wine registry token files.") from exc
    _install_cryptbase_in_prefix()
    install_gameinput(prefix, game_dir)
    wine_apply_winegdk_prereqs()

    if custom_engine is not None:
        update_prefix_registry(
            prefix,
            machine=[reg_delete(WINEGDK_REG, "RefreshToken")],
        )
        bump_stack_reserve(exe)
        return

    if not signed_in:
        update_prefix_registry(
            prefix,
            machine=[reg_delete(WINEGDK_REG, "RefreshToken")],
        )
        bump_stack_reserve(exe)
        return

    account, epoch = msa_session_snapshot()
    refresh_token = account.get("refresh_token")
    if not refresh_token:
        raise BolError("The Microsoft session has no refresh token; sign in again.")
    try:
        fresh = msa_refresh(refresh_token)
    except MsaRefreshRejected as exc:
        msa_logout()
        update_prefix_registry(
            prefix,
            machine=[reg_delete(WINEGDK_REG, "RefreshToken")],
        )
        raise BolError(
            "The Microsoft session expired or was revoked; sign in again."
        ) from exc
    except Exception:
        fresh = None
    if fresh:
        if not msa_save_for_account_epoch(
            {
                "refresh_token": fresh["refresh_token"],
                "obtained": int(time.time()),
            },
            epoch,
        ):
            raise BolError("The Microsoft account changed during sign-in.")
        refresh_token = fresh["refresh_token"]
    if not wine_reg_set_refresh_token(refresh_token):
        raise BolError("Could not store the Microsoft token in the Wine prefix.")
    if not xbl_preauth((fresh or {}).get("access_token", ""), epoch):
        raise BolError(
            xbl_preauth_error_message()
            or "Could not prepare the Xbox Live session."
        )
    bump_stack_reserve(exe)


def supervise(umu: Path, game: Path, arguments: list[str]) -> int:
    umu = umu.resolve()
    game = game.resolve()
    profile = installed_engine_profile(ROOT)
    stop_event = Event()
    monitor_thread: Thread | None = None
    fallback = ROOT / "profile" / "device-code.txt"

    if profile and profile.authentication == "remote-connect-json":
        request = login_request_path(game.parent, profile)
        clear_remote_login_request(request)

        def monitor() -> None:
            try:
                monitor_remote_login(
                    request,
                    lambda url, code: _show_code(
                        url,
                        code,
                        emit=False,
                        stop_event=stop_event,
                        fallback_path=fallback,
                    ),
                    stop_event=stop_event,
                )
            except Exception as exc:
                print(f"Remote login monitor: {exc}", file=sys.stderr, flush=True)

        monitor_thread = Thread(
            target=monitor,
            name="mcbe-remote-login",
            daemon=False,
        )
        monitor_thread.start()

    try:
        child = subprocess.Popen(
            [sys.executable, str(umu), str(game), *arguments],
            cwd=game.parent,
            start_new_session=True,
        )
    except Exception:
        stop_event.set()
        if monitor_thread:
            monitor_thread.join(timeout=3)
        fallback.unlink(missing_ok=True)
        raise
    previous_handlers = {}

    def forward_signal(signum, _frame) -> None:
        if child.poll() is None:
            try:
                os.killpg(child.pid, signum)
            except ProcessLookupError:
                pass

    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        previous_handlers[signum] = signal.signal(signum, forward_signal)
    try:
        return_code = child.wait()
    finally:
        stop_event.set()
        if monitor_thread:
            monitor_thread.join(timeout=3)
        fallback.unlink(missing_ok=True)
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
    return 128 - return_code if return_code < 0 else return_code


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else "status"
    try:
        profile = installed_engine_profile(ROOT)
        custom_engine = read_custom_engine_metadata(ROOT)
        if command == "engine-profile":
            if profile:
                print(profile.identifier)
            return 0
        if command in {"login", "logout", "status"} and custom_engine is not None:
            if profile and profile.authentication == "remote-connect-json":
                messages = {
                    "login": (
                        "Launch Minecraft and select Sign In; the Microsoft "
                        "device code will open automatically."
                    ),
                    "logout": "Sign out from the Profile screen inside Minecraft.",
                    "status": "Account status is only available inside Minecraft.",
                }
            else:
                messages = {
                    "login": "Sign-in is managed by this custom engine.",
                    "logout": "Sign-out is managed by this custom engine.",
                    "status": "Account status is not exposed by this custom engine.",
                }
            print(messages[command])
            return 3
        if command == "login":
            return 0 if login() else 1
        if command == "logout":
            logout()
            return 0
        if command == "status":
            if not msa_signed_in():
                print("Not signed in.")
                return 1
            print(f"Signed in{': ' + msa_gamertag() if msa_gamertag() else ''}.")
            return 0
        if command == "performance":
            for warning in performance_advisories():
                print(f"Performance advisory: {warning}")
            return 0
        if command == "prepare" and len(argv) == 3:
            prepare(Path(argv[2]))
            return 0
        if command == "apply-engine-profile" and len(argv) == 3:
            apply_installed_engine_profile(ROOT, Path(argv[2]))
            return 0
        if command == "supervise" and len(argv) >= 4:
            return supervise(Path(argv[2]), Path(argv[3]), argv[4:])
        if command == "ensure-umu":
            ensure_umu()
            return 0
        if command == "ensure-deps":
            return 1 if ensure_login_deps() else 0
        if command == "gpu-arm":
            require_safe_graphics_session()
            print(arm_gpu_launch())
            return 0
        if command == "gpu-disarm" and len(argv) == 3:
            return 0 if disarm_gpu_launch(argv[2]) else 1
        if command == "gpu-recover":
            recover_gpu()
            return 0
        print(
            f"Usage: {argv[0]} login|logout|status|prepare GAME_DIR|"
            "apply-engine-profile GAME_DIR|engine-profile|"
            "supervise UMU GAME [ARGS]|ensure-umu|ensure-deps|"
            "gpu-arm|gpu-disarm TOKEN|gpu-recover"
        )
        return 2
    except BolError as exc:
        if not getattr(exc, "reported", False):
            print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(
            "\nSign-in cancelled." if command == "login" else "\nCancelled.",
            file=sys.stderr,
        )
        return 130


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
