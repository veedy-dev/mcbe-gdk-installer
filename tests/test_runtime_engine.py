"""Focused tests for experimental in-game login integration."""

import ast
import json
import stat
import tempfile
import unittest
from pathlib import Path

from auth.engine_profiles import (
    CUSTOM_ENGINE_METADATA,
    EXPERIMENTAL_ENGINE_PROFILE,
    LUKAS_EXPERIMENTAL_PROFILE,
    installed_engine_profile,
)
from auth.remote_login import (
    clear_remote_login_request,
    remove_remote_login_request,
)


class ExperimentalRuntimeIntegrationTest(unittest.TestCase):
    def test_profiles_require_their_exact_releases(self):
        profiles = (
            (
                EXPERIMENTAL_ENGINE_PROFILE,
                "https://github.com/veedy-dev/mcbe-gdk-engine/releases/"
                "download/v0.2.0-experimental/"
                "GDK-Proton-mcbe-gdk-v0.2.0-experimental.tar.gz",
            ),
            (
                LUKAS_EXPERIMENTAL_PROFILE,
                "https://github.com/veedy-dev/mcbe-gdk-engine/releases/"
                "download/v0.2.0-ex/GDK-Proton10-32-Custom-4.tar.gz",
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata_path = (
                root / "engine/GDK-Proton-mcbe-gdk" / CUSTOM_ENGINE_METADATA
            )
            metadata_path.parent.mkdir(parents=True)
            for profile, url in profiles:
                with self.subTest(profile=profile.identifier):
                    metadata = {
                        "schema": 2,
                        "profile": profile.identifier,
                        "repository": profile.repository,
                        "tag": profile.tag,
                        "asset": profile.asset,
                        "url": url,
                        "sha256": profile.sha256,
                        "capabilities": profile.capabilities(),
                    }
                    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
                    self.assertEqual(installed_engine_profile(root), profile)

                    metadata["sha256"] = "0" * 64
                    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
                    self.assertIsNone(installed_engine_profile(root))

    def test_login_request_is_precreated_private_and_removed_afterwards(self):
        with tempfile.TemporaryDirectory() as temporary:
            request = Path(temporary) / "login.json"
            clear_remote_login_request(request)
            self.assertTrue(request.is_file())
            self.assertEqual(stat.S_IMODE(request.stat().st_mode), 0o600)

            request.write_text("temporary device code", encoding="utf-8")
            clear_remote_login_request(request)
            self.assertEqual(request.read_bytes(), b"")
            self.assertEqual(stat.S_IMODE(request.stat().st_mode), 0o600)

            remove_remote_login_request(request)
            self.assertFalse(request.exists())

    def test_installed_runtime_uses_profile_wrapper(self):
        repo = Path(__file__).resolve().parents[1]
        wrapper = (repo / "scripts/runtime_engine.py").read_text(encoding="utf-8")
        ast.parse(wrapper)
        self.assertIn("IgnoreVersionMismatch", wrapper)
        self.assertIn("remove_remote_login_request", wrapper)
        self.assertIn("reviewed_custom_engine_metadata", wrapper)
        self.assertIn("login = base.login", wrapper)
        self.assertIn("logout = base.logout", wrapper)

        installer = (repo / "scripts/install-launchers.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'install -m755 "$SOURCE/scripts/runtime.py" "$ROOT/lib/runtime_base.py"',
            installer,
        )
        self.assertIn(
            'install -m755 "$SOURCE/scripts/runtime_engine.py" "$ROOT/lib/runtime.py"',
            installer,
        )


if __name__ == "__main__":
    unittest.main()
