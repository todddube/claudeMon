"""The pages with keys, state and navigation: Tasks, Session and Weekly limit, Inspect and Settings."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

PAGE_KEYS = ["2", "7", "8", "0", "s"]
SIZES = [(16, 70), (36, 120), (60, 200)]

RENDER = (
    "import json\n"
    "from claudemon.ui import draw\n"
    "bad, side = [], {}\n"
    "for ascii_ in (False, True):\n"
    "    draw.set_ascii(ascii_)\n"
    "    for rows, cols in %r:\n"
    "        app = make_app(rows, cols)\n"
    "        for k in %r:\n"
    "            key(app, k)\n"
    "            if 'page error' in text(app):\n"
    "                bad.append((ascii_, rows, cols, k))\n"
    "            for p in app.pages:\n"
    "                v = app.side_cache[p.id]\n"
    "                if not (isinstance(v, tuple) and len(v) == 3 and isinstance(v[0], list)\n"
    "                        and isinstance(v[1], str) and isinstance(v[2], str)):\n"
    "                    side[p.id] = repr(v)\n"
    "print(json.dumps([bad, side]))\n"
) % (SIZES, PAGE_KEYS)


class RenderEverywhere(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.demo = support.DemoHome()
        cls.home = cls.demo.start()

    @classmethod
    def tearDownClass(cls):
        cls.demo.stop()

    def check(self, home, demo=True):
        import json
        bad, side = json.loads(support.ui(RENDER, home, demo=demo))
        self.assertEqual(bad, [], "pages drew a page error")
        self.assertEqual(side, {}, "side() must give (list, str, str)")

    def test_pages_render_on_the_demo_home_at_every_size_and_in_ascii(self):
        self.check(self.home)

    def test_pages_render_on_an_empty_home(self):
        with tempfile.TemporaryDirectory() as empty:
            self.check(empty)


class TasksPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.demo = support.DemoHome()
        cls.home = cls.demo.start()

    @classmethod
    def tearDownClass(cls):
        cls.demo.stop()

    def test_the_tree_is_built_off_page_and_in_mini(self):
        out = support.ui(
            "a = make_app(36, 120)\n"
            "b = make_app(36, 120, mini=True)\n"
            "print(a.pages[a.page].id, len(a.page_state['tasks'].rows) > 0)\n"
            "print(b.mini, len(b.page_state['tasks'].rows) > 0)\n"
            "print(a.page_state['tasks'] is b.page_state['tasks'])\n", self.home)
        self.assertEqual(out.split("\n")[:3], ["burn True", "True True", "False"], out)

    def test_the_cursor_visits_selectable_rows_only_and_wraps(self):
        out = support.ui(
            "import curses\n"
            "app = make_app(36, 120)\n"
            "key(app, '2')\n"
            "st = app.page_state['tasks']\n"
            "sel = [i for i, r in enumerate(st.rows) if r.kind != 'header']\n"
            "seen = [st.i]\n"
            "for _ in range(len(sel)):\n"
            "    key(app, 'j'); seen.append(st.i)\n"
            "print(all(i in sel for i in seen), seen[0] == seen[-1], len(set(seen)) == len(sel))\n"
            "key(app, curses.KEY_DOWN); down = st.i\n"
            "key(app, curses.KEY_UP); up = st.i\n"
            "print(down != up, up == seen[0])\n"
            "key(app, 'k'); a = st.i\n"
            "key(app, curses.KEY_UP); b = st.i\n"
            "print(a in sel and b in sel, len(sel) > 1)\n", self.home)
        self.assertEqual(out.split("\n")[:3], ["True True True", "True True", "True True"], out)

    def test_enter_on_a_session_row_opens_inspect_on_that_session(self):
        out = support.ui(
            "app = make_app(36, 120)\n"
            "key(app, '2')\n"
            "st = app.page_state['tasks']\n"
            "rows = [i for i, r in enumerate(st.rows) if r.kind == 'session']\n"
            "st.i = rows[1]\n"
            "sid = st.rows[st.i].obj.sid\n"
            "key(app, '\\n')\n"
            "print(app.pages[app.page].id, app.sel_sid == sid)\n", self.home)
        self.assertEqual(out.split(), ["inspect", "True"], out)


class LimitPages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.demo = support.DemoHome()
        cls.home = cls.demo.start()
        cls.bare = support.DemoHome(no_tap=True)
        cls.bare_home = cls.bare.start()

    @classmethod
    def tearDownClass(cls):
        cls.demo.stop()
        cls.bare.stop()

    def test_both_pages_come_from_the_limits_module(self):
        out = support.ui(
            "from claudemon.ui.pages import limits\n"
            "app = make_app()\n"
            "print(limits.SESSION in app.pages, limits.WEEKLY in app.pages)\n"
            "print(limits.SESSION.id, limits.WEEKLY.id, limits.SESSION.key, limits.WEEKLY.key)\n", self.home)
        self.assertEqual(out.split("\n")[:2], ["True True", "session_limit weekly_limit 7 8"], out)

    def test_pages_show_a_percentage_and_their_window_label_with_the_tap(self):
        out = support.ui(
            "app = make_app(36, 120)\n"
            "for k, label in (('7', 'Session limit'), ('8', 'Weekly limit')):\n"
            "    key(app, k)\n"
            "    t = text(app)\n"
            "    f = app.forecasts['five_hour' if k == '7' else 'seven_day']\n"
            "    print(label in t, '%.0f%%' % f.pct in t, 'needs the claudeMon tap' in t)\n"
            "    print(app.side_cache[app.pages[app.page].id][1] == '%d%%' % round(f.pct))\n", self.home)
        self.assertEqual(out.split("\n")[:4], ["True True False", "True", "True True False", "True"], out)

    def test_pages_show_the_tap_callout_without_the_tap(self):
        out = support.ui(
            "app = make_app(36, 120)\n"
            "print(app.tap_ok)\n"
            "for k in '78':\n"
            "    key(app, k)\n"
            "    print('needs the claudeMon tap' in text(app))\n"
            "    print(app.side_cache[app.pages[app.page].id][1:])\n", self.bare_home)
        lines = out.split("\n")
        self.assertEqual([lines[0], lines[1], lines[3]], ["False", "True", "True"], out)
        self.assertEqual(lines[2], "('no data', '\u26a1 install tap')", out)


class InspectPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.demo = support.DemoHome()
        cls.home = cls.demo.start()

    @classmethod
    def tearDownClass(cls):
        cls.demo.stop()

    def test_go_with_a_session_name_selects_it(self):
        out = support.ui(
            "import curses\n"
            "app = make_app(36, 120)\n"
            "app.go('inspect:web shop'); app.tick(force=True); app.draw()\n"
            "s = app.selected()\n"
            "print(app.pages[app.page].id, s.name, s.name in text(app))\n"
            "before = app.sel_sid\n"
            "key(app, curses.KEY_DOWN)\n"
            "print(app.sel_sid != before)\n", self.home)
        self.assertEqual(out.split("\n")[:2], ["inspect web shop True", "True"], out)

    def test_enter_on_a_page_without_its_own_enter_opens_inspect(self):
        out = support.ui(
            "app = make_app(36, 120)\n"
            "key(app, '5')\n"
            "print(app.pages[app.page].id)\n"
            "key(app, '\\n')\n"
            "print(app.pages[app.page].id)\n", self.home)
        self.assertEqual(out.split(), ["traffic", "inspect"], out)


class SettingsPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.demo = support.DemoHome(no_tap=True)
        cls.home = cls.demo.start()

    @classmethod
    def tearDownClass(cls):
        cls.demo.stop()

    def test_arrows_move_the_theme_cursor_and_enter_applies_it(self):
        out = support.ui(
            "import curses\n"
            "from claudemon.ui import themes\n"
            "app = make_app(36, 120)\n"
            "key(app, 's')\n"
            "start = app.theme_cursor\n"
            "n = len(themes.ORDER)\n"
            "key(app, curses.KEY_DOWN)\n"
            "print(app.theme_cursor == (start + 1) % n)\n"
            "key(app, 'k')\n"
            "print(app.theme_cursor == start)\n"
            "app.theme_cursor = n - 1\n"
            "key(app, 'j')\n"
            "print(app.theme_cursor)\n"
            "key(app, 'k')\n"
            "print(app.theme_cursor == n - 1)\n"
            "key(app, '\\n')\n"
            "print(app.scr.theme_name == themes.ORDER[n - 1])\n", self.home)
        self.assertEqual(out.split(), ["True", "True", "0", "True", "True"], out)

    def test_u_twice_uninstalls_the_tap_installed_by_i_twice(self):
        out = support.ui(
            "app = make_app(36, 120)\n"
            "print(app.tap_ok)\n"
            "key(app, 'I'); print(app.tap_ok)\n"
            "key(app, 'I'); print(app.tap_ok)\n"
            "key(app, 's')\n"
            "key(app, 'U')\n"
            "print(app.tap_ok, 'press U again' in app.flash)\n"
            "key(app, 'U')\n"
            "print(app.tap_ok)\n", self.home)
        self.assertEqual(out.split("\n")[:5], ["False", "False", "True", "True True", "False"], out)


if __name__ == "__main__":
    unittest.main()
