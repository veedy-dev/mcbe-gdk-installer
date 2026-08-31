"""Smoke test for the standalone runtime entry point."""

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class RuntimeSmokeTest(unittest.TestCase):
    _PROTON_VARS = (
        "PROTON_NO_NTSYNC",
        "PROTON_ADD_CONFIG",
        "STEAM_COMPAT_CONFIG",
        "VKD3D_DISABLE_EXTENSIONS",
    )

    def _run_launch_case(
        self,
        *,
        inherited=None,
        wineserver=b"/dev/ntsync",
        wineserver_access="readable",
        grep_status=None,
        device_state="character-readable",
        vkd3d_config=None,
        disable_dxr=False,
    ):
        repo = Path(__file__).resolve().parents[1]
        real_test = shutil.which("test")
        real_grep = shutil.which("grep")
        self.assertIsNotNone(real_test)
        self.assertIsNotNone(real_grep)

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            home = tmp / "home"
            xdg = tmp / "xdg"
            root = xdg / "mcbe-gdk-linux"
            profile = root / "profile"
            game = root / "game"
            engine = root / "engine" / "GDK-Proton-mcbe-gdk"
            wineserver_path = engine / "files" / "bin" / "wineserver"
            fake_bin = tmp / "bin"
            runtime_trace = tmp / "runtime-trace"
            umu_trace = tmp / "umu-trace"
            engine_trace = tmp / "engine-trace"
            notify_log = tmp / "notify.jsonl"
            child_env_path = tmp / "child-env.json"
            vkd3d_config_path = tmp / "vkd3d-config"

            for directory in (
                home,
                game,
                wineserver_path.parent,
                fake_bin,
                root / "lib",
                profile / "umu",
            ):
                directory.mkdir(parents=True, exist_ok=True)

            (root / "game-dir").write_text(f"{game}\n", encoding="utf-8")
            (game / "Minecraft.Windows.exe").touch()

            def write_executable(path, content):
                path.write_text(content, encoding="utf-8")
                path.chmod(0o755)

            write_executable(
                engine / "proton",
                """#!/usr/bin/env bash
printf 'invoked\n' > "$NTSYNC_TEST_ENGINE_TRACE"
exit 99
""",
            )
            if wineserver is not None:
                wineserver_path.write_bytes(wineserver)
                wineserver_path.chmod(0o755)

            (root / "lib" / "runtime.py").write_text(
                """import os
import subprocess
import sys
from pathlib import Path

trace = Path(os.environ["NTSYNC_TEST_RUNTIME_TRACE"])
with trace.open("a", encoding="utf-8") as stream:
    stream.write(sys.argv[1] + "\\n")
if sys.argv[1] == "gpu-arm":
    print("a" * 32)
elif sys.argv[1] == "supervise":
    raise SystemExit(subprocess.run(
        [sys.executable, sys.argv[2], *sys.argv[3:]],
        check=False,
    ).returncode)
""",
                encoding="utf-8",
            )
            write_executable(
                profile / "umu" / "umu-run",
                """#!/usr/bin/env python3
import json
import os
from pathlib import Path

names = (
    "PROTON_NO_NTSYNC",
    "PROTON_ADD_CONFIG",
    "STEAM_COMPAT_CONFIG",
    "VKD3D_DISABLE_EXTENSIONS",
)
payload = {}
for name in names:
    key = os.fsencode(name)
    payload[name] = None if key not in os.environb else os.environb[key].hex()
Path(os.environ["NTSYNC_TEST_CHILD_ENV"]).write_text(
    json.dumps(payload), encoding="utf-8"
)
Path(os.environ["NTSYNC_TEST_UMU_TRACE"]).write_text("invoked\\n", encoding="utf-8")
Path(os.environ["NTSYNC_TEST_VKD3D_CONFIG"]).write_text(
    os.environ.get("VKD3D_CONFIG", ""), encoding="utf-8"
)
""",
            )
            write_executable(
                fake_bin / "notify-send",
                """#!/usr/bin/env python3
import json
import os
import sys

with open(os.environ["NTSYNC_TEST_NOTIFY_LOG"], "a", encoding="utf-8") as stream:
    stream.write(json.dumps(sys.argv[1:]) + "\\n")
""",
            )
            write_executable(
                fake_bin / "test",
                """#!/usr/bin/env bash
if [[ "$#" -eq 2 && "$2" == "$NTSYNC_TEST_WINESERVER" ]]; then
  case "$1" in
    -f) [[ -f "$2" ]]; exit ;;
    -r) [[ "$NTSYNC_TEST_WINESERVER_ACCESS" == readable ]]; exit ;;
  esac
fi
if [[ "$#" -eq 2 && "$2" == /dev/ntsync ]]; then
  case "$1" in
    -e) [[ "$NTSYNC_TEST_DEVICE_STATE" != missing ]]; exit ;;
    -c) [[ "$NTSYNC_TEST_DEVICE_STATE" == character-* ]]; exit ;;
    -r) [[ "$NTSYNC_TEST_DEVICE_STATE" == character-readable ]]; exit ;;
  esac
fi
exec "$NTSYNC_TEST_REAL_TEST" "$@"
""",
            )
            write_executable(
                fake_bin / "grep",
                """#!/usr/bin/env bash
last="${!#}"
if [[ "$last" == "$NTSYNC_TEST_WINESERVER" &&
      -n "${NTSYNC_TEST_GREP_STATUS+x}" ]]; then
  exit "$NTSYNC_TEST_GREP_STATUS"
fi
exec "$NTSYNC_TEST_REAL_GREP" "$@"
""",
            )
            bash_env = tmp / "bash-env"
            bash_env.write_text("enable -n test\n", encoding="utf-8")

            fixtures = {
                profile / "msa" / "token.json": (b'{"refresh_token":"secret"}\n', 0o600),
                profile / "winegdk-preauth" / "device.json": (
                    b'{"xbl_gamertag":"player"}\n',
                    0o600,
                ),
                profile / "compatdata" / "pfx" / "system.reg": (
                    b"WINE REGISTRY Version 2\n# machine secret\n",
                    0o600,
                ),
                profile / "compatdata" / "pfx" / "user.reg": (
                    b"WINE REGISTRY Version 2\n# user state\n",
                    0o640,
                ),
            }
            for path, (content, mode) in fixtures.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                path.chmod(mode)

            def fixture_snapshot():
                return {
                    str(path.relative_to(profile)): {
                        "bytes": path.read_bytes(),
                        "mode": stat.S_IMODE(path.stat().st_mode),
                    }
                    for path in fixtures
                }

            before = fixture_snapshot()
            env = os.environ.copy()
            for name in self._PROTON_VARS:
                env.pop(name, None)
            for name, value in (inherited or {}).items():
                self.assertIn(name, self._PROTON_VARS)
                env[name] = value
            if vkd3d_config is None:
                env.pop("VKD3D_CONFIG", None)
            else:
                env["VKD3D_CONFIG"] = vkd3d_config
            if disable_dxr:
                env["MCBE_GDK_DISABLE_DXR"] = "1"
            else:
                env.pop("MCBE_GDK_DISABLE_DXR", None)
            env.update({
                "HOME": str(home),
                "XDG_DATA_HOME": str(xdg),
                "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                "BASH_ENV": str(bash_env),
                "NTSYNC_TEST_WINESERVER": str(wineserver_path),
                "NTSYNC_TEST_WINESERVER_ACCESS": wineserver_access,
                "NTSYNC_TEST_DEVICE_STATE": device_state,
                "NTSYNC_TEST_REAL_TEST": real_test,
                "NTSYNC_TEST_REAL_GREP": real_grep,
                "NTSYNC_TEST_RUNTIME_TRACE": str(runtime_trace),
                "NTSYNC_TEST_UMU_TRACE": str(umu_trace),
                "NTSYNC_TEST_ENGINE_TRACE": str(engine_trace),
                "NTSYNC_TEST_NOTIFY_LOG": str(notify_log),
                "NTSYNC_TEST_CHILD_ENV": str(child_env_path),
                "NTSYNC_TEST_VKD3D_CONFIG": str(vkd3d_config_path),
            })
            if grep_status is None:
                env.pop("NTSYNC_TEST_GREP_STATUS", None)
            else:
                env["NTSYNC_TEST_GREP_STATUS"] = str(grep_status)

            result = subprocess.run(
                ["bash", repo / "scripts" / "launch.sh"],
                cwd=repo,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            )
            log_path = profile / "logs" / "desktop-launch.log"
            notifications = []
            if notify_log.exists():
                notifications = [
                    json.loads(line)
                    for line in notify_log.read_text(encoding="utf-8").splitlines()
                ]
            child_env = {}
            if child_env_path.exists():
                child_env = json.loads(child_env_path.read_text(encoding="utf-8"))
            commands = []
            if runtime_trace.exists():
                commands = runtime_trace.read_text(encoding="utf-8").splitlines()

            return {
                "result": result,
                "log": log_path.read_text(encoding="utf-8") if log_path.exists() else "",
                "notifications": notifications,
                "child_env": child_env,
                "vkd3d_config": (
                    vkd3d_config_path.read_text(encoding="utf-8")
                    if vkd3d_config_path.is_file()
                    else None
                ),
                "runtime_trace": {
                    "commands": commands,
                    "umu": umu_trace.exists(),
                    "engine": engine_trace.exists(),
                },
                "fixture_state": {
                    "before": before,
                    "after": fixture_snapshot(),
                },
            }

    def test_login_code_opens_browser_and_uses_copyable_dialog(self):
        repo = Path(__file__).resolve().parents[1]
        code = """
from unittest.mock import patch

from auth import remote_login
from scripts import runtime

url = "https://www.microsoft.com/link"
device_code = "ABCD1234"

def which(name):
    return f"/usr/bin/{name}" if name in {"xdg-open", "kdialog"} else None

with patch.object(remote_login.webbrowser, "open", return_value=False) as browser, \\
     patch.object(remote_login.shutil, "which", side_effect=which), \\
     patch.object(remote_login.subprocess, "Popen") as popen:
    popen.return_value.poll.return_value = 0
    popen.return_value.returncode = 0
    assert runtime._show_code(url, device_code)

browser.assert_called_once_with(url)
assert popen.call_args_list[0].args[0] == ["/usr/bin/xdg-open", url]
dialog = popen.call_args_list[1].args[0]
assert "--inputbox" in dialog
prompt_index = dialog.index("--inputbox")
assert url in dialog[prompt_index + 1]
assert dialog[prompt_index + 2] == device_code
assert "Continue" in dialog

with patch.object(runtime, "login", side_effect=KeyboardInterrupt):
    assert runtime.main(["runtime.py", "login"]) == 130
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=repo,
            env={**os.environ, "MCBE_GDK_ROOT": str(repo)},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("Sign-in cancelled.", result.stderr)

    def test_lukas_profile_manages_game_identity_and_bootstrap(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "game"
            engine = root / "engine/GDK-Proton-mcbe-gdk"
            game.mkdir(parents=True)
            engine.mkdir(parents=True)
            (engine / ".mcbe-gdk-engine.json").write_text(
                json.dumps(
                    {
                        "schema": 2,
                        "profile": "lukas-remote-connect-v1",
                        "repository": "LukasPAH/GDK-Proton-Custom",
                        "tag": "test",
                        "asset": "engine.tar.gz",
                        "url": (
                            "https://github.com/LukasPAH/GDK-Proton-Custom/"
                            "releases/download/test/engine.tar.gz"
                        ),
                        "sha256": "a" * 64,
                        "capabilities": {
                            "authentication": "remote-connect-json",
                            "disable_app_runtime_bootstrap": True,
                            "login_request_parent_levels": 1,
                            "msa_app_id": "0000000048183522",
                            "title_id": "67b57dac",
                            "patch_gaming_services_gate": True,
                        },
                    }
                ),
                encoding="utf-8",
            )
            (game / "appxmanifest.xml").write_text(
                """<?xml version="1.0"?>
