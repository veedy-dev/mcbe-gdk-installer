"""Regression tests for helper scripts executed from an extracted source tree."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class SourceHelperImportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(__file__).resolve().parents[1]

    def test_install_exports_source_root_before_updates_helper(self):
        install = (self.repo / "install.sh").read_text(encoding="utf-8")
        export = 'export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"'
        invocation = 'python3 "$SCRIPT_DIR/scripts/updates.py" latest-tag'
        self.assertIn(export, install)
        self.assertIn(invocation, install)
        self.assertLess(install.index(export), install.index(invocation))

    def test_updates_helper_imports_auth_from_an_extracted_source_tree(self):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(self.repo)
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                [sys.executable, str(self.repo / "scripts/updates.py")],
                cwd=temporary,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("Usage:", result.stderr)
        self.assertNotIn("ModuleNotFoundError", result.stderr)


if __name__ == "__main__":
    unittest.main()
