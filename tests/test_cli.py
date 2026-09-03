import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class CliTest(unittest.TestCase):
    def test_installs_one_dispatcher_with_update_command(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            data = Path(temporary) / "data"
            bin_dir = home / ".local/bin"
            root = data / "mcbe-gdk-linux"
            bin_dir.mkdir(parents=True)
            for name in (
                "mcbe-gdk-linux-gui",
                "mcbe-gdk-linux-auth",
                "mcbe-gdk-linux-login",
                "mcbe-gdk-linux-logout",
                "mcbe-gdk-linux-config",
                "mcbe-gdk-linux-recover",
                "mcbe-gdk-linux-regolith-env",
                "mcbe-gdk-linux-rgl-env",
            ):
                (bin_dir / name).touch()
            env = {
                **os.environ,
                "HOME": str(home),
                "XDG_DATA_HOME": str(data),
            }
            result = subprocess.run(
                [repo / "scripts/install-launchers.sh", root, repo],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                [path.name for path in bin_dir.glob("mcbe-gdk-linux*")],
                ["mcbe-gdk-linux"],
            )

            command = bin_dir / "mcbe-gdk-linux"
            help_result = subprocess.run(
                [command, "help"], env=env, capture_output=True, text=True
            )
            self.assertIn("update", help_result.stdout)
            self.assertIn("engine [ENGINE]", help_result.stdout)
            self.assertIn("setup-env", help_result.stdout)

            (root / "lib/updates.py").write_text(
                "import sys\nprint('|'.join(sys.argv[1:]))\n",
                encoding="utf-8",
            )
            update_result = subprocess.run(
                [command, "update"],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(update_result.returncode, 0, update_result.stderr)
            self.assertEqual(
                update_result.stdout.strip(),
                f"install|{repo}|{root}",
            )

            engine_result = subprocess.run(
                [command, "engine", "0.1.5"],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(engine_result.returncode, 0, engine_result.stderr)
            self.assertEqual(
                engine_result.stdout.strip(),
                f"engine|{root}|0.1.5",
            )

            fake_tool = Path(temporary) / "tool"
            fake_tool.mkdir()
            fake_installer = fake_tool / "easy-install.sh"
            fake_installer.write_text('#!/bin/sh\nprintf "install|%s\\n" "$@"\n')
            fake_installer.chmod(0o755)
            (root / "source-dir").write_text(f"{fake_tool}\n")
            install_result = subprocess.run(
                [command, "install", "--no-gui", "/tmp/build.zip"],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(install_result.returncode, 0, install_result.stderr)
            self.assertEqual(install_result.stdout.strip(), "install|--no-gui|/tmp/build.zip")
            (root / "source-dir").write_text(f"{repo}\n")

            installer_entry = (
                data / "applications/io.github.veedydev.MCBEGDKInstaller.desktop"
            ).read_text(encoding="utf-8")
            game_entry = (
                data / "applications/io.github.veedydev.MinecraftBedrock.desktop"
            ).read_text(encoding="utf-8")
            self.assertIn(f"Exec={command} gui", installer_entry)
            self.assertIn(f"Exec={command} launch", game_entry)

            installer_path = (
                data / "applications/io.github.veedydev.MCBEGDKInstaller.desktop"
            )
            for policy in ("--no-gui", None):
                args = [repo / "scripts/install-launchers.sh", root, repo]
                if policy:
                    args.append(policy)
                subprocess.run(args, env=env, check=True, capture_output=True, text=True)
                self.assertFalse(installer_path.exists())
                self.assertTrue((root / ".no-gui-shortcut").exists())
            subprocess.run(
                [repo / "scripts/install-launchers.sh", root, repo, "--gui"],
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertTrue(installer_path.exists())
            self.assertFalse((root / ".no-gui-shortcut").exists())


if __name__ == "__main__":
    unittest.main()