<Package>
  <Identity Name="Microsoft.MinecraftUWP" Publisher="CN=Microsoft"
            Version="1.26.4031.0"/>
  <Properties>
    <DisplayName>Minecraft for Windows</DisplayName>
    <PublisherDisplayName>Microsoft Studios</PublisherDisplayName>
    <Description>Minecraft</Description>
  </Properties>
  <Applications>
    <Application Id="Game" Executable="Minecraft.Windows.exe">
      <VisualElements DisplayName="Minecraft for Windows"
                      Square150x150Logo="Logo.png"
                      Square44x44Logo="SmallLogo.png"/>
    </Application>
  </Applications>
</Package>
""",
                encoding="utf-8",
            )
            bootstrap = game / "Microsoft.WindowsAppRuntime.Bootstrap.dll"
            bootstrap.write_bytes(b"bootstrap")
            code = """
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from auth.game_profile import apply_game_profile
from scripts import runtime
assert runtime.main(["runtime.py", "status"]) == 3
metadata_path = (
    runtime.ROOT
    / "engine/GDK-Proton-mcbe-gdk/.mcbe-gdk-engine.json"
)
metadata = json.loads(metadata_path.read_text())
metadata["capabilities"]["authentication"] = "tampered"
metadata_path.write_text(json.dumps(metadata))
assert runtime.installed_engine_profile(runtime.ROOT) is None
metadata["capabilities"]["authentication"] = "remote-connect-json"
metadata_path.write_text(json.dumps(metadata))

