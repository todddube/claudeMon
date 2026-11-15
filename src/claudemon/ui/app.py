"""The claudeMon terminal UI: the main loop, header, sidebar and footer, global keys and navigation,
and the state the pages share (passed to them as ctx). The pages are in ui/pages/, the mini view in
ui/mini.py, and the help, manual, tap prompt and too-small guard in ui/modals.py."""

import curses
import locale
import os
import signal
import sys
import time
from collections import Counter
from datetime import datetime

from claudemon.core import config
from claudemon.tap import installer as install
from claudemon.ui import manual
from claudemon.ui import mini as mini_view
from claudemon.ui import modals
from claudemon.ui.pages import PAGES
from claudemon import __version__
from claudemon.ui.draw import STYLE_NOTE, STYLES, Screen, clip, detect_ascii, set_ascii
from claudemon.sources.limits import WINDOWS
from claudemon.sources.store import IDLE, NEEDS_YOU, WORKING, Store
from claudemon.ui.themes import ORDER as THEME_ORDER
from claudemon.ui import widgets as W
from claudemon.ui.widgets import SPANS, STATE_BADGE

INTERVALS = [1, 2, 5, 10]
SIDEBAR_W = 26
FULL_SIZE = (50, 160)       # rows, cols to restore when no full size was seen (matches --window)
DIGITS = "1234567890"       # the page keys `go` accepts as keys rather than as title prefixes


def _index(value, n, default):
    """value when it is an int in range(n), else default (config.json is user-editable)."""
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < n else default


def _size(value):
    """(rows, cols) from config, or None when it is not a plausible terminal size."""
    if isinstance(value, (list, tuple)) and len(value) == 2 and all(isinstance(v, int) and not isinstance(v, bool) for v in value):
        rows, cols = value
        if 16 <= rows <= 500 and 70 <= cols <= 1000:
            return (rows, cols)
    return None


def can_resize():
    """Only Terminal and iTerm resize their window on request; tmux/screen must not be asked."""
    force = os.environ.get("CLAUDEMON_RESIZE")
    if force in ("0", "1"):
        return force == "1"
    if os.environ.get("TMUX") or os.environ.get("STY"):
        return False
    return os.environ.get("TERM_PROGRAM") in ("Apple_Terminal", "iTerm.app")


