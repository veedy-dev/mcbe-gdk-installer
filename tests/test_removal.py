import fcntl
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from scripts.removal import (
    LOCK_NAME,
    minecraft_launcher_pid,
    remove_minecraft,
    runtime_lock,
    stop_minecraft,
)


class RemovalTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "mcbe"
        self.profile = self.root / "profile"
        (self.root / "game").mkdir(parents=True)
        (self.root / "game" / "Minecraft.Windows.exe").touch()
        (self.root / "engine").mkdir()
        (self.root / "lib").mkdir()
        (self.root / "application").touch()
        (self.root / "game-dir").write_text(str(self.root / "game"))
        (self.root / "game-path").write_text(str(self.root / "game"))

    def tearDown(self):
        self.temp.cleanup()

    def seed_profile(self):
        for path in (
            "worlds/world/level.dat",
            "cache/index",
            "logs/latest.log",
            "compatdata/pfx/token",
            ".tokens/session",
        ):
            file = self.profile / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("user data")
        (self.profile / "settings.json").write_text("{}")

    def test_normal_uninstall_preserves_profile(self):
        self.seed_profile()
        (self.profile / "content").symlink_to(self.root / "game")

        remove_minecraft(self.root)

        self.assertFalse((self.root / "game").exists())
        self.assertFalse((self.root / "game-dir").exists())
        self.assertFalse((self.root / "game-path").exists())
        self.assertFalse((self.profile / "content").exists())
        self.assertTrue((self.profile / "worlds/world/level.dat").is_file())
        self.assertTrue((self.profile / ".tokens/session").is_file())
        self.assertTrue((self.root / "engine").is_dir())
        self.assertTrue((self.root / "lib").is_dir())
        self.assertTrue((self.root / "application").is_file())

    def test_full_reset_removes_profile_without_following_symlinks(self):
        self.seed_profile()
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (outside / "keep").write_text("outside")
        (self.profile / "external-dir").symlink_to(outside, target_is_directory=True)
        (self.profile / "external-file").symlink_to(outside / "keep")
        (self.profile / "content").symlink_to(self.root / "game")
        (self.profile / LOCK_NAME).touch()

        remove_minecraft(self.root, remove_user_data=True)

        self.assertEqual(
            {entry.name for entry in self.profile.iterdir()},
            {LOCK_NAME},
        )
        self.assertEqual((outside / "keep").read_text(), "outside")
        self.assertTrue((self.root / "engine").is_dir())
        self.assertTrue((self.root / "lib").is_dir())
        self.assertTrue((self.root / "application").is_file())

    def test_cli_uninstall_requires_confirmation_and_honors_flags(self):
        self.seed_profile()
        script = Path(__file__).resolve().parents[1] / "scripts/removal.py"

        def run(*args):
            return subprocess.run(
                ["python3", script, self.root, *args],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
            )

        self.assertEqual(run("uninstall").returncode, 2)
        self.assertTrue((self.root / "game").exists())
        self.assertEqual(run("uninstall", "--bogus", "--yes").returncode, 2)

        result = run("uninstall", "--yes")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / "game").exists())
        self.assertTrue((self.profile / "worlds/world/level.dat").is_file())

        result = run("uninstall", "--remove-user-data", "--yes")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.profile / "worlds").exists())

        result = run("stop")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("not running", result.stdout)

    def test_runtime_lock_rejects_concurrent_uninstall(self):
        lock_path = self.profile / LOCK_NAME
        lock_path.parent.mkdir(parents=True)
        with lock_path.open("a+") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(RuntimeError, "setup action is running"):
                with runtime_lock(self.root):
                    self.fail("lock unexpectedly acquired")

    def _assert_launcher_detected_and_stopped(self, process):
        try:
            for _ in range(50):
                if minecraft_launcher_pid(self.root) == process.pid:
                    break
                time.sleep(0.02)
            self.assertEqual(minecraft_launcher_pid(self.root), process.pid)
            self.assertTrue(stop_minecraft(self.root))
            process.wait(timeout=2)
            self.assertIsNone(minecraft_launcher_pid(self.root))
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()

    def test_dispatcher_launched_script_is_detected_and_stopped(self):
        installed_launcher = self.root / "lib" / "launch.sh"
        installed_launcher.write_text(
            """#!/bin/sh
exec 9>"$1"
flock -n 9 || exit 1
printf '%s\n' "$$" > "$2"
sleep 30
"""
        )
        installed_launcher.chmod(0o755)
        root_alias = Path(self.temp.name) / "installed-root"
        root_alias.symlink_to(self.root, target_is_directory=True)
        dispatcher = Path(self.temp.name) / "mcbe-gdk-linux"
        dispatcher.write_text(
            """#!/bin/sh
root="$1"
exec "$root/lib/launch.sh" \
  "$root/profile/.desktop-launch.lock" \
  "$root/profile/.desktop-launch.pid"
"""
        )
        dispatcher.chmod(0o755)
        self.profile.mkdir(parents=True, exist_ok=True)

        process = subprocess.Popen(
            [dispatcher, root_alias],
            start_new_session=True,
        )
        self._assert_launcher_detected_and_stopped(process)

    def test_legacy_named_launcher_is_detected_and_stopped(self):
        launcher = Path(self.temp.name) / "mcbe-gdk-linux"
        launcher.write_text(
            """#!/bin/sh
exec 9>"$1"
flock -n 9 || exit 1
printf '%s\n' "$$" > "$2"
sleep 30
"""
        )
        launcher.chmod(0o755)
        lock = self.profile / LOCK_NAME
        pid_file = self.profile / ".desktop-launch.pid"
        lock.parent.mkdir(parents=True, exist_ok=True)

        process = subprocess.Popen(
            [launcher, lock, pid_file],
            start_new_session=True,
        )
        self._assert_launcher_detected_and_stopped(process)


if __name__ == "__main__":
    unittest.main()
