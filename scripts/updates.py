#!/usr/bin/env python3
"""Verified GitHub release discovery and installation."""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable
from urllib.parse import quote, unquote, urlparse
from urllib.request import Request, urlopen

from auth.engine_profiles import (
    CUSTOM_ENGINE_METADATA,
    EngineProfile,
    profile_for_asset,
    read_custom_engine_metadata,
)
from auth.game_profile import apply_installed_engine_profile
from auth.log import BolError

INSTALLER_REPO = "veedy-dev/mcbe-gdk-installer"
ENGINE_REPO = "veedy-dev/mcbe-gdk-engine"
VERSION_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
ENGINE_SELECTION_FILE = "engine-release"
API_VERSION = "2022-11-28"
MAX_RELEASE_JSON = 1_000_000
MAX_RELEASE_LIST_JSON = 10_000_000
MAX_ARCHIVE_MEMBERS = 200_000
MAX_ARCHIVE_PATH = 4096
MAX_ARCHIVE_MEMBER = 2_500_000_000
MAX_INSTALLER_UNPACKED = 100_000_000
MAX_ENGINE_UNPACKED = 8_000_000_000
ProgressCallback = Callable[[str, int | None, int | None], None]


class UpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class Release:
    repo: str
    tag: str
    name: str
    body: str
    url: str
    assets: dict[str, str]


@dataclass(frozen=True)
class CustomEngineAsset:
    repo: str
    tag: str
    name: str
    url: str
    sha256: str


@dataclass(frozen=True)
class AvailableUpdates:
    installer: Release | None = None
    engine: Release | None = None

    def __bool__(self) -> bool:
        return bool(self.installer or self.engine)


def version_tuple(value: str) -> tuple[int, int, int]:
    match = VERSION_RE.fullmatch(value.strip())
    if not match:
        raise UpdateError(f"Unsupported release version: {value!r}")
    return tuple(int(part) for part in match.groups())


def is_newer(candidate: str, current: str) -> bool:
    return version_tuple(candidate) > version_tuple(current)


def _parse_custom_engine_url(value: str) -> tuple[str, str, str]:
    parsed = urlparse(value.strip())
    if (
        parsed.scheme != "https"
        or parsed.netloc.lower() != "github.com"
        or parsed.query
        or parsed.fragment
    ):
        raise UpdateError("Custom engines must use a GitHub release asset URL.")
    parts = [unquote(part) for part in parsed.path.strip("/").split("/")]
    if (
        len(parts) != 6
        or parts[2:4] != ["releases", "download"]
        or any(not part or part in {".", ".."} for part in parts)
        or any("/" in part or "\\" in part for part in parts)
    ):
        raise UpdateError("Custom engines must use a GitHub release asset URL.")
    owner, repository, _, _, tag, asset = parts
    if not all(re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in (owner, repository)):
        raise UpdateError("Custom engine repository is invalid.")
    if not asset.lower().endswith(".tar.gz"):
        raise UpdateError("Custom engine assets must be .tar.gz archives.")
    return f"{owner}/{repository}", tag, asset


def normalize_engine_selection(value: str) -> str:
    value = value.strip()
    if value.startswith("https://"):
        _parse_custom_engine_url(value)
        return value
    if value == "latest":
        return value
    if re.fullmatch(r"\d+\.\d+\.\d+", value):
        value = f"v{value}"
    version_tuple(value)
    return value


def _github_url(url: str, repo: str, *, download: bool = False) -> str:
    parsed = urlparse(url)
    expected = f"/{repo}/releases/"
    if parsed.scheme != "https" or parsed.hostname != "github.com":
        raise UpdateError("GitHub returned an untrusted release URL.")
    if expected not in parsed.path:
        raise UpdateError("GitHub returned a release URL for another repository.")
    if download and "/download/" not in parsed.path:
        raise UpdateError("GitHub returned an invalid asset URL.")
    return url