game = Path(runtime.os.environ["MCBE_GDK_ROOT"]) / "game"
profile = runtime.installed_engine_profile(runtime.ROOT)
assert profile and profile.identifier == "lukas-remote-connect-v1"
runtime.apply_installed_engine_profile(runtime.ROOT, game)
config = ET.parse(game / "MicrosoftGame.Config").getroot()
values = {child.tag: child.text for child in config}
assert values["MSAAppId"] == "0000000048183522"
assert values["TitleId"] == "67b57dac"
assert not (game / "Microsoft.WindowsAppRuntime.Bootstrap.dll").exists()

apply_game_profile(runtime.ROOT, game, None)
assert not (game / "MicrosoftGame.Config").exists()
assert (game / "Microsoft.WindowsAppRuntime.Bootstrap.dll").read_bytes() == b"bootstrap"
"""
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=repo,
                env={**os.environ, "MCBE_GDK_ROOT": str(root)},
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_profile_restores_original_config_and_refuses_user_changes(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "game"
            game.mkdir()
            (game / "appxmanifest.xml").write_text(
                """<Package>
<Identity Name="Microsoft.MinecraftUWP" Publisher="CN=Microsoft"
          Version="1.26.4031.0"/>
<Application Id="Game" Executable="Minecraft.Windows.exe"/>
</Package>
""",
                encoding="utf-8",
            )
            config = game / "MicrosoftGame.Config"
            original = (
                b'<?xml version="1.0"?>\n'
                b'<Game configVersion="1"><MSAAppId>old</MSAAppId>'
                b'<TitleId>AAAAAAAA</TitleId><Custom>keep</Custom></Game>\n'
            )
            config.write_bytes(original)
            (game / "Microsoft.WindowsAppRuntime.Bootstrap.dll").write_bytes(
                b"bootstrap"
            )
            code = """
