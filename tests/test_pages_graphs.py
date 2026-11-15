"""The six graph pages (Token burn, Context, Prompt cache, Traffic, Models, Projects) through the App."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

PAGES = [("burn", "1", "Token burn"), ("context", "3", "Context"), ("cache", "4", "Prompt cache"),
         ("traffic", "5", "Traffic"), ("models", "6", "Models"), ("projects", "9", "Projects")]

# Renders every page at three sizes, in every graph style and in ASCII, and prints one JSON object.
RENDER = """
import json
from claudemon.ui import draw
PAGES = %r
out = {"bad": [], "keys": {}, "side": {}, "manual": {}}
for style in draw.STYLES:
    for rows, cols in ((16, 70), (36, 120), (60, 200)):
        app = make_app(rows, cols, graph=style)
        for pid, k, title in PAGES:
            key(app, k)
            t = text(app)
            if "page error" in t or title not in t:
                out["bad"].append([style, rows, cols, pid, "page error" if "page error" in t else "no title"])
app = make_app(60, 120)
for pid, k, title in PAGES:
    key(app, k)
    out["keys"][pid] = app.pages[app.page].id
    sc = app.side_cache[pid]
    out["side"][pid] = [isinstance(sc[0], list), isinstance(sc[1], str), isinstance(sc[2], str), len(sc) == 3,
                        bool(sc[1]) and sc[1] in text(app)]
    key(app, "m")
    out["manual"][pid] = [app.modal, app.man_i]
    key(app, "\\x1b")
    out["manual"][pid].append(app.modal)
    out["manual"][pid].append(tui.PAGES[app.page].manual_topic)
draw.set_ascii(True)
app = make_app(36, 120)
for pid, k, title in PAGES:
    key(app, k)
    t = text(app)
    if "page error" in t or not t.isascii():
        out["bad"].append(["ascii", pid, "page error" if "page error" in t else "non-ascii"])
print(json.dumps(out))
""" % (PAGES,)


class GraphPagesDemo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.demo = support.DemoHome()
        cls.home = cls.demo.start()
        cls.out = json.loads(support.ui(RENDER, cls.home, timeout=120))

    @classmethod
    def tearDownClass(cls):
        cls.demo.stop()

    def test_every_page_renders_with_its_title_at_all_sizes_styles_and_ascii(self):
        self.assertEqual(self.out["bad"], [])

    def test_each_page_key_opens_its_page(self):
        self.assertEqual(self.out["keys"], {pid: pid for pid, _, _ in PAGES})

    def test_side_returns_a_list_and_two_strings_and_the_sidebar_shows_line_one(self):
        for pid, flags in self.out["side"].items():
            with self.subTest(page=pid):
                self.assertEqual(flags, [True] * 5)

    def test_m_opens_the_manual_at_the_pages_topic_and_escape_closes_it(self):
        for pid, (modal, man_i, after, topic) in self.out["manual"].items():
            with self.subTest(page=pid):
                self.assertEqual(modal, "manual")
                self.assertIsNone(after)
                self.assertEqual(topic, dict((p, t) for p, _, t in PAGES)[pid])

    def test_page_specific_toggles(self):
        out = support.ui(
            "app = make_app(40, 140)\n"
            "res = {}\n"
            "key(app, '1')\n"
            "res['sessions_rows'] = 'web shop' in text(app)\n"
            "key(app, 'o')\n"
            "res['overall'] = app.overall\n"
            "res['overall_title'] = 'All sessions' in text(app)\n"
            "key(app, '6')\n"
            "key(app, 'e')\n"
            "res['by_effort'] = app.by_effort\n"
            "res['effort_rows'] = ' · ' in text(app) and 'Model · effort' in text(app)\n"
            "key(app, '5')\n"
            "labels = []\n"
            "for k in ('g', 'g', 'G'):\n"
            "    key(app, k)\n"
            "    labels.append(app.span_i)\n"
            "res['spans'] = labels\n"
            "key(app, '9')\n"
            "t = text(app)\n"
            "res['missing'] = [s.project for s in app.store.live_sessions() if s.project and s.project not in t]\n"
            "res['n'] = len(app.store.live_sessions())\n"
            "import json; print(json.dumps(res))\n", self.home)
        res = json.loads(out)
        self.assertTrue(res["sessions_rows"], "Token burn lists sessions before o")
        self.assertTrue(res["overall"])
        self.assertTrue(res["overall_title"], "Overall shows the All sessions box")
        self.assertTrue(res["by_effort"])
        self.assertTrue(res["effort_rows"], "Models shows model/effort rows")
        a, b, c = res["spans"]
        self.assertEqual(len({a, b}), 2, "g moves the span")
        self.assertEqual(c, a, "G moves it back")
        self.assertGreater(res["n"], 0)
        self.assertEqual(res["missing"], [], "Projects shows each demo project name")


class GraphPagesEmpty(unittest.TestCase):
    def test_every_page_renders_on_an_empty_home(self):
        with tempfile.TemporaryDirectory() as home:
            out = support.ui(
                "PAGES = %r\n"
                "app = make_app(36, 120)\n"
                "bad = []\n"
                "for pid, k, title in PAGES:\n"
                "    key(app, k)\n"
                "    if 'page error' in text(app) or app.pages[app.page].id != pid:\n"
                "        bad.append(pid)\n"
                "print(bad)\n" % (PAGES,), home, demo=False)
        self.assertEqual(out.strip(), "[]")


if __name__ == "__main__":
    unittest.main()
