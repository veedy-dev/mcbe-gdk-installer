"""Behavioral tests for graphical and command-line bootstrap modes."""

import json
import os
import pty
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class BootstrapInstallModeTest(unittest.TestCase):
    def _write_executable(self, path: Path, body: str) -> None:
        path.write_text(body)
        path.chmod(0o755)

    def _environment(self, root: Path) -> dict[str, str]:
        fake_bin = root / "bin"
        fake_bin.mkdir()
        release = "v1.2.3"
        archive = f"mcbe-gdk-installer-{release}.tar.gz"
        release_url = (
            "https://github.com/veedy-dev/mcbe-gdk-installer/"
            f"releases/download/{release}"
        )
        release_data = json.dumps(
            {
                "tag_name": release,
                "assets": [
                    {
                        "name": archive,
                        "browser_download_url": f"{release_url}/{archive}",
                    },
                    {
                        "name": f"{archive}.sha256",
                        "browser_download_url": f"{release_url}/{archive}.sha256",
                    },
                ],
            }
        )

        self._write_executable(
            fake_bin / "python3",
            "#!/bin/sh\n"
            'if [ "$#" -eq 1 ] && [ "$1" = - ]; then\n'
            "  script=$(cat)\n"
            '  case "$script" in\n'
            '    *"import gi"*) [ -f "$HOME/gui-deps-installed" ]; exit ;;\n'
            "    *) exit 0 ;;\n"
            "  esac\n"
            "fi\n"
            f"exec {shlex.quote(sys.executable)} \"$@\"\n",
        )
        self._write_executable(
            fake_bin / "curl",
            f"#!{sys.executable}\n"
            "import pathlib, sys\n"
            "args = sys.argv[1:]\n"
            "output = pathlib.Path(args[args.index('-o') + 1])\n"
            f"release_data = {release_data!r}\n"
            "output.write_text(release_data if output.name == 'release.json' else '')\n",
        )
        self._write_executable(fake_bin / "sha256sum", "#!/bin/sh\nexit 0\n")
        self._write_executable(fake_bin / "7z", "#!/bin/sh\nexit 0\n")
        self._write_executable(
            fake_bin / "pacman",
            "#!/bin/sh\n"
            'printf \'%s\\n\' "$@" > "$HOME/package-args"\n'
            'touch "$HOME/gui-deps-installed"\n',
        )
        self._write_executable(
            fake_bin / "sudo",
            "#!/bin/sh\nexec \"$@\"\n",
        )
        self._write_executable(
            fake_bin / "tar",
            f"#!{sys.executable}\n"
            "import pathlib, sys\n"
            "args = sys.argv[1:]\n"
            "destination = pathlib.Path(args[args.index('-C') + 1])\n"
            "source = destination / 'mcbe-gdk-installer'\n"
            "scripts = source / 'scripts'\n"
            "scripts.mkdir(parents=True)\n"
            f"(source / 'VERSION').write_text({release!r} + '\\n')\n"
            "launcher = scripts / 'install-launchers.sh'\n"
            "launcher.write_text('#!/bin/sh\\nprintf \\\'%s\\\\n\\\' \\\"$#\\\" \\\"$@\\\" > \\\"$HOME/launcher-args\\\"\\n')\n"
            "launcher.chmod(0o755)\n"
            "gui = source / 'gui.sh'\n"
            "gui.write_text('#!/bin/sh\\nprintf launched > \\\"$HOME/gui-launched\\\"\\n')\n"
            "gui.chmod(0o755)\n",
        )

        return {
            **os.environ,
            "HOME": str(root),
            "XDG_DATA_HOME": str(root / "share"),
            "MCBE_GDK_SOURCE_DIR": str(root / "source"),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
        }

    def test_cli_choice_skips_gui_launch_and_shortcut(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = self._environment(root)
            master, slave = pty.openpty()
            try:
                os.write(master, b"2\n")
                result = subprocess.run(
                    [repo / "bootstrap.sh"],
                    cwd=repo,
                    env=env,
                    stdin=slave,
                    capture_output=True,
                    text=True,
                    check=True,
                )
            finally:
                os.close(master)
                os.close(slave)
            self.assertFalse((root / "package-args").exists())

            self.assertIn("2) Command line only (CLI)", result.stdout)
            self.assertIn("command-line tools installed", result.stdout)
            self.assertFalse((root / "gui-launched").exists())
            self.assertEqual(
                (root / "launcher-args").read_text().splitlines(),
                [
                    "3",
                    str(root / "share/mcbe-gdk-linux"),
                    str(root / "source"),
                    "--no-gui",
                ],
            )

    def test_gui_flag_installs_shortcut_and_opens_gui(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = self._environment(root)
            result = subprocess.run(
                [repo / "bootstrap.sh", "--gui"],
                cwd=repo,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )

            self.assertNotIn("Choose [1]", result.stdout)
            self.assertIn("Opening MCBE GDK Installer", result.stdout)
            self.assertEqual((root / "gui-launched").read_text(), "launched")
            package_args = (root / "package-args").read_text().splitlines()
            self.assertIn("gtk4", package_args)
            self.assertIn("libadwaita", package_args)
            self.assertIn("python-gobject", package_args)
            self.assertIn("unzip", package_args)
            self.assertIn("7zip", package_args)
            self.assertEqual(
                (root / "launcher-args").read_text().splitlines(),
                [
                    "3",
                    str(root / "share/mcbe-gdk-linux"),
                    str(root / "source"),
                    "--gui",
                ],
            )

    def test_no_controlling_tty_defaults_to_gui_without_prompting(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = self._environment(root)
            result = subprocess.run(
                [repo / "bootstrap.sh"],
                cwd=repo,
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                start_new_session=True,
                check=True,
            )

            self.assertNotIn("Choose [1]", result.stdout)
            self.assertIn("Opening MCBE GDK Installer", result.stdout)
            self.assertEqual(
                (root / "launcher-args").read_text().splitlines()[-1],
                "--gui",
            )

    def test_conflicting_mode_flags_are_rejected(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = self._environment(root)
            result = subprocess.run(
                [repo / "bootstrap.sh", "--gui", "--cli"],
                cwd=repo,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("Choose only one install mode", result.stderr)
            self.assertFalse((root / "gui-launched").exists())


if __name__ == "__main__":
    unittest.main()