from pathlib import Path
from auth.engine_profiles import LUKAS_ENGINE_PROFILE
from auth.game_profile import apply_game_profile
from auth.log import BolError
from scripts import runtime

game = Path(runtime.os.environ["MCBE_GDK_ROOT"]) / "game"
config = game / "MicrosoftGame.Config"
apply_game_profile(runtime.ROOT, game, LUKAS_ENGINE_PROFILE)
managed = config.read_bytes()
config.write_bytes(managed + b"changed")
try:
    apply_game_profile(runtime.ROOT, game, LUKAS_ENGINE_PROFILE)
except BolError as exc:
    assert "refusing to overwrite" in str(exc)
else:
    raise AssertionError("managed config changes were overwritten")
config.write_bytes(managed)
apply_game_profile(runtime.ROOT, game, None)
"""
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=repo,
                env={**os.environ, "MCBE_GDK_ROOT": str(root)},
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(config.read_bytes(), original)
            self.assertEqual(
                (game / "Microsoft.WindowsAppRuntime.Bootstrap.dll").read_bytes(),
                b"bootstrap",
            )

    def test_remote_login_request_is_validated_and_delivered(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request = root / "login.json"
            code = """
import json
from pathlib import Path
from scripts import runtime

request = Path(runtime.os.environ["MCBE_GDK_ROOT"]) / "login.json"
request.write_text(json.dumps({
    "verification_uri": "https://www.microsoft.com/link",
    "user_code": "ABCD-1234",
}))
seen = []
assert runtime.monitor_remote_login(
    request,
    lambda url, code: seen.append((url, code)),
    timeout=0.02,
    poll_interval=0.001,
)
assert seen == [("https://www.microsoft.com/link", "ABCD-1234")]

request.write_text('{"verification_uri":')
assert runtime.read_remote_login_request(request) is None
request.write_text(json.dumps({
    "verification_uri": "https://example.com/link",
    "user_code": "ABCD-1234",
}))
try:
    runtime.read_remote_login_request(request)
except runtime.BolError as exc:
    assert "untrusted URL" in str(exc)
else:
    raise AssertionError("untrusted login URL was accepted")
