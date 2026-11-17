"""The modals: help, manual, first-launch tap prompt and too-small guard, plus the manual's markup."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from claudemon.ui import manual  # noqa: E402
from claudemon.ui.pages import PAGES  # noqa: E402


class ManualData(unittest.TestCase):
    def test_every_topic_has_an_id_a_title_and_a_body(self):
        for t in manual.TOPICS:
            with self.subTest(topic=t.get("id")):
                self.assertTrue(t.get("id") and t.get("title") and t.get("body"))

    def test_topic_ids_are_unique(self):
        ids = [t["id"] for t in manual.TOPICS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_topic_index_falls_back_to_welcome(self):
        self.assertEqual(manual.topic_index("nope"), 0)
        self.assertEqual(manual.TOPICS[manual.topic_index("Session limit")]["title"], "7 Session limit")


class Modals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.demo = support.DemoHome()
        cls.home = cls.demo.start()

    @classmethod
    def tearDownClass(cls):
        cls.demo.stop()

    def test_help_opens_with_question_mark_and_any_key_closes_it(self):
        out = support.ui(
            "app = make_app(40, 120)\n"
            "key(app, '?')\n"
            "print(app.modal, 'claudeMon — a task manager for Claude Code' in text(app))\n"
            "key(app, 'x')\n"
            "print(app.modal, 'claudeMon — a task manager for Claude Code' in text(app))\n", self.home)
        self.assertEqual(out.split("\n")[:2], ["help True", "None False"], out)

    def test_m_opens_each_pages_manual_topic(self):
        out = support.ui(
            "from claudemon.ui import manual\n"
            "app = make_app(40, 120)\n"
            "for i, p in enumerate(app.pages):\n"
            "    app.go_page(p.id); app.draw()\n"
            "    key(app, 'm')\n"
            "    print(p.id, app.modal, manual.TOPICS[app.man_i]['id'] == p.manual_topic)\n"
            "    key(app, 'm')\n", self.home)
        rows = [ln.split() for ln in out.strip().split("\n")]
        self.assertEqual(len(rows), len(PAGES), out)
        for r in rows:
            self.assertEqual(r[-2:], ["manual", "True"], r)

    def test_go_manual_picks_topics_by_prefix(self):
        out = support.ui(
            "from claudemon.ui import manual\n"
            "for arg in ('manual:s', 'manual:t', 'manual', 'manual:zzz'):\n"
            "    app = make_app(40, 120)\n"
            "    app.go(arg)\n"
            "    print(arg, app.modal, manual.TOPICS[app.man_i]['id'])\n", self.home)
        self.assertEqual(out.strip().split("\n"), [
            "manual:s manual Session limit", "manual:t manual tap", "manual manual welcome", "manual:zzz manual welcome"], out)

    def test_topic_keys_step_forward_and_back_with_wrap_and_reset_scroll(self):
        out = support.ui(
            "import curses\n"
            "from claudemon.ui import manual\n"
            "n = len(manual.TOPICS)\n"
            "app = make_app(40, 120)\n"
            "app.go('manual')\n"
            "for k in ('j', curses.KEY_DOWN, 'l', curses.KEY_RIGHT, '\\t'):\n"
            "    app.man_i, app.man_scroll = 3, 5\n"
            "    key(app, k)\n"
            "    print('next', app.man_i, app.man_scroll)\n"
            "for k in ('k', curses.KEY_UP, 'h', curses.KEY_LEFT, curses.KEY_BTAB):\n"
            "    app.man_i, app.man_scroll = 3, 5\n"
            "    key(app, k)\n"
            "    print('prev', app.man_i, app.man_scroll)\n"
            "app.man_i = n - 1; key(app, 'j'); print('wrap', app.man_i)\n"
            "app.man_i = 0; key(app, 'k'); print('wrap', app.man_i == n - 1)\n", self.home)
        lines = out.strip().split("\n")
        self.assertEqual(lines[:5], ["next 4 0"] * 5, out)
        self.assertEqual(lines[5:10], ["prev 2 0"] * 5, out)
        self.assertEqual(lines[10:], ["wrap 0", "wrap True"], out)

    def test_paging_scrolls_by_eight_and_clamps_and_shows_percent(self):
        out = support.ui(
            "import curses\n"
            "app = make_app(16, 100)\n"
            "app.go('manual'); app.draw()\n"
            "print('more' in text(app))\n"
            "key(app, curses.KEY_NPAGE); print(app.man_scroll)\n"
            "key(app, ' '); print(app.man_scroll)\n"
            "key(app, curses.KEY_PPAGE); print(app.man_scroll)\n"
            "key(app, 'g'); print(app.man_scroll)\n"
            "for _ in range(40): key(app, curses.KEY_NPAGE)\n"
            "end = app.man_scroll\n"
            "key(app, curses.KEY_NPAGE)\n"
            "print(app.man_scroll == end, end > 8, 'more 100%' in text(app))\n", self.home)
        self.assertEqual(out.split(), ["True", "8", "16", "8", "0", "True", "True", "True"], out)

    def test_keys_that_close_the_manual(self):
        out = support.ui(
            "app = make_app(40, 120)\n"
            "for k in ('q', 'm', '\\x1b', '?'):\n"
            "    app.go('manual'); key(app, k); print(repr(k), app.modal)\n", self.home)
        self.assertEqual(out.strip().split("\n"), ["'q' None", "'m' None", "'\\x1b' None", "'?' None"], out)

    def test_install_chip_flashes_once_and_installs_on_the_second_press(self):
        with tempfile.TemporaryDirectory() as empty:
            out = support.ui(
                "app = make_app(40, 120)\n"
                "app.go('manual'); app.draw()\n"
                "print('Install tap' in text(app), app.tap_ok)\n"
                "key(app, 'I'); print(app.tap_ok, 'press I again' in app.flash)\n"
                "key(app, 'I'); print(app.tap_ok, '✓ tap installed' in text(app))\n", empty, demo=False)
        self.assertEqual(out.strip().split("\n"), ["True False", "False True", "True True"], out)

    def test_prompt_shows_and_install_keys_install_and_close(self):
        for k in ("I", "i", "\\n"):
            with self.subTest(key=k), tempfile.TemporaryDirectory() as empty:
                out = support.ui(
                    "app = make_app(40, 120)\n"
                    "app.go('prompt'); app.draw()\n"
                    "print('⚡ Welcome to claudeMon: install the tap?' in text(app))\n"
                    "key(app, '%s'); print(app.modal, app.tap_ok)\n" % k, empty, demo=False)
                self.assertEqual(out.strip().split("\n"), ["True", "None True"], out)

    def test_other_keys_skip_the_prompt(self):
        with tempfile.TemporaryDirectory() as empty:
            out = support.ui(
                "app = make_app(40, 120)\n"
                "app.go('prompt'); key(app, 'x')\n"
                "print(app.modal, app.tap_ok, app.flash)\n", empty, demo=False)
        self.assertEqual(out.strip(), "None False tap skipped: press I any time to install it")

    def test_too_small_guard_draws_one_line_and_holds_the_prompt(self):
        out = support.ui(
            "app = make_app(12, 60)\n"
            "rows = [r.strip() for r in text(app).split('\\n') if r.strip()]\n"
            "print(rows)\n"
            "app.go('prompt'); app.draw()\n"
            "rows = [r.strip() for r in text(app).split('\\n') if r.strip()]\n"
            "print(rows)\n"
            "print(key(app, '\\n'), app.modal)\n"
            "print(key(app, 'q'))\n", self.home)
        lines = out.strip().split("\n")
        self.assertEqual(lines[0], "['claudeMon needs at least 70×16 (now 60×12)']", out)
        self.assertEqual(lines[1], "['claudeMon needs at least 70×16 (now 60×12)', "
                                   "'⚡ enlarge the window to answer the tap prompt (q quits)']", out)
        self.assertEqual(lines[2:], ["True prompt", "False"], out)


class ManualLines(unittest.TestCase):
    def test_markup_kinds_wrap_and_key_column(self):
        out = support.ui(
            "from claudemon.ui import modals\n"
            "body = ['# Head', 'plain text ' * 12, '- a bullet ' * 8, '! callout words ' * 6,\n"
            "        '> k | short', '> longer key | ' + 'description ' * 8, '', '# Second']\n"
            "lines = modals.manual_lines({'body': body}, 40)\n"
            "print([ln[0] for ln in lines])\n"
            "print(max(len(ln[1]) for ln in lines if ln[0] in ('p', 'b')) <= 40)\n"
            "print(sorted(set(ln[3] for ln in lines if ln[0] == 'k')))\n"
            "print(sum(1 for ln in lines if ln[0] == 'k' and ln[1]))\n"
            "print(all(len(ln[1]) == 39 for ln in lines if ln[0] == 'c'))\n"
            "print(lines[-1][:2])\n", tempfile.gettempdir(), demo=False)
        rows = out.strip().split("\n")
        kinds = eval(rows[0])
        self.assertEqual(kinds[0], "h", out)
        self.assertEqual(kinds[1], "p", out)       # a paragraph straight after a heading gets no blank
        for kind in ("b", "c", "k", "blank"):
            self.assertIn(kind, kinds, out)
        self.assertEqual(kinds[-2:], ["blank", "h"], out)   # a heading after content gets a blank line before it
        self.assertEqual(rows[1:], ["True", "[12]", "2", "True", "('h', 'Second')"], out)


if __name__ == "__main__":
    unittest.main()
