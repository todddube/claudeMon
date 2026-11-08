"""Smoke tests, standard library only:  python3 -m unittest discover -s tests -v"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PAGES = ["token", "tasks", "context", "prompt cache", "traffic", "models", "session", "weekly",
         "projects", "inspect:web shop", "settings", "manual", "manual:tap", "prompt"]


def run(*args, env=None, **kw):
    e = dict(os.environ, **(env or {}))
    return subprocess.run([sys.executable, *args], cwd=ROOT, env=e, capture_output=True, text=True, **kw)


class Ascii(unittest.TestCase):
    def test_every_glyph_in_the_sources_has_a_mapping(self):
        import draw
        missing = set()
        for f in list(ROOT.glob("*.py")):
            for ch in f.read_text():
                if ord(ch) > 127 and not 0x2800 <= ord(ch) <= 0x28FF and ord(ch) not in draw.ASCII_MAP:
                    missing.add(ch)
        self.assertFalse(missing, "no ASCII fallback for: " + "".join(sorted(missing)))

    def test_to_ascii(self):
        import draw
        self.assertEqual(draw.to_ascii("╭─┤x├╮ ▁█ ●▲○"), "+-+x++ .# *^o")
        self.assertTrue(draw.to_ascii("⣿⠁⠀").isascii())

    def test_detect(self):
        import draw
        keep = {k: os.environ.pop(k, None) for k in ("CLAUDEMON_ASCII", "LC_ALL", "LC_CTYPE", "LANG", "TERM")}
        try:
            os.environ["LANG"] = "en_US.UTF-8"
            self.assertFalse(draw.detect_ascii())
            os.environ["LC_ALL"] = "C"
            self.assertTrue(draw.detect_ascii())
            os.environ["CLAUDEMON_ASCII"] = "0"
            self.assertFalse(draw.detect_ascii())
        finally:
            for k in keep:
                os.environ.pop(k, None)
            os.environ.update({k: v for k, v in keep.items() if v is not None})


class Pages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.home = cls.tmp.name
        live = subprocess.Popen(["sleep", "300"])         # a live pid for the demo sessions
        cls.addClassCleanup(live.kill)
        r = run("tools/make_demo.py", cls.home, "--pid", str(live.pid))
        assert r.returncode == 0, r.stderr

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def grid(self, page, size="120x36", ascii_mode=False):
        env = {"CLAUDE_CONFIG_DIR": self.home, "CLAUDEMON_DEMO": "1", "CLAUDEMON_ASCII": "1" if ascii_mode else "0"}
        r = run("tools/grid.py", size, "claude", page, env=env)
        self.assertEqual(r.returncode, 0, "%s: %s" % (page, r.stderr[-400:]))
        return json.loads(r.stdout)

    def test_all_pages_render_unicode_and_ascii(self):
        for page in PAGES:
            for asc in (False, True):
                g = self.grid(page, ascii_mode=asc)
                text = "".join(c[0] for row in g["cells"] for c in row)
                self.assertTrue(text.strip(), page)
                if asc:
                    self.assertTrue(text.isascii(), "non-ASCII left on %s" % page)

    def test_small_terminal(self):
        for page in ("token", "session", "manual"):
            self.grid(page, size="60x20")


class Tap(unittest.TestCase):
    def cli(self, home, cmd):
        r = run("claudemon.py", cmd, env={"CLAUDE_CONFIG_DIR": home})
        return r.stdout.strip() + r.stderr.strip()

    def test_install_uninstall_restores_settings_exactly(self):
        with tempfile.TemporaryDirectory() as home:
            original = {"model": "opus", "statusLine": {"type": "command", "command": "echo hi"},
                        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "true"}]}]}}
            path = Path(home, "settings.json")
            path.write_text(json.dumps(original))
            self.assertIn("installed", self.cli(home, "install"))
            self.assertIn("already", self.cli(home, "install"))
            s = json.loads(path.read_text())
            self.assertIn("tap.py statusline -- 'echo hi'", s["statusLine"]["command"])
            self.assertIn("removed", self.cli(home, "uninstall"))
            self.assertEqual(json.loads(path.read_text()), original)

    def test_fresh_home_leaves_nothing_behind(self):
        with tempfile.TemporaryDirectory() as home:
            self.cli(home, "install")
            self.cli(home, "uninstall")
            self.assertEqual(json.loads(Path(home, "settings.json").read_text()), {})

    def test_bad_json_is_not_touched(self):
        with tempfile.TemporaryDirectory() as home:
            Path(home, "settings.json").write_text("{bad")
            self.assertIn("not valid JSON", self.cli(home, "install"))
            self.assertEqual(Path(home, "settings.json").read_text(), "{bad")

    def test_repair_replaces_a_vanished_interpreter(self):
        with tempfile.TemporaryDirectory() as home:
            self.cli(home, "install")
            p = Path(home, "settings.json")
            p.write_text(p.read_text().replace(sys.executable, "/gone/python3").replace("/usr/bin/python3", "/gone/python3"))
            r = run("-c", "import install;print(install.repair())", env={"CLAUDE_CONFIG_DIR": home})
            self.assertIn("re-pointed", r.stdout)
            self.assertNotIn("/gone/", p.read_text())

    def test_tap_passes_the_status_line_through(self):
        with tempfile.TemporaryDirectory() as home:
            r = subprocess.run([sys.executable, str(ROOT / "tap.py"), "statusline", "--", "cat"], input='{"session_id":"x"}',
                               env=dict(os.environ, CLAUDE_CONFIG_DIR=home), capture_output=True, text=True)
            self.assertEqual(r.stdout, '{"session_id":"x"}')


class Cli(unittest.TestCase):
    def test_snapshot_on_an_empty_home(self):
        with tempfile.TemporaryDirectory() as home:
            r = run("claudemon.py", "snapshot", env={"CLAUDE_CONFIG_DIR": home})
            self.assertEqual(r.returncode, 0)
            self.assertIn("No live Claude Code sessions", r.stdout)

    def test_needs_a_terminal(self):
        r = run("claudemon.py")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("needs a terminal", r.stderr)


if __name__ == "__main__":
    unittest.main()
