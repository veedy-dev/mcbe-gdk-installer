"""Secure presentation of WineGDK remote-connect device-code requests."""
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import time
import webbrowser
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from threading import Event
from urllib.parse import urlparse

from .log import BolError

REMOTE_LOGIN_MAX_BYTES = 4096
REMOTE_LOGIN_HOSTS = {"aka.ms", "microsoft.com", "www.microsoft.com"}


def _safe_request_status(status: os.stat_result) -> bool:
    return (
        stat.S_ISREG(status.st_mode)
        and status.st_uid == os.getuid()
        and status.st_nlink == 1
    )


def clear_remote_login_request(path: Path) -> None:
    """Create or truncate the request as an owned 0600 regular file.

    Lukas WineGDK opens this path with ``fopen(..., "w")``. Pre-creating it
    protects the device code without deleting the rendezvous file that the
    in-game remote-connect flow expects to remain present while it is active.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_TRUNC
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise BolError("Could not safely prepare the remote login request.") from exc
    try:
        status = os.fstat(descriptor)
        if not _safe_request_status(status):
            raise BolError("The remote login request path is unsafe.")
        os.fchmod(descriptor, 0o600)
    except OSError as exc:
        raise BolError("Could not protect the remote login request.") from exc
    finally:
        os.close(descriptor)


def remove_remote_login_request(path: Path) -> None:
    """Remove the short-lived request after the supervised game exits."""
    try:
        status = path.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise BolError("Could not inspect the remote login request.") from exc
    if not _safe_request_status(status):
        raise BolError("The remote login request path is unsafe.")
    try:
        path.unlink()
    except OSError as exc:
        raise BolError("Could not remove the remote login request.") from exc


def read_remote_login_request(path: Path) -> tuple[str, str] | None:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise BolError("Could not safely open the remote login request.") from exc
    try:
        status = os.fstat(descriptor)
        if (
            not _safe_request_status(status)
            or status.st_size > REMOTE_LOGIN_MAX_BYTES
        ):
            raise BolError("The remote login request is unsafe.")
        try:
            os.fchmod(descriptor, 0o600)
        except OSError as exc:
            raise BolError("Could not protect the remote login request.") from exc
        payload = os.read(descriptor, REMOTE_LOGIN_MAX_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(payload) > REMOTE_LOGIN_MAX_BYTES:
        raise BolError("The remote login request is unexpectedly large.")
    try:
        data = json.loads(payload)
    except (UnicodeError, ValueError):
        return None
    if not isinstance(data, Mapping):
        raise BolError("The remote login request is invalid.")
    url = data.get("verification_uri") or data.get("verification_url")
    code = data.get("user_code")
    if not isinstance(url, str) or not isinstance(code, str):
        return None
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in REMOTE_LOGIN_HOSTS
        or parsed.username
        or parsed.password
    ):
        raise BolError("The remote login request has an untrusted URL.")
    code = code.strip()
    if not re.fullmatch(r"[A-Za-z0-9-]{4,32}", code):
        raise BolError("The remote login request has an invalid device code.")
    return url, code


def monitor_remote_login(
    path: Path,
    on_code: Callable[[str, str], None],
    *,
    stop_event: Event | None = None,
    timeout: float | None = None,
    poll_interval: float = 0.25,
) -> bool:
    started = time.monotonic()
    seen: set[tuple[str, str]] = set()
    while (
        (stop_event is None or not stop_event.is_set())
        and (timeout is None or time.monotonic() - started < timeout)
    ):
        request = read_remote_login_request(path)
        if request and request not in seen:
            seen.add(request)
            on_code(*request)
        if stop_event is not None:
            stop_event.wait(poll_interval)
        else:
            time.sleep(poll_interval)
    return bool(seen)


def _open_browser(url: str) -> None:
    try:
        opened = webbrowser.open(url)
    except Exception:
        opened = False
    if opened:
        return
    opener = shutil.which("xdg-open")
    command = [opener, url] if opener else None
    if not command and (opener := shutil.which("gio")):
        command = [opener, "open", url]
    if command:
        subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def _wait_process(process: subprocess.Popen, stop_event: Event | None) -> bool:
    while process.poll() is None:
        if stop_event is not None and stop_event.wait(0.1):
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            return False
        if stop_event is None:
            try:
                return process.wait() == 0
            except KeyboardInterrupt:
                process.terminate()
                process.wait()
                raise
        time.sleep(0.1)
    return process.returncode == 0


def _copy_code(code: str) -> bool:
    if copier := shutil.which("wl-copy"):
        command = [copier]
    elif copier := shutil.which("xclip"):
        command = [copier, "-selection", "clipboard"]
    else:
        return False
    result = subprocess.run(
        command,
        input=code,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def _write_fallback(path: Path, url: str, code: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}")
    try:
        temporary.write_text(
            f"Open {url}\nEnter code: {code}\n",
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def present_device_code(
    url: str,
    code: str,
    *,
    emit: bool = True,
    stop_event: Event | None = None,
    fallback_path: Path | None = None,
) -> bool:
    """Open the verification page and present a copyable short-lived code."""
    message = f"Open {url}\n\nEnter code: {code}"
    prompt = (
        "Your browser should open automatically.\n\n"
        "Copy this code and complete sign-in, then click Continue.\n"
        f"If it does not open, visit {url}."
    )
    _open_browser(url)

    if dialog := shutil.which("kdialog"):
        process = subprocess.Popen(
            [
                dialog,
                "--title",
                "MCBE GDK Installer",
                "--inputbox",
                prompt,
                code,
                "--ok-label",
                "Continue",
                "--cancel-label",
                "Cancel",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return _wait_process(process, stop_event)
    if dialog := shutil.which("zenity"):
        process = subprocess.Popen(
            [
                dialog,
                "--entry",
                "--title=MCBE GDK Installer",
                f"--text={prompt}",
                f"--entry-text={code}",
                "--ok-label=Continue",
                "--cancel-label=Cancel",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return _wait_process(process, stop_event)
    if notifier := shutil.which("notify-send"):
        subprocess.run(
            [notifier, "MCBE GDK Installer sign-in", message],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        _copy_code(code)
        return True

    copied = _copy_code(code)
    if emit:
        print(message, flush=True)
        if copied:
            print("The device code was copied to the clipboard.", flush=True)
        return True
    try:
        with open("/dev/tty", "w", encoding="utf-8") as terminal:
            terminal.write(message + "\n")
            if copied:
                terminal.write("The device code was copied to the clipboard.\n")
        return True
    except OSError:
        if fallback_path is None:
            raise BolError("No secure device-code presentation method is available.")
        _write_fallback(fallback_path, url, code)
        print(
            f"Device code written to protected file: {fallback_path}",
            file=sys.stderr,
            flush=True,
        )
        return True
