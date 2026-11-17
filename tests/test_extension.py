"""The "easy to extend" check: each registry takes a new entry by appending one line, nothing else changes.

PAGES (a page), COMMANDS (a subcommand) and SOURCES (a data source) are each extended from test code
that only appends to the registry, in a fresh subprocess with CLAUDE_CONFIG_DIR and HOME in a temp folder.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

ROOT = support.ROOT

PAGE_CODE = """
import curses
from claudemon.ui.pages import PAGES, Page
from claudemon.ui import manual

before = [p.id for p in PAGES]

def render(ctx, y, x, h, w):
    ctx.scr.put(y + 1, x + 2, "Zebra page body", ctx.T("fg"))

def side(ctx):
    return [1, 2, 3], "zline 1", "zline 2"

PAGES.append(Page("zebra", "Zebra", "x", render, side, manual_topic="Tasks"))

app = make_app(60, 120)
t = text(app)
print("count", len(app.pages) - len(before), [p.id for p in app.pages[:len(before)]] == before)
print("last", app.pages[-1].id, app.index_of("zebra") == len(before))
print("sidebar", "Zebra" in t, "zline 1" in t, "zline 2" in t)
key(app, "x")
t = text(app)
print("key", app.pages[app.page].id, "Zebra page body" in t, "page error" in t)
key(app, "1")
app.go("zeb")
app.draw()
print("go", app.pages[app.page].id, "Zebra page body" in text(app))
key(app, "m")
print("manual", app.modal, app.man_i == manual.topic_index("Tasks") != 0)
"""

COMMAND_CODE = """
import sys
from claudemon import cli, commands

seen = []
commands.COMMANDS["hello"] = lambda args: seen.append(args.command) or print("hello ran")
cli.main(["hello"])
print("seen", seen)
try:
    cli.main(["--help"])
except SystemExit:
    pass
"""

SOURCE_CODE = """
from claudemon.sources import SOURCES
from claudemon.sources import store as store_mod

order = []

class Probe:
    def refresh(self):
        order.append("probe")

class Broken:
    def refresh(self):
        order.append("broken")
        raise RuntimeError("boom")

SOURCES.append(("probe", Probe, "last"))
SOURCES.append(("broken", Broken, "last"))
st = store_mod.Store()
print("has", isinstance(st.probe, Probe), isinstance(st.broken, Broken))
real = st._recent_transcripts
st._recent_transcripts = lambda: (order.append("transcripts") or real())
st.indexed = True
st._last_scan = 0.0
st.refresh()
print("order", order)
"""


def run(code, home):
    env = dict(os.environ, CLAUDE_CONFIG_DIR=home, HOME=home, PYTHONPATH=str(ROOT / "src"), CLAUDEMON_DEMO="1",
               PYTHONDONTWRITEBYTECODE="1", COLUMNS="200")
    r = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise AssertionError("subprocess failed (%d):\n%s" % (r.returncode, r.stderr[-3000:]))
    return r.stdout


class Extension(unittest.TestCase):
    def test_a_page_is_one_module_and_one_pages_line(self):
        with tempfile.TemporaryDirectory() as home:
            out = support.ui(PAGE_CODE, home).splitlines()
        self.assertEqual(out, ["count 1 True", "last zebra True", "sidebar True True True",
                               "key zebra True False", "go zebra True", "manual manual True"], out)

    def test_a_subcommand_is_one_function_and_one_commands_entry(self):
        with tempfile.TemporaryDirectory() as home:
            out = run(COMMAND_CODE, home)
        self.assertIn("hello ran\nseen ['hello']\n", out)
        self.assertRegex(out, r"\{[^}]*hello[^}]*\}", "--help lists hello among the choices")

    def test_a_data_source_is_one_module_and_one_sources_entry(self):
        with tempfile.TemporaryDirectory() as home:
            out = run(SOURCE_CODE, home).splitlines()
        self.assertEqual(out[0], "has True True", out)
        order = eval(out[1].split(" ", 1)[1])
        self.assertEqual(order[-2:], ["probe", "broken"], order)
        self.assertIn("probe", order)
        if "transcripts" in order:
            self.assertLess(order.index("transcripts"), order.index("probe"))


if __name__ == "__main__":
    unittest.main()
