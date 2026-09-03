"""Static checks for the engine-aware GTK entrypoint."""

import ast
import unittest
from pathlib import Path


class GuiEngineIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(__file__).resolve().parents[1]
        self.entrypoint = self.repo / "scripts/gui_engine.py"
        self.source = self.entrypoint.read_text(encoding="utf-8")

    def test_entrypoint_is_valid_python_without_release_presets(self):
        ast.parse(self.source, filename=str(self.entrypoint))
        self.assertNotIn("experimental", self.source.lower())
        self.assertNotIn("Lukas in-game login", self.source)
        self.assertIn("Use custom GitHub engine?", self.source)

    def test_source_and_installed_launchers_use_engine_aware_gui(self):
        source_launcher = (self.repo / "gui.sh").read_text(encoding="utf-8")
        installed_launcher = (self.repo / "scripts/gui-launch.sh").read_text(
            encoding="utf-8"
        )
        installer = (self.repo / "scripts/install-launchers.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("scripts/gui_engine.py", source_launcher)
        self.assertIn("$ROOT/lib/gui_engine.py", installed_launcher)
        self.assertIn(
            'install -m755 "$SOURCE/scripts/gui_engine.py" "$ROOT/lib/gui_engine.py"',
            installer,
        )

    def test_custom_profile_replaces_native_account_controls_with_guidance(self):
        self.assertIn('set_title("Sign in inside Minecraft")', self.source)
        self.assertIn("device-code prompt", self.source)
        self.assertIn("self.login_button.set_visible(False)", self.source)
        self.assertIn("self.logout_button.set_visible(False)", self.source)


if __name__ == "__main__":
    unittest.main()
