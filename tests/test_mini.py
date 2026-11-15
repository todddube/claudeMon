"""The mini view (z): entering and leaving, its keys, and what it draws."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

SESSIONS = ["web shop", "tests", "release notes", "data cleanup", "migration", "firmware", "api refactor", "docs"]


def lines(out):
    return out.splitlines()


class MiniEnterLeave(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.demo = support.DemoHome()
        cls.home = cls.demo.start()

    @classmethod
    def tearDownClass(cls):
        cls.demo.stop()

    def test_z_enters_mini_and_z_again_leaves_it(self):
        out = support.ui(
            "app = make_app(40, 120)\n"
            "print(app.mini)\n"
            "key(app, 'z'); print(app.mini)\n"
            "key(app, 'z'); print(app.mini)\n", self.home)
        self.assertEqual(lines(out), ["False", "True", "False"], out)

    def test_resize_follows_the_session_count_and_returns_to_the_full_size(self):
        out = support.ui(
            "app = make_app(40, 120)\n"
            "n = len(app.session_list())\n"
            "print(n, 6 + max(1, min(n, 10)) + (1 if n > 10 else 0))\n"
            "print(app.sized)\n"
            "key(app, 'z'); print(app.sized)\n"
            "key(app, 'z'); print(app.sized, app.full_size)\n",
            self.home, env={"CLAUDEMON_RESIZE": "1"})
        out = lines(out)
        n, height = out[0].split()
        self.assertEqual(n, "8", out)
        self.assertEqual(out[1], "None", out)
        self.assertEqual(out[2], "(%s, 74)" % height, out)
        self.assertEqual(out[3], "(40, 120) (40, 120)", out)

    def test_no_resize_when_the_terminal_is_not_asked_to(self):
        out = support.ui(
            "app = make_app(40, 120)\n"
            "key(app, 'z'); print(app.mini, app.sized)\n"
            "key(app, 'z'); print(app.mini, app.sized)\n",
            self.home, env={"CLAUDEMON_RESIZE": "0"})
        self.assertEqual(lines(out), ["True None", "False None"], out)

    def test_more_than_ten_sessions_add_a_more_row_to_the_height(self):
        out = support.ui(
            "from claudemon.ui import mini\n"
            "app = make_app(40, 120)\n"
            "for n in (0, 1, 5, 10, 11, 30):\n"
            "    app.session_list = lambda n=n: [None] * n\n"
            "    print(n, mini.height(app))\n", self.home)
        self.assertEqual(lines(out), ["0 7", "1 7", "5 11", "10 16", "11 17", "30 17"], out)

    def test_a_full_size_is_remembered_only_from_a_window_of_16x70_or_more(self):
        out = support.ui(
            "for rows, cols in ((12, 74), (16, 69), (15, 70), (16, 70), (50, 160)):\n"
            "    app = make_app(rows, cols)\n"
            "    key(app, 'z')\n"
            "    print(rows, cols, app.full_size)\n", self.home, env={"CLAUDEMON_RESIZE": "1"})
        self.assertEqual(lines(out), [
            "12 74 (50, 160)", "16 69 (50, 160)", "15 70 (50, 160)", "16 70 (16, 70)", "50 160 (50, 160)"], out)


class MiniKeys(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.demo = support.DemoHome()
        cls.home = cls.demo.start()

    @classmethod
    def tearDownClass(cls):
        cls.demo.stop()

    def test_arrows_and_j_k_move_the_selection(self):
        out = support.ui(
            "import curses\n"
            "app = make_app(12, 74, mini=True)\n"
            "def sel(): return app.selected().sid\n"
            "a = sel()\n"
            "key(app, 'j'); b = sel()\n"
            "key(app, curses.KEY_DOWN); c = sel()\n"
            "key(app, 'k'); d = sel()\n"
            "key(app, curses.KEY_UP); e = sel()\n"
            "print(a != b, b != c, c == app.session_list()[2].sid, d == b, e == a, app.mini)\n", self.home)
        self.assertEqual(out.strip(), "True True True True True True", out)

    def test_enter_opens_inspect_in_the_full_view(self):
        out = support.ui(
            "import curses\n"
            "for k in ('\\n', '\\r', curses.KEY_ENTER):\n"
            "    app = make_app(12, 74, mini=True)\n"
            "    key(app, k)\n"
            "    print(app.mini, app.pages[app.page].id)\n", self.home)
        self.assertEqual(lines(out), ["False inspect"] * 3, out)

    def test_each_page_key_opens_that_page_in_the_full_view(self):
        out = support.ui(
            "for p in tui.PAGES:\n"
            "    app = make_app(12, 74, mini=True)\n"
            "    key(app, p.key)\n"
            "    print(p.key, p.id, app.mini, app.pages[app.page].id)\n", self.home)
        rows = [line.split() for line in lines(out)]
        self.assertEqual(len(rows), 11, out)
        for key, pid, mini, opened in rows:
            self.assertEqual((mini, opened), ("False", pid), "key %s: %s" % (key, out))

    def test_m_and_question_mark_leave_mini_for_the_manual_and_help(self):
        out = support.ui(
            "for k in ('m', 'M', '?'):\n"
            "    app = make_app(12, 74, mini=True)\n"
            "    app.man_i = 3; app.man_scroll = 5\n"
            "    key(app, k)\n"
            "    print(k, app.mini, app.modal, app.man_i, app.man_scroll)\n", self.home)
        self.assertEqual(lines(out), ["m False manual 0 0", "M False manual 0 0", "? False help 3 5"], out)

    def test_t_cycles_the_theme_and_sets_the_cursor(self):
        out = support.ui(
            "from claudemon.ui.themes import ORDER\n"
            "app = make_app(12, 74, mini=True, theme=ORDER[0])\n"
            "for i in (1, 2):\n"
            "    key(app, 't')\n"
            "    print(app.scr.theme_name == ORDER[i], app.theme_cursor == i, app.flash == 'theme: ' + ORDER[i])\n"
            "app = make_app(12, 74, mini=True, theme=ORDER[-1])\n"
            "key(app, 't'); print(app.scr.theme_name == ORDER[0], app.theme_cursor)\n", self.home)
        self.assertEqual(lines(out), ["True True True", "True True True", "True 0"], out)

    def test_b_cycles_the_style_with_a_short_flash(self):
        out = support.ui(
            "from claudemon.ui.draw import STYLES\n"
            "app = make_app(12, 74, mini=True, graph=STYLES[0])\n"
            "for i in (1, 2):\n"
            "    key(app, 'b')\n"
            "    print(app.style == STYLES[i], app.scr.style == STYLES[i], app.flash == 'graphs: ' + STYLES[i])\n", self.home)
        self.assertEqual(lines(out), ["True True True"] * 2, out)

    def test_a_toggles_all_recent_sessions(self):
        out = support.ui(
            "app = make_app(12, 74, mini=True)\n"
            "key(app, 'a'); print(app.show_all, app.flash)\n"
            "key(app, 'a'); print(app.show_all, app.flash)\n", self.home)
        self.assertEqual(lines(out), ["True all recent sessions", "False live sessions"], out)

    def test_q_and_escape_quit_from_mini(self):
        out = support.ui(
            "app = make_app(12, 74, mini=True)\n"
            "print(key(app, 'q'), key(app, '\\x1b'), key(app, 'x'))\n", self.home)
        self.assertEqual(out.strip(), "False False True", out)


class MiniInstallKey(unittest.TestCase):
    def test_I_once_asks_and_twice_installs_the_tap(self):
        with support.DemoHome(no_tap=True) as home:
            out = support.ui(
                "from claudemon.tap import installer as install\n"
                "app = make_app(12, 74, mini=True)\n"
                "print(app.tap_ok, install.installed())\n"
                "key(app, 'I'); print(app.flash, app.tap_ok, install.installed())\n"
                "key(app, 'I'); print(app.tap_ok, install.installed(), 'tap off' in text(app))\n"
                "key(app, 'I'); print(app.flash)\n", home)
        self.assertEqual(lines(out), [
            "False False",
            "⚡ I again installs the tap False False",
            "True True False",
            "tap is already installed"], out)


class MiniDrawing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.demo = support.DemoHome()
        cls.home = cls.demo.start()

    @classmethod
    def tearDownClass(cls):
        cls.demo.stop()

    def test_74x14_shows_both_limits_burn_and_every_live_session(self):
        out = support.ui("app = make_app(14, 74, mini=True)\nprint(text(app))\n", self.home)
        for want in ["5h", "7d", "burn", "Sessions", "z full", "8 live"] + SESSIONS:
            self.assertIn(want, out, "missing %r in:\n%s" % (want, out))
        self.assertNotIn("more (z for the full view)", out)

    def test_50x8_lists_what_fits_and_counts_the_rest(self):
        out = support.ui("app = make_app(8, 50, mini=True)\nprint(text(app))\n", self.home)
        self.assertIn("+", out)
        self.assertRegex(out, r"\+\d+ more \(z for the full view\)")

    def test_the_selected_session_stays_on_screen(self):
        out = support.ui(
            "app = make_app(8, 50, mini=True)\n"
            "names = [s.name for s in app.session_list()]\n"
            "for i in range(len(names)):\n"
            "    app.sel = i; app.sel_sid = app.session_list()[i].sid\n"
            "    app.draw()\n"
            "    print(names[i][:5] in text(app))      # the name column is 7 wide at this size\n", self.home)
        self.assertEqual(lines(out), ["True"] * 8, out)

    def test_a_window_below_40x6_shows_only_the_guard(self):
        out = support.ui("app = make_app(5, 39, mini=True)\nprint(text(app))\n", self.home)
        self.assertIn("mini needs 40×6 (z for the full view)", out)
        self.assertNotIn("Sessions", out)

    def test_the_tap_hint_is_in_the_footer_until_the_tap_is_installed(self):
        out = support.ui(
            "app = make_app(14, 74, mini=True)\n"
            "print(app.tap_ok, 'tap off: I I' in text(app))\n"
            "app.do_install(); app.flash = ''; app.tick(force=True); app.draw()\n"
            "print(app.tap_ok, 'tap off' in text(app))\n", self.home)
        self.assertEqual(lines(out), ["False True", "True False"], out)

    def test_the_footer_lists_the_mini_keys(self):
        out = support.ui("app = make_app(14, 74, mini=True)\nprint(text(app).splitlines()[-1])\n", self.home)
        for want in ["z full", "q quit", "select", "inspect", "1-0 page", "t theme"]:
            self.assertIn(want, out)


class MiniWithoutTap(unittest.TestCase):
    def test_the_footer_says_the_tap_is_off(self):
        with support.DemoHome(no_tap=True) as home:
            out = support.ui("app = make_app(14, 74, mini=True)\nprint(text(app))\n", home)
        self.assertIn("⚡ tap off: I I", out)
        self.assertIn("⚡ I I installs the tap", out)


class MiniEmptyHome(unittest.TestCase):
    def test_no_sessions_says_so(self):
        with tempfile.TemporaryDirectory() as home:
            out = support.ui("app = make_app(12, 74, mini=True)\nprint(text(app))\n", home)
        self.assertIn("no live Claude Code sessions", out)
        self.assertIn("0 live", out)

    def test_mini_start_never_raises_the_first_launch_prompt(self):
        with tempfile.TemporaryDirectory() as home:
            out = support.ui(
                "import curses\n"
                "class W(g.FakeWin):\n"
                "    keys = ['\\n', 'q']\n"
                "    def nodelay(self, f): pass\n"
                "    def timeout(self, t): pass\n"
                "    def get_wch(self):\n"
                "        if not self.keys: raise curses.error()\n"
                "        return self.keys.pop(0)\n"
                "curses.curs_set = lambda n: None\n"
                "st = store.Store(); st.indexed = True\n"
                "app = tui.App(W(12, 74), st, {'mini': True})\n"
                "app.run()\n"
                "print(app.modal)\n"
                "app = make_app(12, 74, mini=True, tap_prompt_seen=False)\n"
                "print(app.modal)\n", home)
        self.assertEqual(lines(out), ["None", "None"], out)


if __name__ == "__main__":
    unittest.main()