def fetch_custom_engine(url: str, *, timeout: int = 10) -> CustomEngineAsset:
    repo, tag, asset_name = _parse_custom_engine_url(url)
    request = Request(
        f"https://api.github.com/repos/{repo}/releases/tags/{quote(tag, safe='')}",
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "mcbe-gdk-installer",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_RELEASE_JSON + 1)
    except OSError as exc:
        raise UpdateError(f"Could not check {repo} releases: {exc}") from exc
    if len(raw) > MAX_RELEASE_JSON:
        raise UpdateError("GitHub returned an unexpectedly large release response.")
    try:
        data = json.loads(raw)
        if str(data["tag_name"]) != tag:
            raise UpdateError("GitHub release tag does not match the asset URL.")
        for asset in data.get("assets", []):
            if str(asset.get("name")) != asset_name:
                continue
            asset_url = str(asset["browser_download_url"])
            asset_repo, asset_tag, resolved_name = _parse_custom_engine_url(asset_url)
            if (
                asset.get("state") != "uploaded"
                or asset_repo.lower() != repo.lower()
                or asset_tag != tag
                or resolved_name != asset_name
            ):
                raise UpdateError("GitHub release asset does not match the requested URL.")
            digest = re.fullmatch(
                r"sha256:([0-9a-fA-F]{64})", str(asset.get("digest") or "")
            )
            if not digest:
                raise UpdateError("GitHub release asset has no SHA-256 digest.")
            return CustomEngineAsset(
                repo=repo,
                tag=tag,
                name=asset_name,
                url=asset_url,
                sha256=digest.group(1).lower(),
            )
    except UpdateError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise UpdateError("GitHub returned invalid release metadata.") from exc
    raise UpdateError(f"{tag} is missing {asset_name}.")


def fetch_release(
    repo: str, tag: str | None = None, *, timeout: int = 10
) -> Release:
    if tag is None or tag == "latest":
        endpoint = "releases/latest"
    else:
        tag = normalize_engine_selection(tag)
        endpoint = f"releases/tags/{quote(tag, safe='')}"
    request = Request(
        f"https://api.github.com/repos/{repo}/{endpoint}",
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "mcbe-gdk-installer",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_RELEASE_JSON + 1)
    except OSError as exc:
        raise UpdateError(f"Could not check {repo} releases: {exc}") from exc
    if len(raw) > MAX_RELEASE_JSON:
        raise UpdateError("GitHub returned an unexpectedly large release response.")
    try:
        data = json.loads(raw)
        release_tag = str(data["tag_name"])
        version_tuple(release_tag)
        assets = {
            str(asset["name"]): _github_url(
                str(asset["browser_download_url"]), repo, download=True
            )
            for asset in data.get("assets", [])
            if asset.get("state") == "uploaded"
        }
        return Release(
            repo=repo,
            tag=release_tag,
            name=str(data.get("name") or release_tag)[:200],
            body=str(data.get("body") or "")[:20_000],
            url=_github_url(str(data["html_url"]), repo),
            assets=assets,
        )
    except (KeyError, TypeError, ValueError, UpdateError) as exc:
        raise UpdateError("GitHub returned invalid release metadata.") from exc


def fetch_release_tags(repo: str, *, timeout: int = 10) -> list[str]:
    request = Request(
        f"https://api.github.com/repos/{repo}/releases?per_page=100",
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "mcbe-gdk-installer",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_RELEASE_LIST_JSON + 1)
    except OSError as exc:
        raise UpdateError(f"Could not check {repo} releases: {exc}") from exc
    if len(raw) > MAX_RELEASE_LIST_JSON:
        raise UpdateError("GitHub returned an unexpectedly large release response.")
    try:
        data = json.loads(raw)
        tags = [str(item["tag_name"]) for item in data]
    except (TypeError, KeyError, ValueError) as exc:
        raise UpdateError("GitHub returned invalid release metadata.") from exc
    releases = []
    for tag in tags:
        try:
            version_tuple(tag)
        except UpdateError:
            continue
        releases.append(tag)
    releases.sort(key=version_tuple, reverse=True)
    return releases


def fetch_latest_release(repo: str, *, timeout: int = 10) -> Release:
    return fetch_release(repo, timeout=timeout)


def read_installer_version(tool_root: Path) -> str:
    try:
        value = (tool_root / "VERSION").read_text(encoding="utf-8").strip()
        version_tuple(value)
        return value
    except (OSError, UpdateError):
        return "v0.0.0"


