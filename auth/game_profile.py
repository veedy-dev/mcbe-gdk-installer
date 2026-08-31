"""Transactional, reversible game-file changes required by engine profiles."""
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
import json
import os
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

from .engine_profiles import EngineProfile, installed_engine_profile
from .log import BolError

_STATE_SCHEMA = 1
_STATE_NAME = "game-profile.json"
_CONFIG_BACKUP = "MicrosoftGame.Config.original"
_LEGACY_CONFIG_BACKUP = "MicrosoftGame.Config.mcbe-original"
_LEGACY_CONFIG_GENERATED = ".mcbe-lukas-config-generated"
_LEGACY_BOOTSTRAP_DISABLED = (
    "Microsoft.WindowsAppRuntime.Bootstrap.dll.mcbe-lukas-disabled"
)
_BOOTSTRAP_BACKUP = "Microsoft.WindowsAppRuntime.Bootstrap.dll.original"


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _state_dir(root: Path) -> Path:
    return Path(root) / "profile" / "engine-state"


def _state_path(root: Path) -> Path:
    return _state_dir(root) / _STATE_NAME


def _write_state(root: Path, state: dict) -> None:
    directory = _state_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / f".{_STATE_NAME}.{os.getpid()}"
    try:
        temporary.write_text(
            json.dumps(state, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, _state_path(root))
    finally:
        temporary.unlink(missing_ok=True)


def _read_state(root: Path) -> dict | None:
    try:
        state = json.loads(_state_path(root).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, TypeError, ValueError) as exc:
        raise BolError("The engine game-profile state is invalid.") from exc
    if state.get("schema") != _STATE_SCHEMA:
        raise BolError("The engine game-profile state uses an unsupported schema.")
    return state


def _local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _first_element(root: ET.Element, name: str) -> ET.Element | None:
    return next(
        (element for element in root.iter() if _local_name(element) == name),
        None,
    )


def _package_version(game_dir: Path) -> str:
    try:
        package = ET.parse(game_dir / "appxmanifest.xml").getroot()
    except (OSError, ET.ParseError) as exc:
        raise BolError("appxmanifest.xml is missing or invalid.") from exc
    identity = _first_element(package, "Identity")
    version = identity.get("Version") if identity is not None else None
    if not version:
        raise BolError("appxmanifest.xml is missing the Minecraft version.")
    return version


def _new_game_config(appx_manifest: Path) -> ET.Element:
    try:
        package = ET.parse(appx_manifest).getroot()
    except (OSError, ET.ParseError) as exc:
        raise BolError(
            "MicrosoftGame.Config is missing and appxmanifest.xml is invalid."
        ) from exc
    identity = _first_element(package, "Identity")
    application = _first_element(package, "Application")
    properties = _first_element(package, "Properties")
    visuals = _first_element(package, "VisualElements")
    splash = _first_element(package, "SplashScreen")
    required_identity = ("Name", "Publisher", "Version")
    if (
        identity is None
        or application is None
        or any(not identity.get(name) for name in required_identity)
    ):
        raise BolError("appxmanifest.xml is missing the Minecraft identity.")

    game = ET.Element("Game", {"configVersion": "1"})
    ET.SubElement(
        game,
        "Identity",
        {name: identity.get(name, "") for name in required_identity},
    )
    executables = ET.SubElement(game, "ExecutableList")
    ET.SubElement(
        executables,
        "Executable",
        {
            "Name": application.get("Executable", "Minecraft.Windows.exe"),
            "Id": application.get("Id", "Game"),
        },
    )

    def property_text(name: str, fallback: str) -> str:
        element = (
            next(
                (
                    child
                    for child in properties
                    if _local_name(child) == name
                ),
                None,
            )
            if properties is not None
            else None
        )
        return (element.text or fallback) if element is not None else fallback

    visual = visuals.attrib if visuals is not None else {}
    ET.SubElement(
        game,
        "ShellVisuals",
        {
            "DefaultDisplayName": visual.get(
                "DisplayName", property_text("DisplayName", "Minecraft")
            ),
            "PublisherDisplayName": property_text(
                "PublisherDisplayName", "Microsoft Studios"
            ),
            "Square150x150Logo": visual.get("Square150x150Logo", "Logo.png"),
            "Square44x44Logo": visual.get("Square44x44Logo", "SmallLogo.png"),
            "StoreLogo": property_text("Logo", "StoreLogo.png"),
            "Description": visual.get(
                "Description", property_text("Description", "Minecraft")
            ),
            "ForegroundText": visual.get("ForegroundText", "light"),
            "BackgroundColor": visual.get("BackgroundColor", "transparent"),
            "SplashScreenImage": (
                splash.get("Image", "MCSplashScreen.png")
                if splash is not None
                else "MCSplashScreen.png"
            ),
        },
    )
    return game


def _write_xml(root: ET.Element, destination: Path) -> None:
    temporary = destination.with_name(f".{destination.name}.mcbe-{os.getpid()}")
    try:
        ET.indent(root, space="  ")
        ET.ElementTree(root).write(
            temporary,
            encoding="utf-8",
            xml_declaration=True,
        )
        os.chmod(temporary, 0o644)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _profile_state(root: Path, game_dir: Path, profile: EngineProfile) -> dict:
    config = game_dir / "MicrosoftGame.Config"
    return {
        "schema": _STATE_SCHEMA,
        "status": "applying",
        "profile": profile.identifier,
        "game_dir": str(game_dir),
        "game_version": _package_version(game_dir),
        "config_mode": "original" if config.is_file() else "generated",
        "managed_config_sha256": None,
        "bootstrap_managed": bool(
            profile.disable_app_runtime_bootstrap
            and (game_dir / "Microsoft.WindowsAppRuntime.Bootstrap.dll").is_file()
        ),
    }


def _ensure_profile(root: Path, state: dict, profile: EngineProfile) -> None:
    game_dir = Path(state["game_dir"])
    state_directory = _state_dir(root)
    config = game_dir / "MicrosoftGame.Config"
    if (
        state.get("status") == "active"
        and state.get("managed_config_sha256")
        and config.is_file()
        and _digest(config) != state["managed_config_sha256"]
    ):
        raise BolError(
            "MicrosoftGame.Config changed after profile setup; "
            "refusing to overwrite it."
        )
    config_backup = state_directory / _CONFIG_BACKUP
    if state["config_mode"] == "original" and not config_backup.exists():
        if not config.is_file():
            raise BolError("MicrosoftGame.Config disappeared before it was backed up.")
        shutil.copy2(config, config_backup)
        os.chmod(config_backup, 0o600)

    if config.is_file():
        try:
            config_root = ET.parse(config).getroot()
        except ET.ParseError as exc:
            raise BolError("MicrosoftGame.Config is invalid.") from exc
        if _local_name(config_root) != "Game":
            raise BolError("MicrosoftGame.Config has an unexpected root.")
    else:
        config_root = _new_game_config(game_dir / "appxmanifest.xml")

    for name, value in (
        ("MSAAppId", profile.msa_app_id),
        ("TitleId", profile.title_id),
    ):
        if value is None:
            continue
        element = _first_element(config_root, name)
        if element is None:
            element = ET.SubElement(config_root, name)
        element.text = value
    _write_xml(config_root, config)
    state["managed_config_sha256"] = _digest(config)

    if state["bootstrap_managed"]:
        bootstrap = game_dir / "Microsoft.WindowsAppRuntime.Bootstrap.dll"
        backup = state_directory / _BOOTSTRAP_BACKUP
        if bootstrap.exists() and not backup.exists():
            shutil.copy2(bootstrap, backup)
            os.chmod(backup, 0o600)
            bootstrap.unlink()
        elif bootstrap.exists() and backup.exists():
            if _digest(bootstrap) != _digest(backup):
                raise BolError("Windows App Runtime bootstrap changed during profile setup.")
            bootstrap.unlink()
        elif not backup.exists():
            raise BolError("Windows App Runtime bootstrap backup is missing.")

    state["status"] = "active"
    _write_state(root, state)


def restore_game_profile(root: Path) -> None:
    root = Path(root)
    state = _read_state(root)
    if not state:
        return
    game_dir = Path(state.get("game_dir", ""))
    state_directory = _state_dir(root)
    config = game_dir / "MicrosoftGame.Config"
    same_build = False
    try:
        same_build = (
            game_dir.is_dir()
            and _package_version(game_dir) == state["game_version"]
        )
    except (KeyError, BolError):
        same_build = False

    if same_build and config.exists() and state.get("managed_config_sha256"):
        if _digest(config) != state["managed_config_sha256"]:
            raise BolError(
                "MicrosoftGame.Config changed after profile setup; "
                "refusing to overwrite it."
            )
        if state.get("config_mode") == "original":
            backup = state_directory / _CONFIG_BACKUP
            if not backup.is_file():
                raise BolError("The original MicrosoftGame.Config backup is missing.")
            shutil.copy2(backup, config)
        else:
            config.unlink()

    bootstrap_backup = state_directory / _BOOTSTRAP_BACKUP
    bootstrap = game_dir / "Microsoft.WindowsAppRuntime.Bootstrap.dll"
    if (
        same_build
        and state.get("bootstrap_managed")
        and bootstrap_backup.is_file()
        and not bootstrap.exists()
    ):
        shutil.copy2(bootstrap_backup, bootstrap)

    for path in (
        state_directory / _CONFIG_BACKUP,
        state_directory / _BOOTSTRAP_BACKUP,
        _state_path(root),
    ):
        path.unlink(missing_ok=True)
    try:
        state_directory.rmdir()
    except OSError:
        pass


def _restore_legacy_game_profile(game_dir: Path) -> None:
    config = game_dir / "MicrosoftGame.Config"
    backup = game_dir / _LEGACY_CONFIG_BACKUP
    generated = game_dir / _LEGACY_CONFIG_GENERATED
    if backup.exists():
        config.unlink(missing_ok=True)
        backup.rename(config)
    elif generated.exists():
        config.unlink(missing_ok=True)
    generated.unlink(missing_ok=True)

    bootstrap = game_dir / "Microsoft.WindowsAppRuntime.Bootstrap.dll"
    disabled = game_dir / _LEGACY_BOOTSTRAP_DISABLED
    if disabled.exists() and not bootstrap.exists():
        disabled.rename(bootstrap)


def apply_game_profile(
    root: Path,
    game_dir: Path,
    profile: EngineProfile | None,
) -> None:
    root = Path(root)
    game_dir = Path(game_dir).resolve()
    state = _read_state(root)
    if not state:
        _restore_legacy_game_profile(game_dir)
    if profile is None:
        restore_game_profile(root)
        return

    version = _package_version(game_dir)
    if state and (
        state.get("profile") != profile.identifier
        or state.get("game_dir") != str(game_dir)
        or state.get("game_version") != version
    ):
        restore_game_profile(root)
        state = None
    if not state:
        state = _profile_state(root, game_dir, profile)
        _write_state(root, state)
    _ensure_profile(root, state, profile)


def apply_installed_engine_profile(root: Path, game_dir: Path) -> None:
    apply_game_profile(root, game_dir, installed_engine_profile(root))


def login_request_path(game_dir: Path, profile: EngineProfile) -> Path:
    path = Path(game_dir).resolve()
    for _ in range(profile.login_request_parent_levels):
        path = path.parent
    return path / "login.json"
