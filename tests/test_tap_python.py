"""Which interpreter the tap bakes (runtime.tap_python) and how --window starts claudeMon again
(runtime.self_command). Nothing here touches the real ~/.claude."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import runtime  # noqa: E402


class TapPython(unittest.TestCase):
    def test_mac_with_command_line_tools_uses_system_python(self):
        with mock.patch.object(runtime.os.path, "exists", side_effect=lambda p: p in runtime._CLT_PYTHONS[:1]), \
                mock.patch.object(runtime, "_probe", return_value=True):
            self.assertEqual(runtime.tap_choice("darwin"), ("/usr/bin/python3", None))

    def test_mac_without_command_line_tools_falls_back_with_warning(self):
        with mock.patch.object(runtime.os.path, "exists", return_value=False), \
                mock.patch.object(runtime, "_probe", side_effect=AssertionError("must not probe the stub")), \
                mock.patch.object(runtime, "_in_venv", return_value=False), \
                mock.patch.object(runtime, "stable_python", return_value="/opt/x/bin/python3"):
            py, warn = runtime.tap_choice("darwin")
        self.assertEqual(py, "/opt/x/bin/python3")
        self.assertIn("claudemon install", warn)

    def test_probe_timeout_falls_back(self):
        err = subprocess.TimeoutExpired("python3", 5)
        with mock.patch.object(runtime.subprocess, "run", side_effect=err):
            self.assertFalse(runtime._probe("/usr/bin/python3"))
        with mock.patch.object(runtime.os.path, "exists", return_value=True), \
                mock.patch.object(runtime, "_probe", return_value=False), \
                mock.patch.object(runtime, "_in_venv", return_value=False), \
                mock.patch.object(runtime, "stable_python", return_value="/base/python3"):
            py, warn = runtime.tap_choice("darwin")
        self.assertEqual(py, "/base/python3")
        self.assertTrue(warn)

    def test_probe_nonzero_exit_and_missing_binary(self):
        class R:
            returncode = 1
        with mock.patch.object(runtime.subprocess, "run", return_value=R()):
            self.assertFalse(runtime._probe("/usr/bin/python3"))
        self.assertFalse(runtime._probe("/nonexistent/python3"))
        self.assertTrue(runtime._probe(sys.executable))

    def test_linux_uses_system_python_when_it_runs(self):
        with mock.patch.object(runtime, "_probe", return_value=True):
            self.assertEqual(runtime.tap_choice("linux"), ("/usr/bin/python3", None))
            self.assertEqual(runtime.tap_python("linux"), "/usr/bin/python3")

    def test_linux_without_system_python_falls_back(self):
        with mock.patch.object(runtime, "_probe", return_value=False), \
                mock.patch.object(runtime, "_in_venv", return_value=False), \
                mock.patch.object(runtime, "stable_python", return_value="/usr/local/bin/python3"):
            py, warn = runtime.tap_choice("linux")
        self.assertEqual(py, "/usr/local/bin/python3")
        self.assertTrue(warn)

    def test_never_bakes_a_venv(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d, "base", "bin")
            base.mkdir(parents=True)
            (base / "python3").write_text("")
            venv = Path(d, "venv")
            with mock.patch.object(runtime, "_probe", return_value=False), \
                    mock.patch.object(runtime.sys, "prefix", str(venv)), \
                    mock.patch.object(runtime.sys, "base_prefix", str(base.parent)), \
                    mock.patch.object(runtime.sys, "_base_executable", str(base / "python3"), create=True), \
                    mock.patch.object(runtime.sys, "executable", str(venv / "bin" / "python")):
                py, warn = runtime.tap_choice("linux")
        self.assertEqual(py, str(base / "python3"))
        self.assertNotIn(str(venv), py)
        self.assertTrue(warn)

    def test_venv_without_base_interpreter_still_warns(self):
        with mock.patch.object(runtime, "_probe", return_value=False), \
                mock.patch.object(runtime, "_in_venv", return_value=True), \
                mock.patch.object(runtime.sys, "_base_executable", "/gone/python", create=True), \
                mock.patch.object(runtime.sys, "base_prefix", "/gone"):
            py, warn = runtime.tap_choice("linux")
        self.assertTrue(warn)
        self.assertEqual(py, sys.executable or "python3")


class Installer(unittest.TestCase):
    """The installer bakes tap_python() for fresh installs and when the baked interpreter vanished."""

    def run_py(self, home, code):
        env = dict(os.environ, CLAUDE_CONFIG_DIR=home, HOME=home)
        return subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), env=env, capture_output=True, text=True)

    def test_fresh_install_bakes_tap_python_and_keeps_a_working_one(self):
        with tempfile.TemporaryDirectory() as home:
            code = ("import runtime; runtime.tap_python = lambda *a: '/baked/one'\n"
                    "import install; install.tap_python = runtime.tap_python\n"
                    "print(install.install())\n")
            r = self.run_py(home, code)
            self.assertEqual(r.returncode, 0, r.stderr)
            cmd = json.loads(Path(home, "settings.json").read_text())["statusLine"]["command"]
            self.assertTrue(cmd.startswith("/baked/one "), cmd)

    def test_vanished_interpreter_is_replaced_and_a_working_one_kept(self):
        with tempfile.TemporaryDirectory() as home:
            settings = Path(home, "settings.json")
            first = ("import install; install.tap_python = lambda *a: %r\nprint(install.install())\n")
            self.assertEqual(self.run_py(home, first % "/gone/python3").returncode, 0)
            self.assertTrue(json.loads(settings.read_text())["statusLine"]["command"].startswith("/gone/python3 "))
            fix = "import install; install.tap_python = lambda *a: %r\nprint(install.repair())\n"
            self.assertEqual(self.run_py(home, fix % sys.executable).returncode, 0)
            cmd = json.loads(settings.read_text())["statusLine"]["command"]
            self.assertTrue(cmd.startswith(sys.executable + " "), cmd)
            self.assertEqual(self.run_py(home, fix % "/other/python3").returncode, 0)
            self.assertTrue(json.loads(settings.read_text())["statusLine"]["command"].startswith(sys.executable + " "))


class SelfCommand(unittest.TestCase):
    def test_script_run_uses_interpreter_and_realpath(self):
        with tempfile.TemporaryDirectory() as d:
            link = Path(d, "claudemon")
            os.symlink(str(ROOT / "claudemon.py"), str(link))
            main = mock.Mock(spec=[])
            with mock.patch.dict(sys.modules, {"__main__": main}), mock.patch.object(sys, "argv", [str(link)]):
                self.assertEqual(runtime.self_command(), [sys.executable, os.path.realpath(str(ROOT / "claudemon.py"))])

    def test_script_run_ending_in_py_via_symlink_name(self):
        with tempfile.TemporaryDirectory() as d:
            link = Path(d, "cm.py")
            os.symlink(str(ROOT / "claudemon.py"), str(link))
            main = mock.Mock(spec=[])
            with mock.patch.dict(sys.modules, {"__main__": main}), mock.patch.object(sys, "argv", [str(link)]):
                self.assertEqual(runtime.self_command()[1], os.path.realpath(str(ROOT / "claudemon.py")))

    def test_module_run(self):
        main = mock.Mock()
        main.__spec__ = mock.Mock()
        main.__spec__.name = "claudemon.__main__"
        with mock.patch.dict(sys.modules, {"__main__": main}):
            self.assertEqual(runtime.self_command(), [sys.executable, "-m", "claudemon"])

    def test_installed_entry_point_keeps_the_invoked_path(self):
        with tempfile.TemporaryDirectory() as d:
            real = Path(d, "Cellar", "claudemon", "1", "bin", "claudemon")
            real.parent.mkdir(parents=True)
            real.write_text("#!/bin/sh\n")
            link = Path(d, "bin", "claudemon")
            link.parent.mkdir()
            os.symlink(str(real), str(link))
            main = mock.Mock(spec=[])
            with mock.patch.dict(sys.modules, {"__main__": main}), mock.patch.object(sys, "argv", [str(link)]):
                self.assertEqual(runtime.self_command(), [str(link)])

    def test_bare_command_name_is_resolved_on_path(self):
        with tempfile.TemporaryDirectory() as d:
            exe = Path(d, "claudemon")
            exe.write_text("#!/bin/sh\n")
            exe.chmod(0o755)
            main = mock.Mock(spec=[])
            with mock.patch.dict(sys.modules, {"__main__": main}), mock.patch.object(sys, "argv", ["claudemon"]), \
                    mock.patch.dict(os.environ, {"PATH": d}):
                self.assertEqual(runtime.self_command(), [os.path.abspath(str(exe))])


class WindowCommand(unittest.TestCase):
    def test_window_command_has_no_cd_and_reruns_the_launcher(self):
        import launch
        main = mock.Mock(spec=[])
        with mock.patch.dict(sys.modules, {"__main__": main}), \
                mock.patch.object(sys, "argv", [str(ROOT / "claudemon.py"), "--window"]):
            cmd = launch._command(["--mini"], {"CLAUDEMON_ASCII": "1"})
        self.assertNotIn("cd ", cmd)
        self.assertIn(str(ROOT / "claudemon.py"), cmd)
        self.assertTrue(cmd.endswith("--mini"), cmd)
        self.assertIn("exec env CLAUDEMON_ASCII=1 %s " % sys.executable, cmd)


if __name__ == "__main__":
    unittest.main()
