"""Declarative compatibility behavior for reviewed engine releases."""
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CUSTOM_ENGINE_METADATA = ".mcbe-gdk-engine.json"
LUKAS_ENGINE_PROFILE_ID = "lukas-remote-connect-v1"
LUKAS_EXPERIMENTAL_PROFILE_ID = "mcbe-lukas-v0.2.0-ex-v1"
LUKAS_EXPERIMENTAL_TAG = "v0.2.0-ex"
LUKAS_EXPERIMENTAL_ASSET = "GDK-Proton10-32-Custom-4.tar.gz"
LUKAS_EXPERIMENTAL_SHA256 = (
    "4d19774c64451d4f1395dc4c5f4b6e8b5fdbc1ce6c05e29a855f5e0678b8800c"
)
EXPERIMENTAL_ENGINE_PROFILE_ID = "mcbe-v0.2.0-experimental-v1"
EXPERIMENTAL_ENGINE_TAG = "v0.2.0-experimental"
EXPERIMENTAL_ENGINE_ASSET = (
    "GDK-Proton-mcbe-gdk-v0.2.0-experimental.tar.gz"
)
EXPERIMENTAL_ENGINE_SHA256 = (
    "92b767dbd3bb08bf8bcac4d75147d9cf53514d96d378f2efc2806a2b9fb4a3ee"
)


@dataclass(frozen=True)
class EngineProfile:
    identifier: str
    repository: str
    authentication: str
    msa_app_id: str | None = None
    title_id: str | None = None
    disable_app_runtime_bootstrap: bool = False
    login_request_parent_levels: int = 0
    patch_gaming_services_gate: bool = False
    tag: str | None = None
    asset: str | None = None
    sha256: str | None = None
    ignore_gaming_services_version: bool = False

    def capabilities(self) -> dict[str, Any]:
        # Keep this serialized contract limited to behavior consumed by older
        # installer builds. Exact release pins and registry policy are verified
        # independently below and are not publisher-controlled metadata.
        return {
            "authentication": self.authentication,
            "disable_app_runtime_bootstrap": self.disable_app_runtime_bootstrap,
            "login_request_parent_levels": self.login_request_parent_levels,
            "msa_app_id": self.msa_app_id,
            "title_id": self.title_id,
            "patch_gaming_services_gate": self.patch_gaming_services_gate,
        }


# Generic direct-upstream profile retained for existing custom selections and
# tests. Its legacy runtime requires the narrowly scoped byte patch below.
LUKAS_ENGINE_PROFILE = EngineProfile(
    identifier=LUKAS_ENGINE_PROFILE_ID,
    repository="LukasPAH/GDK-Proton-Custom",
    authentication="remote-connect-json",
    msa_app_id="0000000048183522",
    title_id="67b57dac",
    disable_app_runtime_bootstrap=True,
    login_request_parent_levels=1,
    patch_gaming_services_gate=True,
)

# Legacy project mirror retained so an existing installation can still restore
# its profile. It is no longer exposed as a selectable preset.
LUKAS_EXPERIMENTAL_PROFILE = EngineProfile(
    identifier=LUKAS_EXPERIMENTAL_PROFILE_ID,
    repository="veedy-dev/mcbe-gdk-engine",
    authentication="remote-connect-json",
    msa_app_id="0000000048183522",
    title_id="67b57dac",
    disable_app_runtime_bootstrap=True,
    login_request_parent_levels=1,
    patch_gaming_services_gate=False,
    tag=LUKAS_EXPERIMENTAL_TAG,
    asset=LUKAS_EXPERIMENTAL_ASSET,
    sha256=LUKAS_EXPERIMENTAL_SHA256,
    ignore_gaming_services_version=True,
)

# Source-built experimental profile with the Gaming Services gate fixed in the
# maintained engine source and verified by the pinned release build.
EXPERIMENTAL_ENGINE_PROFILE = EngineProfile(
    identifier=EXPERIMENTAL_ENGINE_PROFILE_ID,
    repository="veedy-dev/mcbe-gdk-engine",
    authentication="remote-connect-json",
    msa_app_id="0000000048183522",
    title_id="67b57dac",
    disable_app_runtime_bootstrap=True,
    login_request_parent_levels=1,
    patch_gaming_services_gate=False,
    tag=EXPERIMENTAL_ENGINE_TAG,
    asset=EXPERIMENTAL_ENGINE_ASSET,
    sha256=EXPERIMENTAL_ENGINE_SHA256,
    ignore_gaming_services_version=True,
)

_PROFILES = (
    LUKAS_ENGINE_PROFILE,
    LUKAS_EXPERIMENTAL_PROFILE,
    EXPERIMENTAL_ENGINE_PROFILE,
)
_PROFILES_BY_ID = {profile.identifier: profile for profile in _PROFILES}


def profile_for_asset(
    repository: str, tag: str, asset: str, sha256: str
) -> EngineProfile | None:
    for profile in _PROFILES:
        if profile.repository.casefold() != repository.casefold():
            continue
        if profile.tag is not None and profile.tag != tag:
            continue
        if profile.asset is not None and profile.asset != asset:
            continue
        if profile.sha256 is not None and profile.sha256 != sha256:
            continue
        return profile
    return None


def read_custom_engine_metadata(root: Path) -> dict[str, Any] | None:
    path = (
        Path(root)
        / "engine"
        / "GDK-Proton-mcbe-gdk"
        / CUSTOM_ENGINE_METADATA
    )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return None
    if not isinstance(data, Mapping):
        return None
    required = ("repository", "tag", "asset", "url", "sha256")
    if data.get("schema") not in (1, 2) or any(
        not isinstance(data.get(key), str) or not data[key] for key in required
    ):
        return None
    return dict(data)


def installed_engine_profile(root: Path) -> EngineProfile | None:
    metadata = read_custom_engine_metadata(root)
    if not metadata:
        return None
    identifier = metadata.get("profile")
    profile = _PROFILES_BY_ID.get(identifier) if isinstance(identifier, str) else None
    if not profile or metadata["repository"].casefold() != profile.repository.casefold():
        return None
    if (
        metadata.get("schema") != 2
        or metadata.get("capabilities") != profile.capabilities()
    ):
        return None
    for key in ("tag", "asset", "sha256"):
        expected = getattr(profile, key)
        if expected is not None and metadata.get(key) != expected:
            return None
    return profile