def _installed_engine_hashes(engine: Path) -> dict[str, str]:
    required = (
        "proton",
        "files/bin/wine",
        "files/bin/wineserver",
    )
    optional = ("files/lib/wine/x86_64-windows/xgameruntime.dll",)
    hashes = {}
    for relative in (*required, *optional):
        path = engine / relative
        if not path.is_file():
            if relative in optional:
                continue
            raise UpdateError(f"Installed engine is missing {relative}.")
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        hashes[relative] = digest.hexdigest()
    return hashes

def read_engine_version(root: Path) -> str | None:
    custom = read_custom_engine_metadata(root)
    if custom:
        return f"{custom['repository']}@{custom['tag']}"
    manifest = root / "engine/GDK-Proton-mcbe-gdk/engine-manifest.json"
    if not manifest.is_file():
        return None
    try:
        value = str(json.loads(manifest.read_text(encoding="utf-8"))["version"])
        version_tuple(value)
        return value
    except (OSError, KeyError, TypeError, ValueError, UpdateError):
        return "v0.0.0"


def engine_is_ready(root: Path, expected_version: str) -> bool:
    engine = root / "engine/GDK-Proton-mcbe-gdk"
    proton = engine / "proton"
    wineserver = engine / "files/bin/wineserver"
    return (
        read_engine_version(root) == expected_version
        and proton.is_file()
        and os.access(proton, os.X_OK)
        and wineserver.is_file()
        and os.access(wineserver, os.X_OK)
    )


def read_engine_selection(root: Path) -> str:
    selection = root / ENGINE_SELECTION_FILE
    if not selection.is_file():
        return "latest"
    try:
        return normalize_engine_selection(selection.read_text(encoding="utf-8"))
    except OSError as exc:
        raise UpdateError("The selected engine release is unavailable.") from exc


def check_for_updates(
    tool_root: Path,
    root: Path,
    *,
    raise_if_unavailable: bool = False,
) -> AvailableUpdates:
    try:
        installer = fetch_latest_release(INSTALLER_REPO)
    except UpdateError:
        installer = None
    try:
        selection = read_engine_selection(root)
        engine = (
            None
            if selection.startswith("https://")
            else fetch_release(ENGINE_REPO, selection)
        )
    except UpdateError:
        engine = None
    if raise_if_unavailable and installer is None and engine is None:
        raise UpdateError("Could not check GitHub releases.")
    current_engine = read_engine_version(root)
    return AvailableUpdates(
        installer=installer
        if installer and is_newer(installer.tag, read_installer_version(tool_root))
        else None,
        engine=engine
        if engine and current_engine and engine.tag != current_engine
        else None,
    )


def _download(
    url: str,
    destination: Path,
    max_size: int,
    progress: Callable[[int, int | None], None] | None = None,
) -> None:
    request = Request(url, headers={"User-Agent": "mcbe-gdk-installer"})
    try:
        with urlopen(request, timeout=30) as response, destination.open("wb") as output:
            declared = int(response.headers.get("Content-Length") or 0)
            if declared > max_size:
                raise UpdateError("Release asset is unexpectedly large.")
            total = 0
            if progress:
                progress(0, declared or None)
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > max_size:
                    raise UpdateError("Release asset is unexpectedly large.")
                output.write(chunk)
                if progress:
                    progress(total, declared or None)
    except (OSError, ValueError) as exc:
        raise UpdateError(f"Could not download the release: {exc}") from exc


def _asset(release: Release, name: str) -> str:
    try:
        return release.assets[name]
    except KeyError as exc:
        raise UpdateError(f"{release.tag} is missing {name}.") from exc


def _verify_checksum(archive: Path, checksum: Path) -> None:
    try:
        line = checksum.read_text(encoding="ascii").strip()
        expected, filename = re.fullmatch(
            r"([0-9a-fA-F]{64})[ \t]+\*?(.+)", line
        ).groups()
    except (AttributeError, OSError, UnicodeError) as exc:
        raise UpdateError("Release checksum is invalid.") from exc
    if filename != archive.name:
        raise UpdateError("Release checksum names a different asset.")
    _verify_digest(archive, expected)


