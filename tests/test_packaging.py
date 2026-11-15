"""Every way of starting claudeMon reaches the one package in src/claudemon/, never a second copy.

The root claudemon.py is a wrapper: run, it starts the CLI; imported as `claudemon`, it replaces
itself in sys.modules with the real package. Two module objects for one file would split globals
such as draw.ascii_mode, so each route checks where `claudemon` came from. The wheel half builds and
installs the wheel when uv is available (CI's wheel job), and is skipped otherwise."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_PKG = ROOT / "src" / "claudemon"
WRAPPER = ROOT / "claudemon.py"

# Printed by every import route: where the package came from, and whether the wrapper stayed loaded.
REPORT = ("import sys, claudemon, claudemon.cli\n"
          "from claudemon.ui import draw\n"
          "print(claudemon.__file__)\n"
          "print(sys.modules['claudemon'] is claudemon and hasattr(claudemon, '__path__'))\n"
          "print(sorted(n for n, m in sys.modules.items()\n"
          "             if (getattr(m, '__file__', None) or '').endswith('claudemon.py')))\n"
          "print(sys.modules['claudemon.ui.draw'] is draw)\n")


def version():
    ns = {}
    exec((SRC_PKG / "__init__.py").read_text(), ns)
    return ns["__version__"]


class Routes(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.env = dict(os.environ, CLAUDE_CONFIG_DIR=str(self.tmp / "home"), HOME=str(self.tmp))
        self.env.pop("PYTHONPATH", None)

    def tearDown(self):
        self._tmp.cleanup()

    def run_py(self, args, cwd, **env):
        r = subprocess.run([sys.executable] + list(args), cwd=str(cwd), env=dict(self.env, **env),
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        return r.stdout

    def assert_one_copy(self, out, under):
        path, is_pkg, wrappers, same = out.splitlines()[-4:]
        self.assertTrue(Path(path).resolve().is_relative_to(under.resolve()), path)
        self.assertEqual((is_pkg, wrappers, same), ("True", "[]", "True"))

    def test_script(self):
        self.assertEqual(self.run_py([str(WRAPPER), "--version"], self.tmp).strip(), "claudemon " + version())

    def test_symlink_from_another_folder(self):
        link = self.tmp / "bin" / "claudemon"
        link.parent.mkdir()
        os.symlink(str(WRAPPER), str(link))
        self.assertEqual(self.run_py([str(link), "--version"], self.tmp).strip(), "claudemon " + version())
        out = self.run_py([str(link), "snapshot"], self.tmp)
        self.assertIn("No live Claude Code sessions", out)

    def test_script_route_loads_the_package_from_src(self):
        # what ./claudemon.py does, in one process so sys.modules can be inspected afterwards
        code = ("import runpy, sys\nsys.argv = [%r, '--version']\n"
                "try:\n    runpy.run_path(%r, run_name='__main__')\nexcept SystemExit:\n    pass\n" % (
                    str(WRAPPER), str(WRAPPER))) + REPORT
        self.assert_one_copy(self.run_py(["-c", code], self.tmp), SRC_PKG)

    def test_import_from_the_root(self):
        self.assert_one_copy(self.run_py(["-c", REPORT], ROOT), SRC_PKG)

    def test_import_cli_from_the_root(self):
        out = self.run_py(["-c", "import claudemon.cli, sys; print(claudemon.cli.__file__); "
                                 "print(type(sys.modules['claudemon']).__name__, sys.modules['claudemon'].__file__)"], ROOT)
        cli, mod = out.splitlines()
        self.assertEqual(Path(cli).resolve(), (SRC_PKG / "cli.py").resolve())
        self.assertEqual(Path(mod.split(" ", 1)[1]).resolve(), (SRC_PKG / "__init__.py").resolve())

    def test_module_from_the_root(self):
        self.assertEqual(self.run_py(["-m", "claudemon", "--version"], ROOT).strip(), "claudemon " + version())

    def test_module_from_elsewhere(self):
        out = self.run_py(["-m", "claudemon", "--version"], self.tmp, PYTHONPATH=str(ROOT / "src"))
        self.assertEqual(out.strip(), "claudemon " + version())

    def test_in_process_import(self):
        import claudemon
        self.assertEqual(Path(claudemon.__file__).name, "__init__.py")
        self.assertNotEqual(Path(claudemon.__file__).resolve(), WRAPPER.resolve())
        self.assertTrue(hasattr(claudemon, "__path__"))

    def test_window_relaunches_the_wrapper(self):
        code = ("import runpy, sys\n"
                "import claudemon.window as w\n"
                "w.open_window = lambda term, extra, size: ' '.join(w.self_command())\n"
                "sys.argv = ['claudemon', '--window']\n"
                "runpy.run_path(%r, run_name='__main__')\n" % str(WRAPPER))
        out = self.run_py(["-c", code], self.tmp, PYTHONPATH=str(ROOT / "src"))
        self.assertEqual(out.strip(), "%s %s" % (sys.executable, os.path.realpath(str(WRAPPER))))


class LegacyTapShim(unittest.TestCase):
    def test_the_shim_runs_the_real_tap(self):
        self.assertIn(b"tap for claudeMon", (ROOT / "tap.py").read_bytes()[:400])
        with tempfile.TemporaryDirectory() as home:
            r = subprocess.run([sys.executable, str(ROOT / "tap.py"), "statusline", "--", "cat; exit 4"],
                               input='{"session_id":"x"}', env=dict(os.environ, CLAUDE_CONFIG_DIR=home),
                               capture_output=True, text=True, timeout=20)
            self.assertEqual((r.stdout, r.returncode), ('{"session_id":"x"}', 4))
            self.assertTrue(Path(home, "claudemon", "status", "x.json").exists())


@unittest.skipUnless(shutil.which("uv"), "the wheel half needs uv to build the wheel (CI's wheel job has it)")
class Wheel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls._tmp.name)
        # Build from a copy, so setuptools' build/ and egg-info never land in the checkout.
        src = cls.tmp / "src-copy"
        src.mkdir()
        for name in ("pyproject.toml", "README.md", "LICENSE", "claudemon.py", "tap.py"):
            shutil.copy2(str(ROOT / name), str(src / name))
        shutil.copytree(str(ROOT / "src"), str(src / "src"), ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
        venv = cls.tmp / "venv"
        cls.py = venv / "bin" / "python"
        cls.bin = venv / "bin" / "claudemon"
        cls.uv("build", "--wheel", "-q", "-o", str(cls.tmp / "dist"), str(src))
        cls.wheel = next((cls.tmp / "dist").glob("*.whl"))
        # uv for the venv too: Debian's and Ubuntu's system Pythons have no ensurepip.
        cls.uv("venv", "-q", "--python", sys.executable, str(venv))
        cls.uv("pip", "install", "-q", "--python", str(cls.py), "--no-deps", str(cls.wheel))

    @classmethod
    def uv(cls, *args):
        env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
        r = subprocess.run(["uv"] + list(args), capture_output=True, text=True, timeout=300, env=env)
        if r.returncode:
            cls._tmp.cleanup()
            raise AssertionError("uv %s failed: %s" % (args[0], r.stderr[-2000:]))

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def env(self):
        e = dict(os.environ, CLAUDE_CONFIG_DIR=str(self.tmp / "home"), HOME=str(self.tmp))
        e.pop("PYTHONPATH", None)
        return e

    def test_wheel_holds_only_the_package(self):
        import zipfile
        names = zipfile.ZipFile(str(self.wheel)).namelist()
        top = {n.split("/", 1)[0] for n in names}
        self.assertEqual({t for t in top if not t.endswith(".dist-info")}, {"claudemon"})
        self.assertIn("claudemon/tap/tap.py", names)
        self.assertIn("claudemon/__main__.py", names)

    def test_entry_point_version(self):
        r = subprocess.run([str(self.bin), "--version"], cwd=str(self.tmp), env=self.env(),
                           capture_output=True, text=True, timeout=60)
        self.assertEqual((r.stdout.strip(), r.returncode), ("claudemon " + version(), 0), r.stderr)

    def test_installed_package_and_tap(self):
        code = ("import claudemon, hashlib\n"
                "from claudemon.tap import installer\n"
                "print(claudemon.__file__)\n"
                "print(installer.TAP_SRC.exists())\n"
                "print(hashlib.sha256(installer.TAP_SRC.read_bytes()).hexdigest())\n")
        r = subprocess.run([str(self.py), "-c", code], cwd=str(self.tmp), env=self.env(),
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        path, exists, digest = r.stdout.split()
        self.assertIn("site-packages", path)
        self.assertEqual(exists, "True")
        import hashlib
        self.assertEqual(digest, hashlib.sha256((SRC_PKG / "tap" / "tap.py").read_bytes()).hexdigest())

    def test_module_route(self):
        r = subprocess.run([str(self.py), "-m", "claudemon", "--version"], cwd=str(self.tmp), env=self.env(),
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.stdout.strip(), "claudemon " + version(), r.stderr)


if __name__ == "__main__":
    unittest.main()