"""
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=repo,
                env={**os.environ, "MCBE_GDK_ROOT": str(root)},
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_python_supervisor_delivers_lukas_login_request(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            engine = root / "engine/GDK-Proton-mcbe-gdk"
            game = root / "game"
            engine.mkdir(parents=True)
            game.mkdir()
            (game / "Minecraft.Windows.exe").touch()
            (engine / ".mcbe-gdk-engine.json").write_text(
                json.dumps(
                    {
                        "schema": 2,
                        "profile": "lukas-remote-connect-v1",
                        "repository": "LukasPAH/GDK-Proton-Custom",
                        "tag": "test",
                        "asset": "engine.tar.gz",
                        "url": (
                            "https://github.com/LukasPAH/GDK-Proton-Custom/"
                            "releases/download/test/engine.tar.gz"
                        ),
                        "sha256": "a" * 64,
                        "capabilities": {
                            "authentication": "remote-connect-json",
                            "disable_app_runtime_bootstrap": True,
                            "login_request_parent_levels": 1,
                            "msa_app_id": "0000000048183522",
                            "title_id": "67b57dac",
                            "patch_gaming_services_gate": True,
                        },
                    }
                ),
                encoding="utf-8",
            )
            umu = root / "umu.py"
            umu.write_text(
                """import json
import time
from pathlib import Path
Path(__file__).with_name("login.json").write_text(json.dumps({
    "verification_uri": "https://www.microsoft.com/link",
    "user_code": "ABCD-1234",
}))
time.sleep(0.6)
raise SystemExit(7)
""",
                encoding="utf-8",
            )
            code = """
from pathlib import Path
from unittest.mock import patch
from scripts import runtime

root = Path(runtime.os.environ["MCBE_GDK_ROOT"])
with patch.object(runtime, "_show_code", return_value=True) as show:
    result = runtime.supervise(
        root / "umu.py",
        root / "game/Minecraft.Windows.exe",
        [],
    )
assert result == 7
show.assert_called_once()
assert show.call_args.args == (
    "https://www.microsoft.com/link",
    "ABCD-1234",
)
"""
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=repo,
                env={**os.environ, "MCBE_GDK_ROOT": str(root)},
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_remote_login_has_protected_no_gui_fallback(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            code = """
import builtins
import stat
from pathlib import Path
from unittest.mock import patch
from auth import remote_login

fallback = Path(__import__("os").environ["MCBE_GDK_ROOT"]) / "device-code.txt"
real_open = builtins.open
def open_without_tty(path, *args, **kwargs):
    if path == "/dev/tty":
        raise OSError("no terminal")
    return real_open(path, *args, **kwargs)

with patch.object(remote_login.webbrowser, "open", return_value=False), \\
     patch.object(remote_login.shutil, "which", return_value=None), \\
     patch.object(remote_login, "open", new=open_without_tty, create=True):
    assert remote_login.present_device_code(
        "https://www.microsoft.com/link",
        "ABCD-1234",
        emit=False,
        fallback_path=fallback,
    )
assert fallback.read_text().endswith("Enter code: ABCD-1234\\n")
assert stat.S_IMODE(fallback.stat().st_mode) == 0o600
"""
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=repo,
                env={**os.environ, "MCBE_GDK_ROOT": str(root)},
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("ABCD-1234", result.stdout)

    def test_gui_uses_the_installed_profile_for_auth(self):
        gui = (
            Path(__file__).resolve().parents[1] / "scripts" / "gui.py"
        ).read_text(encoding="utf-8")
        self.assertLess(
            gui.index('os.environ["BOL_HOME"] = str(ROOT / "profile")'),
            gui.index("from auth.auth import"),
        )

    def test_launcher_does_not_override_system_tls_policy(self):
        launch = (
            Path(__file__).resolve().parents[1] / "scripts" / "launch.sh"
        ).read_text(encoding="utf-8")
        self.assertNotIn("GNUTLS_SYSTEM_PRIORITY_FILE", launch)
        self.assertNotIn("gnutls-no-tls13", launch)

    def test_performance_advisories_cover_measured_bottlenecks(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            options = (
                root
                / "profile/compatdata/pfx/drive_c/users/steamuser/options.txt"
            )
            options.parent.mkdir(parents=True)
            options.write_text(
                "gfx_viewdistance:768\n"
                "gfx_vsync:1\n"
                "gfx_fullscreen:0\n",
                encoding="utf-8",
            )
            meminfo = root / "meminfo"
            meminfo.write_text("MemAvailable: 1048576 kB\n", encoding="utf-8")
            code = """
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from scripts import runtime

with patch.object(
    runtime.shutil, "disk_usage", return_value=SimpleNamespace(free=1024**3)
):
    warnings = runtime.performance_advisories(
        Path(runtime.os.environ["MCBE_GDK_ROOT"]),
        meminfo_path=Path(runtime.os.environ["TEST_MEMINFO"]),
        environ={"WAYLAND_DISPLAY": "wayland-0"},
    )