def _verify_digest(archive: Path, expected: str) -> None:
    digest = hashlib.sha256()
    with archive.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest().lower() != expected.lower():
        raise UpdateError("Release checksum verification failed.")


def _download_verified(
    release: Release,
    archive_name: str,
    directory: Path,
    max_size: int,
    component: str,
    progress: ProgressCallback | None = None,
) -> Path:
    archive = directory / archive_name
    checksum = directory / f"{archive_name}.sha256"
    download_progress = None
    if progress:
        download_progress = lambda current, total: progress(
            f"{component}_download", current, total
        )
    _download(
        _asset(release, archive.name),
        archive,
        max_size,
        download_progress,
    )
    _download(_asset(release, checksum.name), checksum, 4096)
    if progress:
        progress(f"{component}_verify", None, None)
    _verify_checksum(archive, checksum)
    return archive


def _download_custom_engine(
    asset: CustomEngineAsset,
    directory: Path,
    progress: ProgressCallback | None = None,
) -> Path:
    archive = directory / asset.name
    download_progress = None
    if progress:
        download_progress = lambda current, total: progress(
            "engine_download", current, total
        )
    _download(asset.url, archive, 1_500_000_000, download_progress)
    if progress:
        progress("engine_verify", None, None)
    _verify_digest(archive, asset.sha256)
    return archive


def _validate_archive(
    archive: Path,
    expected_root: str | None,
    *,
    links: bool,
    max_unpacked: int,
) -> str:
    archive_root = expected_root
    unpacked = 0
    try:
        bundle = tarfile.open(archive, "r:gz")
    except (OSError, tarfile.TarError) as exc:
        raise UpdateError("Release archive is not a readable tar.gz file.") from exc
    with bundle:
        for count, member in enumerate(bundle, 1):
            if count > MAX_ARCHIVE_MEMBERS:
                raise UpdateError("Release archive contains too many entries.")
            if len(member.name) > MAX_ARCHIVE_PATH:
                raise UpdateError("Release archive contains an overlong path.")
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not path.parts:
                raise UpdateError("Release archive contains an unsafe path.")
            member_root = path.parts[0]
            if archive_root is None:
                archive_root = member_root
            elif member_root != archive_root:
                raise UpdateError("Release archive has an unexpected root directory.")
            if member.size > MAX_ARCHIVE_MEMBER:
                raise UpdateError("Release archive contains an oversized file.")
            if member.isfile():
                unpacked += member.size
                if unpacked > max_unpacked:
                    raise UpdateError("Release archive expands beyond its size limit.")
            elif not (
                member.isdir()
                or member.issym()
                or member.islnk()
            ):
                raise UpdateError("Release archive contains an unsupported file.")
            if member.issym() or member.islnk():
                if not links:
                    raise UpdateError("Installer archive contains an unexpected link.")
                base = path.parent if member.issym() else PurePosixPath(archive_root)
                target = posixpath.normpath(str(base / member.linkname))
                if target != archive_root and not target.startswith(archive_root + "/"):
                    raise UpdateError("Release archive contains an unsafe link.")
    if archive_root is None:
        raise UpdateError("Release archive is empty.")
    return archive_root


def _extract_archive(archive: Path, destination: Path) -> None:
    try:
        with tarfile.open(archive, "r:gz") as bundle:
            bundle.extractall(destination, filter="data")
    except (OSError, tarfile.TarError) as exc:
        raise UpdateError("Could not safely extract the release archive.") from exc


def _validate_custom_engine_archive(archive: Path) -> str:
    archive_root = _validate_archive(
        archive,
        None,
        links=True,
        max_unpacked=MAX_ENGINE_UNPACKED,
    )
    required = (
        f"{archive_root}/proton",
        f"{archive_root}/files/bin/wine",
        f"{archive_root}/files/bin/wineserver",
    )
    with tarfile.open(archive, "r:gz") as bundle:
        try:
            members = [bundle.getmember(name) for name in required]
        except KeyError as exc:
            raise UpdateError("Custom engine archive is missing its Proton runtime.") from exc
    if any(not member.isfile() or not member.mode & 0o111 for member in members):
        raise UpdateError("Custom engine archive has invalid Proton executables.")
    return archive_root


