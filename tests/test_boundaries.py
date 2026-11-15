"""The layering rules (docs/reorg-plan.md, "Why this shape"), as tests.

- core/, sources/ and tap/ never import ui/ or curses: they are the data layers every page shares.
- tap/tap.py imports only the standard library: Claude Code runs it directly on the system Python.
- ui/__init__.py and ui/themes.py import nothing, so cli.py may use themes for --theme's choices.
- The headless routes (snapshot, loops, install, uninstall, --version, --window) never load curses.
"""

import ast
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "src" / "claudemon"


def imports(path):
    """Every module name a file imports, at any depth, as written (relative imports resolved)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    package = ".".join(("claudemon",) + path.relative_to(PKG).parent.parts)
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = package.split(".")[:len(package.split(".")) - node.level + 1]
                base = ".".join(parts + ([base] if base else []))
            out.add(base)
            out.update("%s.%s" % (base, a.name) for a in node.names)
    return out


def files(*subdirs):
    return sorted(p for d in subdirs for p in (PKG / d).rglob("*.py"))


class Layers(unittest.TestCase):
    def test_data_layers_never_import_the_interface_or_curses(self):
        found = files("core", "sources", "tap")
        self.assertGreaterEqual(len(found), 10)
        bad = ["%s: %s" % (p.relative_to(PKG), m) for p in found for m in sorted(imports(p))
               if m == "curses" or m.startswith("curses.") or m == "claudemon.ui" or m.startswith("claudemon.ui.")]
        self.assertEqual(bad, [])

    def test_the_tap_imports_only_the_standard_library(self):
        mods = imports(PKG / "tap" / "tap.py")
        self.assertTrue(mods, "the scan found no imports at all")
        self.assertEqual(sorted(m for m in mods if m.split(".")[0] in ("claudemon", "")), [])

    def test_themes_and_the_ui_package_import_nothing(self):
        for p in (PKG / "ui" / "__init__.py", PKG / "ui" / "themes.py"):
            self.assertEqual(imports(p), set(), p.name)


class HeadlessRoutes(unittest.TestCase):
    ROUTES = [["snapshot"], ["loops"], ["install"], ["uninstall"], ["--version"], ["--window"]]

    def test_headless_routes_never_load_curses(self):
        code = ("import sys\n"
                "import claudemon.window as w\n"
                "w.open_window = lambda *a, **k: 'stubbed'\n"     # --window must not open a terminal here
                "from claudemon.cli import main\n"
                "try:\n    main(sys.argv[1:])\nexcept SystemExit:\n    pass\n"
                "sys.stdout.flush()\n"
                "print('CURSES', 'curses' in sys.modules, '_curses' in sys.modules)\n")
        for route in self.ROUTES:
            with self.subTest(route=route), tempfile.TemporaryDirectory() as tmp:
                env = dict(os.environ, CLAUDE_CONFIG_DIR=os.path.join(tmp, "claude"), HOME=tmp,
                           PYTHONPATH=str(ROOT / "src"), CLAUDEMON_DEMO="1")
                r = subprocess.run([sys.executable, "-c", code] + route, cwd=tmp, env=env,
                                   capture_output=True, text=True, timeout=60)
                self.assertEqual(r.returncode, 0, r.stderr[-2000:])
                self.assertIn("CURSES False False", r.stdout, r.stdout[-500:])

    def test_the_check_would_see_curses(self):
        r = subprocess.run([sys.executable, "-c", "import sys\nfrom claudemon.ui import app\n"
                            "print('curses' in sys.modules)"], cwd=str(ROOT), env=dict(os.environ, PYTHONPATH=str(ROOT / "src")),
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.stdout.strip(), "True", r.stderr[-500:])


if __name__ == "__main__":
    unittest.main()