assert len(warnings) == 4, warnings
assert any("memory" in warning for warning in warnings)
assert any("disk space" in warning for warning in warnings)
assert any("48 chunks" in warning for warning in warnings)
assert any("VSync" in warning for warning in warnings)
"""
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=repo,
                env={
                    **os.environ,
                    "MCBE_GDK_ROOT": str(root),
                    "TEST_MEMINFO": str(meminfo),
                },
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_launcher_preserves_vkd3d_extension_policy(self):
        cases = (
            ("absent", {}, None),
            (
                "inherited",
                {"VKD3D_DISABLE_EXTENSIONS": "VK_EXT_foo;VK_KHR_present_wait"},
                "VK_EXT_foo;VK_KHR_present_wait",
            ),
        )
        for name, inherited, expected in cases:
            with self.subTest(name=name):
                case = self._run_launch_case(inherited=inherited)
                self.assertEqual(case["result"].returncode, 0, case["result"].stderr)
                actual = case["child_env"]["VKD3D_DISABLE_EXTENSIONS"]
                self.assertEqual(
                    None if actual is None else bytes.fromhex(actual).decode(),
                    expected,
                )

    def test_launcher_can_disable_dxr_without_duplicate_flags(self):
        cases = (
            (None, "nodxr,force_raw_va_cbv"),
            ("foo;nodxr", "foo;nodxr,force_raw_va_cbv"),
        )
        for inherited, expected in cases:
            with self.subTest(inherited=inherited):
                case = self._run_launch_case(
                    vkd3d_config=inherited,
                    disable_dxr=True,
                )
                self.assertEqual(case["result"].returncode, 0, case["result"].stderr)
                self.assertEqual(case["vkd3d_config"], expected)

    def test_launcher_ntsync_legacy_proton_flags_do_not_change_status(self):
        expected = "NTSync preflight: static prerequisites present."
        cases = (
            ("absent", {}),
            ("direct", {"PROTON_NO_NTSYNC": "1"}),
            ("add config", {"PROTON_ADD_CONFIG": "foo,nontsync"}),
            ("steam config", {"STEAM_COMPAT_CONFIG": "foo,nontsync"}),
            (
                "combined",
                {
                    "PROTON_NO_NTSYNC": "false",
                    "PROTON_ADD_CONFIG": "foo,nontsync",
                    "STEAM_COMPAT_CONFIG": r"cmdlineappend:--foo\,bar,nontsync",
                },
            ),
        )
        for name, inherited in cases:
            with self.subTest(name=name):
                case = self._run_launch_case(inherited=inherited)
                lines = [
                    line for line in case["log"].splitlines()
                    if line.startswith("NTSync preflight:")
                ]
                self.assertEqual(lines, [expected])
                self.assertEqual(
                    case["child_env"],
                    {
                        key: (
                            os.fsencode(inherited[key]).hex()
                            if key in inherited
                            else None
                        )
                        for key in self._PROTON_VARS
                    },
                )
                notifications = [
                    item for item in case["notifications"]
                    if len(item) >= 2
                    and item[-2] == "NTSync performance path unavailable"
                ]
                self.assertEqual(notifications, [])

    def test_launcher_ntsync_classifies_static_prerequisites(self):
        cases = (
            (
                "wineserver missing",
                {"wineserver": None},
                "NTSync preflight: engine wineserver is missing or unreadable; "
                "update or reinstall the engine.",
            ),
            (
                "wineserver unreadable",
                {"wineserver_access": "unreadable"},
                "NTSync preflight: engine wineserver is missing or unreadable; "
                "update or reinstall the engine.",
            ),
            (
                "marker absent",
                {"grep_status": 1},
                "NTSync preflight: engine wineserver lacks /dev/ntsync support; "
                "update or reinstall the engine.",
            ),
            (
                "marker error",
                {"grep_status": 2},
                "NTSync preflight: could not inspect engine wineserver; "
                "update or reinstall the engine.",
            ),
            (
                "device missing",
                {"device_state": "missing"},
                "NTSync preflight: /dev/ntsync is missing; use Linux 6.14+ or "
                "a distribution NTSync backport and load the module.",
            ),
            (
                "device regular",
                {"device_state": "regular-readable"},
                "NTSync preflight: /dev/ntsync is not a character device; "
                "repair the distribution device node.",
            ),
            (
                "device unreadable",
                {"device_state": "character-unreadable"},
                "NTSync preflight: /dev/ntsync is unreadable; repair the "
                "distribution device permissions.",
            ),
            (
                "static success",
                {"device_state": "character-readable"},
                "NTSync preflight: static prerequisites present.",
            ),
        )
        for name, options, expected in cases:
            with self.subTest(name=name):
                case = self._run_launch_case(**options)
                lines = [
                    line for line in case["log"].splitlines()
                    if line.startswith("NTSync preflight:")
                ]
                self.assertEqual(case["result"].returncode, 0, case["result"].stderr)
                self.assertEqual(lines, [expected])
                notifications = [
                    item for item in case["notifications"]
                    if len(item) >= 2
                    and item[-2] == "NTSync performance path unavailable"
                ]
                self.assertEqual(len(notifications), 0 if name == "static success" else 1)

    def test_launcher_ntsync_is_advisory_and_preserves_auth_state(self):
        cases = (
            ("success", {}, {}),
            (
                "legacy override ignored",
                {"inherited": {"PROTON_NO_NTSYNC": "private-direct-value"}},
                {"PROTON_NO_NTSYNC": "private-direct-value"},
            ),
            (
                "engine failure",
                {
                    "inherited": {
                        "PROTON_NO_NTSYNC": "0",
                        "PROTON_ADD_CONFIG": "private-add-value",
                        "STEAM_COMPAT_CONFIG": "private-steam-value",
                    },
                    "wineserver": None,
                },
                {
                    "PROTON_NO_NTSYNC": "0",
                    "PROTON_ADD_CONFIG": "private-add-value",
                    "STEAM_COMPAT_CONFIG": "private-steam-value",
                },
            ),
            (
                "device failure",
                {
                    "inherited": {
                        "PROTON_NO_NTSYNC": "",
                        "PROTON_ADD_CONFIG": "private-add-value",
                        "STEAM_COMPAT_CONFIG": "nontsync",
                    },
                    "device_state": "missing",
                },
                {
                    "PROTON_NO_NTSYNC": "",
                    "PROTON_ADD_CONFIG": "private-add-value",
                    "STEAM_COMPAT_CONFIG": "nontsync",
                },
            ),
        )
        for name, options, expected_env in cases:
            with self.subTest(name=name):
                case = self._run_launch_case(**options)
                result = case["result"]
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    case["runtime_trace"]["commands"],
                    ["performance", "prepare", "gpu-arm", "supervise", "gpu-disarm"],
                )
                self.assertTrue(case["runtime_trace"]["umu"])
                self.assertFalse(case["runtime_trace"]["engine"])
                self.assertEqual(
                    case["fixture_state"]["before"],
                    case["fixture_state"]["after"],
                )
                expected_child = {
                    key: (
                        None if key not in expected_env
                        else os.fsencode(expected_env[key]).hex()
                    )
                    for key in self._PROTON_VARS
                }
                self.assertEqual(case["child_env"], expected_child)
                rendered = (
                    case["log"]
                    + result.stdout
                    + result.stderr
                    + json.dumps(case["notifications"])
                )
                for value in expected_env.values():
                    if value.startswith("private-"):
                        self.assertNotIn(value, rendered)


    def test_fresh_profile_is_signed_out(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "lib").mkdir()
            (root / "lib" / "auth").symlink_to(
                repo / "auth",
                target_is_directory=True,
            )
            result = subprocess.run(
                [sys.executable, repo / "scripts" / "runtime.py", "status"],
                env={**os.environ, "MCBE_GDK_ROOT": str(root)},
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout.strip(), "Not signed in.")

    def test_prepare_does_not_require_sign_in(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = root / "game"
            game.mkdir()
            (game / "Minecraft.Windows.exe").touch()
            code = """
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from scripts import runtime

