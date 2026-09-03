import hashlib
import io
import json
import os
import sys
import tarfile
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
os.environ.setdefault("MCBE_GDK_ROOT", "/tmp/mcbe-gdk-update-tests")

from auth.engine_profiles import (  # noqa: E402
    EXPERIMENTAL_ENGINE_PROFILE,
    LUKAS_EXPERIMENTAL_PROFILE,
    STABLE_ENGINE_PROFILE,
    installed_engine_profile,
    profile_for_asset,
)

from updates import (  # noqa: E402
    ENGINE_REPO,
    INSTALLER_REPO,
    AvailableUpdates,
    Release,
    CustomEngineAsset,
    UpdateError,
    _apply_custom_engine_profile,
    _custom_engine_is_ready,
    _download_verified,
    _engine_cli,
    _install_updates_cli,
    _validate_archive,
    _verify_checksum,
    check_for_updates,
    fetch_custom_engine,
    fetch_latest_release,
    fetch_release,
    fetch_release_tags,
    engine_is_ready,
    is_newer,
    install_custom_engine,
    install_engine_update,
    normalize_engine_selection,
    read_engine_version,
    switch_engine,
)


class Response:
    def __init__(self, data: bytes):
        self.data = data
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, _size=-1):
        data, self.data = self.data, b""
        return data


def release(repo: str, tag: str) -> Release:
    archive = (
        f"mcbe-gdk-installer-{tag}.tar.gz"
        if repo == INSTALLER_REPO
        else f"GDK-Proton-mcbe-gdk-{tag}.tar.gz"
    )
    base = f"https://github.com/{repo}/releases/download/{tag}"
    return Release(
        repo=repo,
        tag=tag,
        name=tag,
        body="Changes",
        url=f"https://github.com/{repo}/releases/tag/{tag}",
        assets={
            archive: f"{base}/{archive}",
            f"{archive}.sha256": f"{base}/{archive}.sha256",
        },
    )