def _custom_engine_is_ready(root: Path, asset: CustomEngineAsset) -> bool:
    metadata = read_custom_engine_metadata(root)
    engine = root / "engine/GDK-Proton-mcbe-gdk"
    if (
        not metadata
        or metadata.get("schema") != 2
        or metadata["url"] != asset.url
        or metadata["sha256"] != asset.sha256
        or not isinstance(metadata.get("installed_sha256"), dict)
    ):
        return False
    try:
        return _installed_engine_hashes(engine) == metadata["installed_sha256"]
    except UpdateError:
        return False


def _apply_custom_engine_profile(
    source: Path, asset: CustomEngineAsset
) -> EngineProfile | None:
    profile = profile_for_asset(asset.repo, asset.tag, asset.name, asset.sha256)
    if not profile:
        return None
    if not profile.patch_gaming_services_gate:
        return profile

    runtime = source / "files/lib/wine/x86_64-windows/xgameruntime.dll"
    try:
        payload = runtime.read_bytes()
    except OSError as exc:
        raise UpdateError("Profiled engine is missing xgameruntime.dll.") from exc
    version_gate = bytes.fromhex("81 fe 4d 11 00 00 76 e4")
    patched_gate = bytes.fromhex("81 fe ff ff ff ff 76 e4")
    unpatched_count = payload.count(version_gate)
    patched_count = payload.count(patched_gate)
    if unpatched_count == 1 and patched_count == 0:
        runtime.write_bytes(payload.replace(version_gate, patched_gate, 1))
    elif unpatched_count > 1 or (unpatched_count and patched_count):
        raise UpdateError("Profiled engine has an ambiguous Gaming Services gate.")
    return profile


def _replace_directory(source: Path, destination: Path) -> Path:
    backup = destination.with_name(f"{destination.name}.previous")
    if backup.exists():
        shutil.rmtree(backup)
    destination.rename(backup)
    try:
        source.rename(destination)
    except Exception:
        backup.rename(destination)
        raise
    return backup


def install_installer_update(
    release: Release,
    tool_root: Path,
    root: Path,
    progress: ProgressCallback | None = None,
) -> None:
    if not (tool_root / ".mcbe-managed-source").is_file():
        raise UpdateError("Open the release page to update a source checkout.")
    archive_name = f"mcbe-gdk-installer-{release.tag}.tar.gz"
    with tempfile.TemporaryDirectory(
        prefix=".installer-update.", dir=tool_root.parent
    ) as temporary:
        work = Path(temporary)
        archive = _download_verified(
            release, archive_name, work, 25_000_000, "installer", progress
        )
        if progress:
            progress("installer_install", None, None)
        _validate_archive(
            archive,
            "mcbe-gdk-installer",
            links=False,
            max_unpacked=MAX_INSTALLER_UNPACKED,
        )
        _extract_archive(archive, work)
        source = work / "mcbe-gdk-installer"
        if read_installer_version(source) != release.tag:
            raise UpdateError("Installer archive version does not match its release.")
        (source / ".mcbe-managed-source").touch()
        backup = _replace_directory(source, tool_root)
        try:
            subprocess.run(
                [str(tool_root / "scripts/install-launchers.sh"), str(root), str(tool_root)],
                check=True,
            )
        except Exception:
            shutil.rmtree(tool_root)
            backup.rename(tool_root)
            subprocess.run(
                [str(tool_root / "scripts/install-launchers.sh"), str(root), str(tool_root)],
                check=False,
            )
            raise
        shutil.rmtree(backup)
        if progress:
            progress("installer_done", None, None)


def _apply_game_profile(root: Path) -> None:
    try:
        game_dir = Path(
            (root / "game-dir").read_text(encoding="utf-8").strip()
        ).expanduser()
    except OSError:
        return
    if not game_dir.is_dir():
        return
    try:
        apply_installed_engine_profile(root, game_dir)
    except BolError as exc:
        raise UpdateError(f"Could not apply the engine game profile: {exc}") from exc