game = Path(__import__("os").environ["MCBE_GDK_ROOT"]) / "game"
prefix = game.parent / "profile" / "compatdata" / "pfx"
prefix.mkdir(parents=True)
patches = {
    "msa_signed_in": patch.object(runtime, "msa_signed_in", return_value=False),
    "ensure_login_deps": patch.object(runtime, "ensure_login_deps"),
    "login": patch.object(runtime, "login"),
    "install_gdk_xbox_dlls": patch.object(runtime, "install_gdk_xbox_dlls"),
    "fix_curl_ssl": patch.object(runtime, "fix_curl_ssl"),
    "ensure_umu": patch.object(runtime, "ensure_umu"),
    "boot_prefix": patch.object(runtime, "boot_prefix", return_value=True),
    "_install_cryptbase_in_prefix": patch.object(runtime, "_install_cryptbase_in_prefix"),
    "active_prefix": patch.object(runtime, "active_prefix", return_value=prefix),
    "install_gameinput": patch.object(runtime, "install_gameinput"),
    "wine_apply_winegdk_prereqs": patch.object(runtime, "wine_apply_winegdk_prereqs"),
    "update_prefix_registry": patch.object(runtime, "update_prefix_registry"),
    "msa_session_snapshot": patch.object(runtime, "msa_session_snapshot"),
    "bump_stack_reserve": patch.object(runtime, "bump_stack_reserve"),
}
with ExitStack() as stack:
    mocks = {name: stack.enter_context(item) for name, item in patches.items()}
    runtime.prepare(game)
    mocks["ensure_login_deps"].assert_not_called()
    mocks["login"].assert_not_called()
    mocks["msa_session_snapshot"].assert_not_called()
    mocks["update_prefix_registry"].assert_called_once()
    mocks["bump_stack_reserve"].assert_called_once()