class UpdateTests(unittest.TestCase):
    def test_semantic_versions_do_not_use_lexical_order(self):
        self.assertTrue(is_newer("v0.1.10", "v0.1.9"))
        self.assertFalse(is_newer("v0.1.2", "v0.1.2"))
        with self.assertRaises(UpdateError):
            is_newer("latest", "v0.1.2")

    def test_engine_selection_accepts_cli_versions(self):
        self.assertEqual(normalize_engine_selection("0.1.5"), "v0.1.5")
        self.assertEqual(normalize_engine_selection("v0.1.5"), "v0.1.5")
        self.assertEqual(normalize_engine_selection("latest"), "latest")
        with self.assertRaises(UpdateError):
            normalize_engine_selection("main")

    def test_engine_selection_accepts_github_release_asset_urls(self):
        url = (
            "https://github.com/LukasPAH/GDK-Proton-Custom/releases/download/"
            "release-10-32-4/GDK-Proton10-32-Custom-4.tar.gz"
        )
        self.assertEqual(normalize_engine_selection(url), url)
        for invalid in (
            "https://example.com/engine.tar.gz",
            "https://github.com/owner/repo/archive/main.tar.gz",
            "https://github.com/owner/repo/releases/download/tag/engine.zip",
        ):
            with self.assertRaises(UpdateError):
                normalize_engine_selection(invalid)

    def test_custom_engine_metadata_and_digest_are_resolved(self):
        url = (
            "https://github.com/LukasPAH/GDK-Proton-Custom/releases/download/"
            "release-10-32-4/GDK-Proton10-32-Custom-4.tar.gz"
        )
        digest = "4d19774c64451d4f1395dc4c5f4b6e8b5fdbc1ce6c05e29a855f5e0678b8800c"
        data = {
            "tag_name": "release-10-32-4",
            "assets": [
                {
                    "name": "GDK-Proton10-32-Custom-4.tar.gz",
                    "state": "uploaded",
                    "digest": f"sha256:{digest}",
                    "browser_download_url": url,
                }
            ],
        }
        with patch("updates.urlopen", return_value=Response(json.dumps(data).encode())):
            asset = fetch_custom_engine(url)
        self.assertEqual(asset.repo, "LukasPAH/GDK-Proton-Custom")
        self.assertEqual(asset.tag, "release-10-32-4")
        self.assertEqual(asset.sha256, digest)

        data["assets"][0]["digest"] = None
        with patch("updates.urlopen", return_value=Response(json.dumps(data).encode())):
            with self.assertRaisesRegex(UpdateError, "no SHA-256 digest"):
                fetch_custom_engine(url)

    def test_latest_release_metadata_is_validated(self):
        repo = INSTALLER_REPO
        data = {
            "tag_name": "v0.1.3",
            "name": "MCBE GDK Installer v0.1.3",
            "body": "Automatic updates",
            "html_url": f"https://github.com/{repo}/releases/tag/v0.1.3",
            "assets": [
                {
                    "name": "mcbe-gdk-installer-v0.1.3.tar.gz",
                    "state": "uploaded",
                    "browser_download_url": (
                        f"https://github.com/{repo}/releases/download/v0.1.3/"
                        "mcbe-gdk-installer-v0.1.3.tar.gz"
                    ),
                }
            ],
        }
        with patch("updates.urlopen", return_value=Response(json.dumps(data).encode())):
            latest = fetch_latest_release(repo)
        self.assertEqual(latest.tag, "v0.1.3")
        self.assertIn("mcbe-gdk-installer-v0.1.3.tar.gz", latest.assets)

        data["html_url"] = "https://example.com/update"
        with patch("updates.urlopen", return_value=Response(json.dumps(data).encode())):
            with self.assertRaises(UpdateError):
                fetch_latest_release(repo)

    def test_checks_installer_and_engine_independently(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tool = root / "source"
            tool.mkdir()
            (tool / "VERSION").write_text("v0.1.2\n")
            engine = root / "engine/GDK-Proton-mcbe-gdk"
            engine.mkdir(parents=True)
            (engine / "engine-manifest.json").write_text(
                json.dumps({"version": "v0.1.2"})
            )
            with patch(
                "updates.fetch_latest_release",
                return_value=release(INSTALLER_REPO, "v0.1.3"),
            ), patch(
                "updates.fetch_release", side_effect=UpdateError("offline")
            ) as fetch:
                available = check_for_updates(tool, root)
            self.assertEqual(available.installer.tag, "v0.1.3")
            self.assertIsNone(available.engine)
            fetch.assert_called_once_with(ENGINE_REPO, "latest")

            with patch(
                "updates.fetch_latest_release", side_effect=UpdateError("offline")
            ), patch(
                "updates.fetch_release", side_effect=UpdateError("offline")
            ):
                with self.assertRaises(UpdateError):
                    check_for_updates(tool, root, raise_if_unavailable=True)

    def test_selected_engine_release_can_downgrade(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tool = root / "source"
            tool.mkdir()
            (tool / "VERSION").write_text("v0.1.3\n")
            (root / "engine-release").write_text("v0.1.5\n")
            engine = root / "engine/GDK-Proton-mcbe-gdk"
            engine.mkdir(parents=True)
            (engine / "engine-manifest.json").write_text(
                json.dumps({"version": "v0.1.7"})
            )
            selected = release(ENGINE_REPO, "v0.1.5")
            with patch(
                "updates.fetch_latest_release",
                return_value=release(INSTALLER_REPO, "v0.1.3"),
            ), patch("updates.fetch_release", return_value=selected) as fetch:
                available = check_for_updates(tool, root)
            self.assertEqual(available.engine, selected)
            fetch.assert_called_once_with(ENGINE_REPO, "v0.1.5")

    def test_custom_engine_selection_stays_pinned_during_update_checks(self):
        url = (
            "https://github.com/owner/custom-engine/releases/download/build-4/"
            "custom-engine.tar.gz"
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tool = root / "source"
            tool.mkdir()
            (tool / "VERSION").write_text("v0.1.3\n")
            (root / "engine-release").write_text(url + "\n")
            engine = root / "engine/GDK-Proton-mcbe-gdk"
            engine.mkdir(parents=True)
            (engine / ".mcbe-gdk-engine.json").write_text(
                json.dumps(
                    {
                        "schema": 1,
                        "repository": "owner/custom-engine",
                        "tag": "build-4",
                        "asset": "custom-engine.tar.gz",
                        "url": url,
                        "sha256": "a" * 64,
                    }
                )
            )
            with patch(
                "updates.fetch_latest_release",
                return_value=release(INSTALLER_REPO, "v0.1.3"),
            ), patch("updates.fetch_release") as fetch:
                available = check_for_updates(tool, root)
            self.assertFalse(available)
            fetch.assert_not_called()

    def test_engine_cli_switches_and_persists_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            engine = root / "engine/GDK-Proton-mcbe-gdk"
            engine.mkdir(parents=True)
            (engine / "engine-manifest.json").write_text(
                json.dumps({"version": "v0.1.7"})
            )
            selected = release(ENGINE_REPO, "v0.1.5")
            output = io.StringIO()
            with patch("updates.fetch_release", return_value=selected) as fetch, patch(
                "updates.install_engine_update"
            ) as install, redirect_stdout(output):
                result = _engine_cli(root, "0.1.5")
            self.assertEqual(result, 0)
            self.assertEqual((root / "engine-release").read_text(), "v0.1.5\n")
            fetch.assert_called_once_with(ENGINE_REPO, "v0.1.5")
            install.assert_called_once()
            self.assertIn("Switched compatibility engine to v0.1.5.", output.getvalue())

    def test_engine_cli_switches_to_custom_release_asset(self):
        url = (
            "https://github.com/LukasPAH/GDK-Proton-Custom/releases/download/"
            "release-10-32-4/GDK-Proton10-32-Custom-4.tar.gz"
        )
        asset = CustomEngineAsset(
            repo="LukasPAH/GDK-Proton-Custom",
            tag="release-10-32-4",
            name="GDK-Proton10-32-Custom-4.tar.gz",
            url=url,
            sha256="4d19774c64451d4f1395dc4c5f4b6e8b5fdbc1ce6c05e29a855f5e0678b8800c",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            engine = root / "engine/GDK-Proton-mcbe-gdk"
            engine.mkdir(parents=True)
            (engine / "engine-manifest.json").write_text(
                json.dumps({"version": "v0.1.7"})
            )
            output = io.StringIO()
            with patch("updates.fetch_custom_engine", return_value=asset) as fetch, patch(
                "updates.install_custom_engine"
            ) as install, redirect_stdout(output):
                result = _engine_cli(root, url)
            self.assertEqual(result, 0)
            self.assertEqual((root / "engine-release").read_text(), url + "\n")
            fetch.assert_called_once_with(url)
            install.assert_called_once()
            self.assertIn(
                "Switched compatibility engine to "
                "LukasPAH/GDK-Proton-Custom@release-10-32-4.",
                output.getvalue(),
            )

    def test_custom_engine_archive_is_normalized_and_identified(self):
        url = (
            "https://github.com/owner/custom-engine/releases/download/build-4/"
            "custom-engine.tar.gz"
        )
        asset = CustomEngineAsset(
            repo="owner/custom-engine",
            tag="build-4",
            name="custom-engine.tar.gz",
            url=url,
            sha256="a" * 64,
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / asset.name
            with tarfile.open(archive, "w:gz") as bundle:
                for name in (
                    "Custom-Proton/proton",
                    "Custom-Proton/files/bin/wine",
                    "Custom-Proton/files/bin/wineserver",
                ):
                    info = tarfile.TarInfo(name)
                    info.mode = 0o755
                    info.size = len(name)
                    bundle.addfile(info, io.BytesIO(name.encode()))
            destination = root / "engine/GDK-Proton-mcbe-gdk"
            destination.mkdir(parents=True)
            (destination / "old-engine").touch()

            with patch("updates._download_custom_engine", return_value=archive):
                install_custom_engine(asset, root)

            self.assertTrue((destination / "proton").is_file())
            self.assertFalse((destination / "old-engine").exists())
            self.assertEqual(
                read_engine_version(root), "owner/custom-engine@build-4"
            )
            metadata = json.loads(
                (destination / ".mcbe-gdk-engine.json").read_text()
            )
            self.assertEqual(metadata["url"], url)
            self.assertEqual(metadata["sha256"], "a" * 64)
            self.assertEqual(metadata["schema"], 2)
            self.assertIn("proton", metadata["installed_sha256"])
            self.assertTrue(_custom_engine_is_ready(root, asset))
            (destination / "proton").write_bytes(b"tampered")
            self.assertFalse(_custom_engine_is_ready(root, asset))

    def test_lukas_engine_profile_patches_gaming_services_gate(self):
        url = (
            "https://github.com/LukasPAH/GDK-Proton-Custom/releases/download/"
            "release-10-32-4/GDK-Proton10-32-Custom-4.tar.gz"
        )
        asset = CustomEngineAsset(
            repo="LukasPAH/GDK-Proton-Custom",
            tag="release-10-32-4",
            name="GDK-Proton10-32-Custom-4.tar.gz",
            url=url,
            sha256="4d19774c64451d4f1395dc4c5f4b6e8b5fdbc1ce6c05e29a855f5e0678b8800c",
        )
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            runtime = source / "files/lib/wine/x86_64-windows/xgameruntime.dll"
            runtime.parent.mkdir(parents=True)
            runtime.write_bytes(
                b"before"
                + bytes.fromhex("81 fe 4d 11 00 00 76 e4")
                + b"after"
            )
            profile = _apply_custom_engine_profile(source, asset)
            payload = runtime.read_bytes()

        self.assertEqual(profile.identifier, "lukas-remote-connect-v1")
        self.assertIn(bytes.fromhex("81 fe ff ff ff ff 76 e4"), payload)
        self.assertNotIn(bytes.fromhex("81 fe 4d 11 00 00 76 e4"), payload)

    def test_lukas_profile_is_selected_by_repository_name(self):
        asset = CustomEngineAsset(
            repo="lukaspah/gdk-proton-custom",
            tag="future-release",
            name="future-engine.tar.gz",
            url=(
                "https://github.com/LukasPAH/GDK-Proton-Custom/releases/"
                "download/future-release/future-engine.tar.gz"
            ),
            sha256="b" * 64,
        )
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            runtime = source / "files/lib/wine/x86_64-windows/xgameruntime.dll"
            runtime.parent.mkdir(parents=True)
            runtime.write_bytes(b"future runtime without the legacy gate")
            profile = _apply_custom_engine_profile(source, asset)

        self.assertEqual(profile.identifier, "lukas-remote-connect-v1")

    def test_project_profiles_are_selected_by_exact_asset(self):
        for expected in (
            LUKAS_EXPERIMENTAL_PROFILE,
            EXPERIMENTAL_ENGINE_PROFILE,
        ):
            with self.subTest(profile=expected.identifier):
                asset = CustomEngineAsset(
                    repo=expected.repository,
                    tag=expected.tag,
                    name=expected.asset,
                    url=(
                        f"https://github.com/{expected.repository}/releases/download/"
                        f"{expected.tag}/{expected.asset}"
                    ),
                    sha256=expected.sha256,
                )
                with tempfile.TemporaryDirectory() as temporary:
                    profile = _apply_custom_engine_profile(Path(temporary), asset)
                self.assertEqual(profile, expected)

                wrong_digest = CustomEngineAsset(
                    repo=asset.repo,
                    tag=asset.tag,
                    name=asset.name,
                    url=asset.url,
                    sha256="0" * 64,
                )
                with tempfile.TemporaryDirectory() as temporary:
                    profile = _apply_custom_engine_profile(
                        Path(temporary), wrong_digest
                    )
                self.assertIsNone(profile)

    def test_checksum_and_archive_paths_are_verified(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "source.tar.gz"
            archive.write_bytes(b"release")
            digest = hashlib.sha256(b"release").hexdigest()
            checksum = root / "source.tar.gz.sha256"
            checksum.write_text(f"{digest}  source.tar.gz\n")
            _verify_checksum(archive, checksum)
            checksum.write_text(f"{'0' * 64}  source.tar.gz\n")
            with self.assertRaises(UpdateError):
                _verify_checksum(archive, checksum)

            unsafe = root / "unsafe.tar.gz"
            with tarfile.open(unsafe, "w:gz") as bundle:
                info = tarfile.TarInfo("../outside")
                info.size = 1
                bundle.addfile(info, io.BytesIO(b"x"))
            with self.assertRaises(UpdateError):
                _validate_archive(
                    unsafe,
                    "mcbe-gdk-installer",
                    links=False,
                    max_unpacked=1024,
                )

            oversized = root / "oversized.tar.gz"
            with tarfile.open(oversized, "w:gz") as bundle:
                info = tarfile.TarInfo("mcbe-gdk-installer/payload")
                info.size = 2
                bundle.addfile(info, io.BytesIO(b"xx"))
            with self.assertRaisesRegex(UpdateError, "size limit"):
                _validate_archive(
                    oversized,
                    "mcbe-gdk-installer",
                    links=False,
                    max_unpacked=1,
                )

    def test_verified_download_reports_progress_and_verification(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            latest = release(INSTALLER_REPO, "v0.1.3")
            name = "mcbe-gdk-installer-v0.1.3.tar.gz"
            data = b"verified release"
            checksum = f"{hashlib.sha256(data).hexdigest()}  {name}\n".encode()
            events = []
            with patch(
                "updates.urlopen",
                side_effect=[Response(data), Response(checksum)],
            ):
                archive, digest = _download_verified(
                    latest,
                    name,
                    root,
                    1024,
                    "installer",
                    lambda *event: events.append(event),
                )
            self.assertEqual(archive, root / name)
            self.assertEqual(digest, hashlib.sha256(data).hexdigest())
            self.assertEqual(
                events,
                [
                    ("installer_download", 0, len(data)),
                    ("installer_download", len(data), len(data)),
                    ("installer_verify", None, None),
                ],
            )

    def test_cli_update_reports_component_progress(self):
        installer = release(INSTALLER_REPO, "v0.1.3")
        engine = release(ENGINE_REPO, "v0.1.4")
        output = io.StringIO()

        def install(updates, tool_root, root, progress):
            self.assertEqual(updates.installer, installer)
            progress("engine_download", 50 * 1024**2, 100 * 1024**2)
            progress("engine_verify", None, None)
            progress("engine_install", None, None)
            progress("engine_done", None, None)
            progress("installer_done", None, None)

        with patch(
            "updates.check_for_updates",
            return_value=AvailableUpdates(installer=installer, engine=engine),
        ), patch("updates.install_available_updates", side_effect=install):
            with redirect_stdout(output):
                result = _install_updates_cli(Path("/tool"), Path("/root"))

        self.assertEqual(result, 0)
        text = output.getvalue()
        self.assertIn("Downloading compatibility engine: 50%", text)
        self.assertIn("Verifying compatibility engine…", text)
        self.assertIn("MCBE GDK Installer updated…", text)
        self.assertIn("Updates installed.", text)

    def test_release_tags_are_validated_and_sorted(self):
        data = [
            {"tag_name": "v0.1.9"},
            {"tag_name": "v0.1.10"},
            {"tag_name": "not-a-version"},
            {"tag_name": "v0.2.0"},
        ]
        with patch(
            "updates.urlopen", return_value=Response(json.dumps(data).encode())
        ):
            tags = fetch_release_tags(ENGINE_REPO)
        self.assertEqual(tags, ["v0.2.0", "v0.1.10", "v0.1.9"])

        with patch("updates.urlopen", return_value=Response(b"[{")):
            with self.assertRaises(UpdateError):
                fetch_release_tags(ENGINE_REPO)

    def _engine_archive(self, root: Path, tag: str) -> Path:
        archive = root / "engine.tar.gz"
        files = {
            "engine-manifest.json": json.dumps({"version": tag}).encode(),
            "proton": b"#!/bin/sh\n",
            "files/bin/wine": b"wine",
            "files/bin/wineserver": b"wineserver",
        }
        with tarfile.open(archive, "w:gz") as bundle:
            for name, payload in files.items():
                info = tarfile.TarInfo(f"GDK-Proton-mcbe-gdk/{name}")
                info.size = len(payload)
                info.mode = 0o755
                bundle.addfile(info, io.BytesIO(payload))
        return archive

    def test_engine_install_bootstraps_missing_destination(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selected = release(ENGINE_REPO, "v0.1.8")
            archive = self._engine_archive(root, selected.tag)
            with patch(
                "updates._download_verified", return_value=(archive, "a" * 64)
            ):
                install_engine_update(selected, root)

            engine = root / "engine/GDK-Proton-mcbe-gdk"
            manifest = engine / "engine-manifest.json"
            self.assertEqual(json.loads(manifest.read_text())["version"], selected.tag)
            self.assertFalse((engine / ".mcbe-gdk-engine.json").exists())
            self.assertEqual(read_engine_version(root), "v0.1.8")

    def test_engine_install_records_stable_profile_from_v0_2_0(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selected = release(ENGINE_REPO, "v0.2.0")
            archive = self._engine_archive(root, selected.tag)
            with patch(
                "updates._download_verified", return_value=(archive, "B" * 64)
            ):
                install_engine_update(selected, root)

            engine = root / "engine/GDK-Proton-mcbe-gdk"
            metadata = json.loads((engine / ".mcbe-gdk-engine.json").read_text())
            self.assertEqual(metadata["repository"], ENGINE_REPO)
            self.assertEqual(metadata["tag"], "v0.2.0")
            self.assertEqual(metadata["sha256"], "B" * 64)
            self.assertEqual(metadata["profile"], STABLE_ENGINE_PROFILE.identifier)
            self.assertIs(installed_engine_profile(root), STABLE_ENGINE_PROFILE)
            self.assertEqual(read_engine_version(root), "v0.2.0")
            self.assertTrue(engine_is_ready(root, "v0.2.0"))

    def test_legacy_experimental_url_selection_tracks_latest(self):
        url = (
            f"https://github.com/{ENGINE_REPO}/releases/download/"
            "v0.2.0-experimental/GDK-Proton-mcbe-gdk-v0.2.0-experimental.tar.gz"
        )
        self.assertEqual(normalize_engine_selection(url), "latest")
        self.assertEqual(
            profile_for_asset(ENGINE_REPO, "v0.2.0", "x.tar.gz", "c" * 64),
            STABLE_ENGINE_PROFILE,
        )
        self.assertIsNone(
            profile_for_asset(ENGINE_REPO, "v0.1.9", "x.tar.gz", "c" * 64)
        )

    def test_switch_engine_installs_and_persists_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            engine = root / "engine/GDK-Proton-mcbe-gdk"
            engine.mkdir(parents=True)
            (engine / "engine-manifest.json").write_text(
                json.dumps({"version": "v0.1.7"})
            )
            selected = release(ENGINE_REPO, "v0.1.5")
            with patch("updates.fetch_release", return_value=selected) as fetch, patch(
                "updates.install_engine_update"
            ) as install, patch("updates._apply_game_profile") as apply_profile:
                result = switch_engine(root, "0.1.5")
            self.assertEqual(result.tag, "v0.1.5")
            self.assertEqual((root / "engine-release").read_text(), "v0.1.5\n")
            fetch.assert_called_once_with(ENGINE_REPO, "v0.1.5")
            install.assert_called_once_with(selected, root, None)
            apply_profile.assert_called_once_with(root)

            # Persisting the already-installed version never reinstalls.
            (engine / "engine-manifest.json").write_text(
                json.dumps({"version": "v0.1.5"})
            )
            proton = engine / "proton"
            proton.write_text("#!/bin/sh\n")
            proton.chmod(0o755)
            wineserver = engine / "files/bin/wineserver"
            wineserver.parent.mkdir(parents=True)
            wineserver.write_text("runtime\n")
            wineserver.chmod(0o755)
            with patch("updates.fetch_release", return_value=selected), patch(
                "updates.install_engine_update"
            ) as install:
                switch_engine(root, "v0.1.5")
            install.assert_not_called()

            # A matching manifest cannot hide a damaged engine installation.
            wineserver.unlink()
            with patch("updates.fetch_release", return_value=selected), patch(
                "updates.install_engine_update"
            ) as install:
                switch_engine(root, "v0.1.5")
            install.assert_called_once_with(selected, root, None)


if __name__ == "__main__":
    unittest.main()