def install_engine_update(
    release: Release,
    root: Path,
    progress: ProgressCallback | None = None,
) -> None:
    archive_name = f"GDK-Proton-mcbe-gdk-{release.tag}.tar.gz"
    engine_parent = root / "engine"
    engine_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".engine-update.", dir=engine_parent
    ) as temporary:
        work = Path(temporary)
        archive = _download_verified(
            release, archive_name, work, 1_500_000_000, "engine", progress
        )
        if progress:
            progress("engine_install", None, None)
        _validate_archive(
            archive,
            "GDK-Proton-mcbe-gdk",
            links=True,
            max_unpacked=MAX_ENGINE_UNPACKED,
        )
        _extract_archive(archive, work)
        source = work / "GDK-Proton-mcbe-gdk"
        try:
            manifest = json.loads(
                (source / "engine-manifest.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise UpdateError("Engine release manifest is missing or invalid.") from exc
        if manifest.get("version") != release.tag:
            raise UpdateError("Engine manifest version does not match its release.")
        destination = engine_parent / "GDK-Proton-mcbe-gdk"
        if destination.exists():
            backup = _replace_directory(source, destination)
            shutil.rmtree(backup)
        else:
            source.rename(destination)
        if progress:
            progress("engine_done", None, None)


def switch_engine(
    root: Path,
    selection: str,
    progress: ProgressCallback | None = None,
) -> Release:
    """Install the selected engine release and persist the selection."""
    selected = normalize_engine_selection(selection)
    release = fetch_release(ENGINE_REPO, selected)
    if not engine_is_ready(root, release.tag):
        install_engine_update(release, root, progress)
    root.mkdir(parents=True, exist_ok=True)
    _apply_game_profile(root)
    (root / ENGINE_SELECTION_FILE).write_text(selected + "\n", encoding="utf-8")
    return release


def install_custom_engine(
    asset: CustomEngineAsset,
    root: Path,
    progress: ProgressCallback | None = None,
) -> None:
    engine_parent = root / "engine"
    engine_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".engine-update.", dir=engine_parent
    ) as temporary:
        work = Path(temporary)
        archive = _download_custom_engine(asset, work, progress)
        if progress:
            progress("engine_install", None, None)
        archive_root = _validate_custom_engine_archive(archive)
        _extract_archive(archive, work)
        source = work / archive_root
        profile = _apply_custom_engine_profile(source, asset)
        metadata = {
            "schema": 2,
            "repository": asset.repo,
            "tag": asset.tag,
            "asset": asset.name,
            "url": asset.url,
            "sha256": asset.sha256,
            "installed_sha256": _installed_engine_hashes(source),
        }
        if profile:
            metadata["profile"] = profile.identifier
            metadata["capabilities"] = profile.capabilities()
        metadata_path = source / CUSTOM_ENGINE_METADATA
        metadata_path.unlink(missing_ok=True)
        metadata_path.write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        destination = engine_parent / "GDK-Proton-mcbe-gdk"
        if destination.exists():
            backup = _replace_directory(source, destination)
            shutil.rmtree(backup)
        else:
            source.rename(destination)
        if progress:
            progress("engine_done", None, None)


def install_available_updates(
    updates: AvailableUpdates,
    tool_root: Path,
    root: Path,
    progress: ProgressCallback | None = None,
) -> bool:
    if updates.engine:
        install_engine_update(updates.engine, root, progress)
    if updates.installer:
        install_installer_update(updates.installer, tool_root, root, progress)
    return bool(updates.installer)


def _install_updates_cli(tool_root: Path, root: Path) -> int:
    print("Checking for updates…")
    updates = check_for_updates(tool_root, root, raise_if_unavailable=True)
    if not updates:
        print("No updates available.")
        return 0

    labels = {
        "engine_download": "Downloading compatibility engine",
        "engine_verify": "Verifying compatibility engine",
        "engine_install": "Installing compatibility engine",
        "engine_done": "Compatibility engine updated",
        "installer_download": "Downloading MCBE GDK Installer",
        "installer_verify": "Verifying MCBE GDK Installer",
        "installer_install": "Installing MCBE GDK Installer",
        "installer_done": "MCBE GDK Installer updated",
    }
    last_stage = ""
    last_bucket = -1

    def size_label(value: int) -> str:
        if value >= 1024**2:
            return f"{value / 1024**2:.0f} MB"
        return f"{value / 1024:.0f} KB"

    def progress(stage: str, current: int | None, total: int | None) -> None:
        nonlocal last_stage, last_bucket
        label = labels.get(stage, "Installing updates")
        if stage != last_stage:
            last_stage = stage
            last_bucket = -1
        if stage.endswith("_download") and current is not None and total:
            percent = min(round(current / total * 100), 100)
            bucket = percent // 10
            if bucket == last_bucket:
                return
            last_bucket = bucket
            print(
                f"{label}: {percent}% "
                f"({size_label(current)} of {size_label(total)})"
            )
        elif last_bucket < 0:
            last_bucket = 0
            print(f"{label}…")

    install_available_updates(updates, tool_root, root, progress)
    print("Updates installed.")
    return 0


def _engine_cli(root: Path, selection: str | None) -> int:
    current = read_engine_version(root)
    selection_file = root / ENGINE_SELECTION_FILE
    if selection is None:
        selected = (
            selection_file.read_text(encoding="utf-8").strip()
            if selection_file.is_file()
            else "not set"
        )
        print(f"Current engine: {current or 'not installed'}")
        print(f"Selected engine: {selected}")
        return 0

    selected = normalize_engine_selection(selection)
    print(f"Resolving compatibility engine {selected}…")
    custom_asset = (
        fetch_custom_engine(selected) if selected.startswith("https://") else None
    )
    release = None if custom_asset else fetch_release(ENGINE_REPO, selected)
    already_installed = (
        bool(custom_asset and _custom_engine_is_ready(root, custom_asset))
        or bool(release and engine_is_ready(root, release.tag))
    )
    if already_installed:
        root.mkdir(parents=True, exist_ok=True)
        _apply_game_profile(root)
        selection_file.write_text(selected + "\n", encoding="utf-8")
        identity = (
            f"{custom_asset.repo}@{custom_asset.tag}"
            if custom_asset
            else release.tag
        )
        print(f"Compatibility engine {identity} is already installed.")
        return 0
    seen: set[str] = set()
    labels = {
        "engine_download": "Downloading compatibility engine",
        "engine_verify": "Verifying compatibility engine",
        "engine_install": "Installing compatibility engine",
        "engine_done": "Compatibility engine installed",
    }

    def progress(stage: str, _current: int | None, _total: int | None) -> None:
        if stage not in seen:
            seen.add(stage)
            print(f"{labels.get(stage, 'Switching compatibility engine')}…")

    if custom_asset:
        install_custom_engine(custom_asset, root, progress)
        identity = f"{custom_asset.repo}@{custom_asset.tag}"
    else:
        assert release
        install_engine_update(release, root, progress)
        identity = release.tag
    _apply_game_profile(root)
    selection_file.write_text(selected + "\n", encoding="utf-8")
    print(f"Switched compatibility engine to {identity}.")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[1] == "latest-tag":
        try:
            print(fetch_latest_release(argv[2]).tag)
            return 0
        except UpdateError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    if len(argv) == 4 and argv[1] == "install":
        try:
            return _install_updates_cli(
                Path(argv[2]).expanduser().resolve(),
                Path(argv[3]).expanduser().resolve(),
            )
        except (OSError, subprocess.SubprocessError, UpdateError) as exc:
            print(f"Update failed: {exc}", file=sys.stderr)
            return 1
    if len(argv) in (3, 4) and argv[1] == "engine":
        try:
            return _engine_cli(
                Path(argv[2]).expanduser().resolve(),
                argv[3] if len(argv) == 4 else None,
            )
        except (OSError, subprocess.SubprocessError, UpdateError) as exc:
            print(f"Engine switch failed: {exc}", file=sys.stderr)
            return 1
    print(
        f"Usage: {argv[0]} latest-tag OWNER/REPOSITORY | "
        "install SOURCE ROOT | "
        "engine ROOT [VERSION|latest|GITHUB-RELEASE-ASSET-URL]",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
