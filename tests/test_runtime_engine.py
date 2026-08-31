"""Focused tests for the v0.2.0-ex in-game login integration."""

import ast
import json
import stat
import tempfile
import unittest
from pathlib import Path

from auth.engine_profiles import (
    CUSTOM_ENGINE_METADATA,
    LUKAS_EXPERIMENTAL_PROFILE,
    installed_engine_profile,
)
from auth.remote_login import (
    clear_remote_login_request,
    remove_remote_login_request,
)


class ExperimentalRuntimeIntegrationTest(unittest.TestCase):
    def test_profile_requires_the_exact_mirrored_release(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata_path = (
                root / "engine/GDK-Proton-mcbe-gdk" / CUSTOM_ENGINE_METADATA
            )
            metadata_path.parent.mkdir(parents=True)
            metadata = {
                "schema": 2,
                "profile": LUKAS_EXPERIMENTAL_PROFILE.identifier,
                "repository": LUKAS_EXPERIMENTAL_PROFILE.repository,
                "tag": LUKAS_EXPERIMENTAL_PROFILE.tag,
                "asset": LUKAS_EXPERIMENTAL_PROFILE.asset,
                "url": (
                    "https://github.com/veedy-dev/mcbe-gdk-engine/releases/"
                    "download/v0.2.0-ex/GDK-Proton10-32-Custom-4.tar.gz"
                ),
                "sha256": LUKAS_EXPERIMENTAL_PROFILE.sha256,
                "capabilities": LUKAS_EXPERIMENTAL_PROFILE.capabilities(),
            }
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            self.assertEqual(
                installed_engine_profile(root), LUKAS_EXPERIMENTAL_PROFILE
            )

            metadata["tag"] = "v0.2.1-ex"
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