class App:
    def __init__(self, win, store, cfg):
        self.store = store
        self.cfg = cfg
        theme = cfg.get("theme")
        self.scr = Screen(win, theme if isinstance(theme, str) else "claude")
        self.win = win
        self.span_i = _index(cfg.get("span"), len(SPANS), 1)
        self.interval_i = _index(cfg.get("interval"), len(INTERVALS), 1)
        self.overall = False
        self.by_effort = False
        self.show_all = False
        style = cfg.get("graph") or ("braille" if cfg.get("braille") else "blocks")
        style = style if isinstance(style, str) else "blocks"
        self.style = style if style in STYLES else "blocks"
        self.scr.style = self.style
        self.sel = 0
        self.sel_sid = None
        self.theme_cursor = THEME_ORDER.index(self.scr.theme_name)
        self.modal = None            # None | prompt | manual | help
        self.tap_ok = False
        self._confirm = None
        self.man_i, self.man_scroll = 0, 0
        self.want_session = ""
        self.flash = cfg.pop("flash", "")
        self.side_cache = {}
        self.forecasts = {}
        self.last_tick = 0.0
        self.mini = bool(cfg.get("mini"))
        self.full_size = _size(cfg.get("full_size")) or FULL_SIZE
        self.start_size = None       # the terminal's size when this run started; given back on exit
        self.sized = None            # the size this run last asked the terminal for
        self.pages = list(PAGES)
        self.page_state = {p.id: p.state() for p in self.pages if p.state}
        titles = [p.title for p in self.pages]
        name = cfg.get("page_name")
        self.page = titles.index(name) if name in titles else _index(cfg.get("page"), len(self.pages), 0)

    # ── helpers ────────────────────────────────────────────────────────────
    @property
    def span(self):
        return SPANS[self.span_i][0]

    @property
    def interval(self):
        return INTERVALS[self.interval_i]

    def T(self, role):
        return self.scr.t[role]

    def session_list(self):
        live = self.store.live_sessions()
        if self.show_all or not live:
            recent = [s for s in self.store.recent_sessions(time.time() - self.span) if not s.live]
            recent.sort(key=lambda s: -(s.t.last_ts or 0))
            return live + recent
        return live

    def selected(self, sessions=None):
        sessions = sessions if sessions is not None else self.session_list()
        if not sessions:
            return None
        for i, s in enumerate(sessions):
            if s.sid == self.sel_sid:
                self.sel = i
                return s
        self.sel = min(self.sel, len(sessions) - 1)
        self.sel_sid = sessions[self.sel].sid
        return sessions[self.sel]

    def index_of(self, page_id):
        return next(i for i, p in enumerate(self.pages) if p.id == page_id)

    def page_for_key(self, k):
        """The id of the page key k opens, or None."""
        if k is None or len(k) != 1:
            return None
        return next((p.id for p in self.pages if p.key == k), None)

    def go_page(self, page_id, session=None):
        """Show a page, optionally selecting a session (by sid): how pages and the mini view navigate."""
        self.page = self.index_of(page_id)
        if session is not None:
            self.sel_sid = session

    def move(self, d):
        sessions = self.session_list()
        if not sessions:
            return
        self.selected(sessions)
        self.sel = (self.sel + d) % len(sessions)
        self.sel_sid = sessions[self.sel].sid

    # ── main loop ──────────────────────────────────────────────────────────
    def tick(self, force=False):
        now = time.time()
        if not force and now - self.last_tick < self.interval:
            return False
        self.last_tick = now
        try:
            self.store.refresh()
        except Exception as e:          # a data problem must never take the UI down
            self.flash = "refresh error: %s" % e
        forecasts = {}
        for k in WINDOWS:
            try:
                forecasts[k] = self.store.forecast(k)
            except Exception:           # e.g. the indexer thread changed a dict mid-read: keep the last one
                if k in self.forecasts:
                    forecasts[k] = self.forecasts[k]
        self.forecasts = forecasts
        self.tap_ok = install.installed()
        if self.want_session:
            for s in self.store.live_sessions():
                if self.want_session in s.name.lower():
                    self.sel_sid, self.want_session = s.sid, ""
                    break
        for p in self.pages:
            if p.tick:
                try:
                    p.tick(self)
                except Exception as e:
                    self.flash = "%s error: %s" % (p.id, e)
        self.side_cache = {}
        for p in self.pages:
            try:
                self.side_cache[p.id] = p.side(self)
            except Exception as e:      # a sidebar summary must never take the UI down
                self.side_cache[p.id] = ([], "error", str(e)[:22])
        return True

    def run(self, start=None):
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        self.win.nodelay(False)
        self.win.timeout(150)
        h, w = self.scr.size
        self.start_size = (h, w)
        if h >= 16 and w >= 70:
            self.full_size = (h, w)               # the window we were started in is a real full size
        self.title("\033[22;0t\033]0;claudeMon\007")   # save the old title, then set ours
        try:
            self.loop(start)
        except KeyboardInterrupt:                 # Ctrl-C (or SIGTERM, see run()) quits like q
            pass
        finally:
            if self.sized and self.sized != self.start_size:
                self.resize(*self.start_size)     # give the terminal back the size it had
            self.title("\033[23;0t")              # restore the old title
            self.save()

    def title(self, seq):
        try:
            if sys.stdout.isatty():
                sys.stdout.write(seq)
                sys.stdout.flush()
        except (OSError, ValueError):
            pass

    def loop(self, start):
        self.tick(force=True)
        if start:
            self.go(start)
        elif not self.tap_ok and not self.cfg.get("tap_prompt_seen") and not self.mini:
            self.modal = "prompt"                 # first launch only; the header chip remains after Later
            self.cfg["tap_prompt_seen"] = True    # (never in mini: it has no room to show the prompt)
            config.save(self.cfg)
        dirty = True
        while True:
            if self.tick():
                dirty = True
            if dirty:
                self.draw()
                dirty = False
            try:
                key = self.win.get_wch()
            except curses.error:
                continue
            if key == curses.KEY_RESIZE:
                dirty = True
                continue
            if key == "\x1b" and self.escape_sequence():
                dirty = True
                continue                          # Alt+key or an unknown sequence: not a quit
            if self.on_key(key) is False:
                break
            dirty = True

    def escape_sequence(self):
        """After Esc: True (and the rest is swallowed) when more input follows at once,
        i.e. an Alt+key or a sequence curses did not recognise, rather than a lone Esc."""
        curses.napms(30)
        self.win.nodelay(True)
        seen = False
        try:
            for _ in range(16):
                try:
                    self.win.get_wch()
                except curses.error:
                    break
                seen = True
        finally:
            self.win.nodelay(False)
            self.win.timeout(150)
        return seen

    def go(self, start):
        """Jump to a page by number or name (page:session picks a session), or open manual[:topic] / prompt / mini."""
        name, _, arg = start.lower().partition(":")
        if name == "mini":
            self.mini = True
        elif name == "prompt":
            self.modal = "prompt"
        elif name == "manual":
            self.man_i = next((i for i, t in enumerate(manual.TOPICS) if arg and t["id"].lower().startswith(arg)), 0)
            self.man_scroll, self.modal = 0, "manual"
        else:
            if len(name) == 1 and name in DIGITS:
                if self.page_for_key(name):
                    self.page = self.index_of(self.page_for_key(name))
            elif name.isdecimal() and name.isascii():
                self.page = (int(name) - 1) % len(self.pages)
            else:
                self.page = next((i for i, p in enumerate(self.pages) if p.title.lower().startswith(name)), self.page)
            self.want_session = arg

    def save(self):
        self.cfg.update(theme=self.scr.theme_name, page=self.page, page_name=self.pages[self.page].title,
                        span=self.span_i, interval=self.interval_i,
                        graph=self.style, mini=self.mini, full_size=list(self.full_size))
        config.save(self.cfg)

    def on_key(self, key):
        k = key if isinstance(key, str) else None
        self.flash = ""
        if self.modal:
            return modals.on_key(self, key, k)
        if k in ("q", "Q", "\x1b"):
            return False
        if k == "z":
            mini_view.set_mini(self, not self.mini)
            return True
        if self.mini:
            return mini_view.on_key(self, key, k)
        page = self.pages[self.page]
        if page.on_key and page.on_key(self, key, k):
            return True
        d = W.updown(key, k)
        if self.page_for_key(k):
            self.go_page(self.page_for_key(k))
        elif key in (curses.KEY_RIGHT, "\t") or k == "l":
            self.page = (self.page + 1) % len(self.pages)
        elif key in (curses.KEY_LEFT, curses.KEY_BTAB) or k == "h":
            self.page = (self.page - 1) % len(self.pages)
        elif d:
            self.move(d)
        elif W.is_enter(key):
            self.go_page("inspect")
        elif k == "g":
            self.span_i = (self.span_i + 1) % len(SPANS)
        elif k == "G":
            self.span_i = (self.span_i - 1) % len(SPANS)
        elif k == "u":
            self.interval_i = (self.interval_i + 1) % len(INTERVALS)
        elif k == "t":
            i = (THEME_ORDER.index(self.scr.theme_name) + 1) % len(THEME_ORDER)
            self.scr.set_theme(THEME_ORDER[i])
            self.theme_cursor = i
            self.flash = "theme: " + THEME_ORDER[i]
        elif k == "b":
            self.style = STYLES[(STYLES.index(self.style) + 1) % len(STYLES)]
            self.scr.style = self.style
            self.flash = "graphs: %s (%s)" % (self.style, STYLE_NOTE[self.style])
        elif k == "o":
            self.overall = not self.overall
        elif k == "e":
            self.by_effort = not self.by_effort
        elif k == "a":
            self.show_all = not self.show_all
            self.flash = "showing all recent sessions" if self.show_all else "showing live sessions"
        elif k == "r":
            self.tick(force=True)
        elif k in ("m", "M"):
            self.man_i = manual.topic_index(self.pages[self.page].manual_topic)
            self.man_scroll = 0
            self.modal = "manual"
        elif k == "?":
            self.modal = "help"
        elif k == "I":
            if self.tap_ok:
                self.flash = "tap is already installed"
            elif self.confirm("I", "⚡ press I again to install the tap (settings.json is backed up first)"):
                self.do_install()
        return True

    # ── frame ──────────────────────────────────────────────────────────────
    def draw(self):
        scr = self.scr
        scr.win.erase()
        h, w = scr.size
        if self.mini:
            mini_view.fit(self)
            mini_view.draw(self, h, w)
            scr.win.refresh()
            return
        if modals.too_small(self):
            modals.draw_too_small(self, h, w)
            scr.win.refresh()
            return
        self.draw_header(w)
        self.draw_sidebar(1, h - 2)
        x = SIDEBAR_W + 1
        try:
            self.pages[self.page].render(self, 1, x, h - 2, w - x)
        except Exception as e:
            scr.put(3, x + 2, "page error: %s" % e, self.T("crit"))
        self.draw_footer(h - 1, w)
        modals.draw(self, h, w)
        scr.win.refresh()

    def draw_header(self, w):
        scr = self.scr
        scr.fill(0, 0, 1, w, self.T("hl_bg"))
        bg = self.T("hl_bg")
        x = scr.put(0, 1, " ◆ ", self.T("accent"), bg, curses.A_BOLD) + 1
        x += scr.put(0, x, "claudeMon", self.T("title"), bg, curses.A_BOLD)
        x += scr.put(0, x, "  │  ", self.T("border"), bg)
        live = self.store.live_sessions()
        counts = Counter(s.state() for s in live)
        x += scr.put(0, x, "%d live" % len(live), self.T("fg"), bg)
        for state in (WORKING, NEEDS_YOU, IDLE):
            if counts[state]:
                text, role = STATE_BADGE[state]
                sym, word = text.split(" ", 1)
                x += scr.put(0, x, "  %s %d %s" % (sym, counts[state], word.lower()), self.T(role), bg, curses.A_BOLD if state == NEEDS_YOU else 0)
        indexed, (done, total) = self.store.index_status()
        if not indexed:
            x += scr.put(0, x, "  indexing %d/%d…" % (done, total), self.T("info"), bg)
        if not self.tap_ok:
            x += 2
            x += W.chip(self, 0, x, " ⚡ tap off: press I ", "warn")
        right = "⟳ %ds  %s  %s " % (self.interval, self.scr.theme_name, datetime.now().strftime("%H:%M:%S"))
        dot = self.T("ok") if time.time() - self.last_tick < self.interval + 2 else self.T("crit")
        scr.put(0, w - len(right) - 3, "●", dot, bg)
        scr.put(0, w - len(right) - 1, right, self.T("dim"), bg)

    def draw_sidebar(self, y0, y1):
        scr = self.scr
        avail = y1 - y0
        per = 4 if avail >= 4 * len(self.pages) else 3 if avail >= 3 * len(self.pages) else 1
        for i, p in enumerate(self.pages):
            y = y0 + i * per
            if y + per - 1 > y1:
                break
            active = i == self.page
            bg = self.T("hl_bg") if active else None
            if active:
                scr.fill(y, 0, per - (1 if per == 4 else 0), SIDEBAR_W, self.T("hl_bg"))
                scr.put(y, 0, "▌", self.T("accent"), bg)
            spark, line1, line2 = self.side_cache.get(p.id, ([], "", ""))
            scr.put(y, 1, p.key, self.T("accent") if active else self.T("dim"), bg)
            scr.put(y, 3, p.title, self.T("title") if active else self.T("fg"), bg, curses.A_BOLD)
            if per == 1:
                scr.put(y, 17, clip(line1, SIDEBAR_W - 18), self.T("dim"), bg)
                continue
            tx = 13 if spark else 3
            if spark:
                scr.spark(y + 1, 3, spark, 9)
            scr.put(y + 1, tx, clip(line1, SIDEBAR_W - tx - 1), self.T("fg") if active else self.T("dim"), bg)
            if per >= 3:
                hot = line2.startswith("⚡")
                scr.put(y + 2, tx, clip(line2, SIDEBAR_W - tx - 1), self.T("warn") if hot else self.T("dim"), bg,
                        curses.A_BOLD if hot else 0)
        for row in range(y0, y1 + 1):
            scr.put(row, SIDEBAR_W, "│", self.T("border"))

    def draw_footer(self, y, w):
        scr = self.scr
        keys = [("1-0", "pages"), ("z", "mini"), ("←→", "page"), ("↑↓", "select"), ("⏎", "inspect"), ("g", "range"),
                ("o", "overall"), ("a", "all"), ("t", "theme"), ("u", "update"), ("m", "manual"), ("?", "help"), ("q", "quit")]
        x = 1
        if not self.tap_ok:
            x += W.chip(self, y, x, " ⚡ I install tap ", "warn") + 2
        for k, label in keys:
            if x + len(k) + len(label) + 3 > w - 30:
                break
            x += scr.put(y, x, k, self.T("accent"), extra=curses.A_BOLD)
            x += scr.put(y, x, " %s  " % label, self.T("dim"))
        msg = self.flash or ("claudeMon v%s" % __version__)
        scr.put(y, w - len(msg) - 2, msg, self.T("info") if self.flash else self.T("border"))

    # ── window ─────────────────────────────────────────────────────────────
    def resize(self, rows, cols):
        """Ask the terminal to resize its window (xterm CSI 8 t; Terminal and iTerm honour it)."""
        if not can_resize():
            return
        self.sized = (rows, cols)
        self.title("\033[8;%d;%dt" % (rows, cols))

    # ── shared by the pages, the mini view and the modals ──────────────────
    def confirm(self, key, msg):
        now = time.time()
        if self._confirm and self._confirm[0] == key and now - self._confirm[1] < 6:
            self._confirm = None
            return True
        self._confirm = (key, now)
        self.flash = msg
        return False

    def do_install(self):
        try:
            self.flash = install.install()
        except Exception as e:
            self.flash = "install failed: %s" % e
        self.tap_ok = install.installed()

    def not_reported(self, key):
        """True when the tap works but Claude Code reports no such window for this account
        (some plans report only the weekly limit), so waiting longer will not help."""
        return self.tap_ok and any(f and f.pct is not None for k, f in self.forecasts.items() if k != key)


def run(theme=None, interval=None, start=None, mini=False):
    try:
        locale.setlocale(locale.LC_ALL, "")      # curses needs this to draw UTF-8 (blocks, box lines)
    except locale.Error:
        pass
    set_ascii(detect_ascii())
    cfg = config.load()
    if theme:
        cfg["theme"] = theme
    if interval:
        cfg["interval"] = INTERVALS.index(interval) if interval in INTERVALS else 1
    if mini or start:
        cfg["mini"] = mini              # an explicit page opens the full view
    note = install.repair()          # keeps an installed tap working (never raises)
    if note:
        cfg["flash"] = note
    store = Store()
    store.prune_state()
    store.start()
    os.environ.setdefault("ESCDELAY", "25")

    def on_term(signum, frame):
        raise KeyboardInterrupt      # leave through App.run's cleanup: save prefs, restore the window

    try:
        signal.signal(signal.SIGTERM, on_term)
        signal.signal(signal.SIGHUP, on_term)
    except (ValueError, OSError):
        pass

    def main(win):
        curses.start_color()
        curses.use_default_colors()
        App(win, store, cfg).run(start)

    try:
        curses.wrapper(main)
    except KeyboardInterrupt:        # Ctrl-C before the loop started
        pass