"""
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=repo,
                env={**os.environ, "MCBE_GDK_ROOT": str(root)},
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_prepare_revokes_terminally_rejected_microsoft_session(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "game"
            game.mkdir()
            (game / "Minecraft.Windows.exe").touch()
            code = """
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from scripts import runtime

game = Path(runtime.os.environ["MCBE_GDK_ROOT"]) / "game"
prefix = game.parent / "profile/compatdata/pfx"
prefix.mkdir(parents=True)
patches = {
    "msa_signed_in": patch.object(runtime, "msa_signed_in", return_value=True),
    "ensure_login_deps": patch.object(runtime, "ensure_login_deps", return_value=False),
    "install_gdk_xbox_dlls": patch.object(runtime, "install_gdk_xbox_dlls"),
    "fix_curl_ssl": patch.object(runtime, "fix_curl_ssl"),
    "ensure_umu": patch.object(runtime, "ensure_umu"),
    "boot_prefix": patch.object(runtime, "boot_prefix", return_value=True),
    "active_prefix": patch.object(runtime, "active_prefix", return_value=prefix),
    "purge_registry_staging": patch.object(runtime, "purge_registry_staging"),
    "_install_cryptbase_in_prefix": patch.object(runtime, "_install_cryptbase_in_prefix"),
    "install_gameinput": patch.object(runtime, "install_gameinput"),
    "wine_apply_winegdk_prereqs": patch.object(runtime, "wine_apply_winegdk_prereqs"),
    "msa_session_snapshot": patch.object(
        runtime,
        "msa_session_snapshot",
        return_value=({"refresh_token": "revoked"}, "a" * 32),
    ),
    "msa_refresh": patch.object(
        runtime,
        "msa_refresh",
        side_effect=runtime.MsaRefreshRejected("invalid_grant"),
    ),
    "msa_logout": patch.object(runtime, "msa_logout"),
    "update_prefix_registry": patch.object(runtime, "update_prefix_registry"),
    "wine_reg_set_refresh_token": patch.object(runtime, "wine_reg_set_refresh_token"),
    "xbl_preauth": patch.object(runtime, "xbl_preauth"),
    "bump_stack_reserve": patch.object(runtime, "bump_stack_reserve"),
}
with ExitStack() as stack:
    mocks = {name: stack.enter_context(item) for name, item in patches.items()}
    try:
        runtime.prepare(game)
    except runtime.BolError as exc:
        assert "revoked" in str(exc)
    else:
        raise AssertionError("terminal refresh rejection was accepted")
    mocks["msa_logout"].assert_called_once_with()
    mocks["update_prefix_registry"].assert_called_once()
    mocks["wine_reg_set_refresh_token"].assert_not_called()
    mocks["xbl_preauth"].assert_not_called()
    mocks["bump_stack_reserve"].assert_not_called()
"""
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=repo,
                env={**os.environ, "MCBE_GDK_ROOT": str(root)},
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_source_runtime_keeps_source_modules_ahead_of_installed_lib(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            installed = root / "lib"
            installed.mkdir()
            (installed / "updates.py").write_text("SOURCE = 'installed'\n")
            code = """
import importlib.util
import runtime

print(importlib.util.find_spec("updates").origin)
"""
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=repo,
                env={
                    **os.environ,
                    "MCBE_GDK_ROOT": str(root),
                    "PYTHONPATH": os.pathsep.join(
                        (str(repo / "scripts"), str(repo))
                    ),
                },
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            Path(result.stdout.strip()).resolve(),
            (repo / "scripts/updates.py").resolve(),
        )


if __name__ == "__main__":
    unittest.main()
