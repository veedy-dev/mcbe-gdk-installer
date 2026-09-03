"""Filesystem operations shared by the uninstall UI and tests."""

from __future__ import annotations

import fcntl
import os
import signal
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

LOCK_NAME = ".desktop-launch.lock"
PID_NAME = ".desktop-launch.pid"


@contextmanager
def runtime_lock(root: Path):
    path = root / "profile" / LOCK_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(
                "Minecraft or another setup action is running."
            ) from exc
        yield


def _is_launcher(pid: int, lock_path: Path) -> bool:
    try:
        command = (Path("/proc") / str(pid) / "cmdline").read_bytes().split(b"\0")
        installed_launcher = os.path.realpath(
            os.fsencode(lock_path.parent.parent / "lib" / "launch.sh")
        )
        if not any(
            os.path.basename(part) == b"mcbe-gdk-linux"
            or os.path.realpath(part) == installed_launcher
            for part in command
            if part
        ):
            return False
        locked = lock_path.stat()
        for descriptor in (Path("/proc") / str(pid) / "fd").iterdir():
            try:
                opened = descriptor.stat()
            except OSError:
                continue
            if (opened.st_dev, opened.st_ino) == (locked.st_dev, locked.st_ino):
                return True
    except (OSError, UnicodeDecodeError):
        pass
    return False


def minecraft_launcher_pid(root: Path) -> int | None:
    profile = root / "profile"
    lock_path = profile / LOCK_NAME
    pid_path = profile / PID_NAME
    try:
        pid = int(pid_path.read_text().strip())
    except (OSError, ValueError):
        pid = 0
    if pid and _is_launcher(pid, lock_path):
        return pid
    if pid:
        pid_path.unlink(missing_ok=True)

    try:
        with lock_path.open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return None
    except BlockingIOError:
        pass
    except OSError:
        return None

    # Support sessions started by installer versions predating the PID file.
    for process in Path("/proc").iterdir():
        if process.name.isdigit() and _is_launcher(int(process.name), lock_path):
            return int(process.name)
    return None


def stop_minecraft(root: Path) -> bool:
    pid = minecraft_launcher_pid(root)
    if not pid:
        return False

    wineserver = root / "engine/GDK-Proton-mcbe-gdk/files/bin/wineserver"
    if wineserver.is_file():
        try:
            subprocess.run(
                [wineserver, "-k"],
                env={
                    **os.environ,
                    "WINEPREFIX": str(root / "profile/compatdata/pfx"),
                },
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
        except subprocess.TimeoutExpired:
            pass
    try:
        group = os.getpgid(pid)
        if group == pid:
            os.killpg(group, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    return True


def _remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def remove_minecraft(root: Path, remove_user_data: bool = False) -> None:
    _remove(root / "game")
    _remove(root / "game-dir")
    _remove(root / "game-path")
    _remove(root / "profile" / "content")

    if remove_user_data:
        profile = root / "profile"
        if profile.is_dir():
            for entry in profile.iterdir():
                if entry.name != LOCK_NAME:
                    _remove(entry)


def main(argv: list[str]) -> int:
    usage = f"Usage: {argv[0]} ROOT uninstall [--remove-user-data] [--yes] | ROOT stop"
    if len(argv) < 3:
        print(usage, file=sys.stderr)
        return 2
    root = Path(argv[1]).expanduser()
    command, options = argv[2], set(argv[3:])
    if command == "stop" and not options:
        if stop_minecraft(root):
            print("Stopping Minecraft.")
        else:
            print("Minecraft is not running.")
        return 0
    if command != "uninstall" or options - {"--remove-user-data", "--yes"}:
        print(usage, file=sys.stderr)
        return 2
    remove_user_data = "--remove-user-data" in options
    if "--yes" not in options:
        detail = (
            "game files, worlds, settings, and the Microsoft/Xbox session"
            if remove_user_data
            else "game files (worlds, settings, and account data are kept)"
        )
        if not sys.stdin.isatty():
            print(f"This removes {detail}; pass --yes to confirm.", file=sys.stderr)
            return 2
        if input(f"Uninstall Minecraft? This removes {detail}. [y/N] ").strip().lower() != "y":
            print("Cancelled.")
            return 1
    try:
        with runtime_lock(root):
            remove_minecraft(root, remove_user_data)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1
    print("Minecraft uninstalled." + (" User data removed." if remove_user_data else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
