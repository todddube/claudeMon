"""The claudeMon terminal UI: a sidebar of live mini-graphs and ten pages."""

import curses
import locale
import math
import os
import signal
import sys
import textwrap
import time
from collections import Counter, defaultdict
from datetime import datetime

import config
import install
import manual
import tasks as tasks_mod
from version import __version__
from draw import GLYPHS, STYLE_NOTE, STYLES, Canvas, Screen, blocks, clip, detect_ascii, set_ascii
from limits import WINDOWS
from store import DONE, IDLE, NEEDS_YOU, WORKING, Store, short_model, weight
from themes import ORDER as THEME_ORDER
from themes import THEMES

SPANS = [(300, "5m"), (900, "15m"), (3600, "1h"), (6 * 3600, "6h"), (86400, "24h")]
INTERVALS = [1, 2, 5, 10]
SIDEBAR_W = 26
MISS_FLOOR = 2000      # a call this big with almost no cache read counts as a miss
MINI_W, MINI_MAX = 74, 10   # mini view: window width, most session rows before "+n more"
FULL_SIZE = (50, 160)       # rows, cols to restore when no full size was seen (matches --window)
DIGITS = "1234567890"       # page keys, in page order: 1 is the first page, 0 the tenth


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


# ── formatting ─────────────────────────────────────────────────────────────
def ftok(n):
    n = n or 0
    for div, suf in ((1e9, "G"), (1e6, "M"), (1e3, "k")):
        if abs(n) >= div:
            v = n / div
            return ("%.2f" % v if v < 10 else "%.1f" % v if v < 100 else "%.0f" % v) + suf
    return "%d" % n


def fdur(s):
    if s is None:
        return "—"
    s = int(max(0, s))
    if s >= 86400:
        return "%dd%02dh" % (s // 86400, s % 86400 // 3600)
    if s >= 3600:
        return "%dh%02dm" % (s // 3600, s % 3600 // 60)
    if s >= 60:
        return "%dm%02ds" % (s // 60, s % 60)
    return "%ds" % s


def fclock(ts, weekday=False):
    if not ts:
        return "—"
    d = datetime.fromtimestamp(ts)
    return d.strftime("%a %H:%M" if weekday or abs(ts - time.time()) > 20 * 3600 else "%H:%M")


def fdate(ts, weekly):
    d = datetime.fromtimestamp(ts)
    return d.strftime("%a %-d %b %H:%M") if weekly else d.strftime("%H:%M")


def fpct(f):
    return "—" if f is None else "%d%%" % round(f * 100)


STATE_ROLE_TUI = {WORKING: "ok", NEEDS_YOU: "warn", IDLE: "dim"}
STATE_BADGE = {
    WORKING: ("● Working", "ok"),
    NEEDS_YOU: ("▲ Needs you", "warn"),
    IDLE: ("○ Idle", "dim"),
    DONE: ("· Done", "dim"),
}


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
        self.task_rows, self.task_counts = [], dict(sessions=0, tools=0, agents=0, bg=0, procs=0, queued=0)
        self.task_i, self.task_key, self.task_top = 0, None, 0
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
        self.pages = [
            ("Token burn", self.page_burn, self.side_burn),
            ("Tasks", self.page_tasks, self.side_tasks),
            ("Context", self.page_context, self.side_context),
            ("Prompt cache", self.page_cache, self.side_cache_),
            ("Traffic", self.page_traffic, self.side_traffic),
            ("Models", self.page_models, self.side_models),
            ("Session limit", lambda *a: self.page_limit("five_hour", *a), lambda: self.side_limit("five_hour")),
            ("Weekly limit", lambda *a: self.page_limit("seven_day", *a), lambda: self.side_limit("seven_day")),
            ("Projects", self.page_projects, self.side_projects),
            ("Inspect", self.page_inspect, self.side_inspect),
            ("Settings", self.page_settings, self.side_settings),
        ]
        titles = [p[0] for p in self.pages]
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

    def move(self, d):
        sessions = self.session_list()
        if not sessions:
            return
        self.selected(sessions)
        self.sel = (self.sel + d) % len(sessions)
        self.sel_sid = sessions[self.sel].sid

    def grad_fn(self):
        return lambda frac: self.scr.grad_color(frac)

    def chart(self, y, x, h, w, values, vmax=None, color=None, line=None, scale_fmt=ftok, grid=True, style=None):
        """Area chart in the chosen graph style filling an h×w cell rectangle; returns the scale used."""
        style = style or self.style
        if h < 1 or w < 2:
            return 0
        top = vmax if vmax is not None else (max(values) if values else 0)
        color_fn = (lambda f: color) if color is not None else self.grad_fn()
        g = ("." if style == "ascii" else "┈", max(2, h // 3), self.T("border")) if grid and h >= 4 else None
        if style in ("braille", "line"):
            cv = Canvas(w, h)
            if style == "line":
                cv.trace(values, top or 1, color_fn)
            else:
                cv.area(values, top or 1, color_fn, line)
            cv.render(self.scr, y, x, self.T("accent"), grid=g)
        else:
            blocks(self.scr, y, x, h, w, values, top or 1, color_fn, g, GLYPHS[style])
        if scale_fmt and top:
            lab = scale_fmt(top)
            self.scr.put(y, x + w - len(lab), lab, self.T("dim"))
        return top

    def nbuckets(self, w):
        return max(2, min(w * (2 if self.style in ("braille", "line") else 1), self.span // 5))

    def per_min(self, values):
        size = self.span / max(1, len(values))
        return [v * 60 / size for v in values]

    def kv(self, y, x, label, value, color=None, w=14):
        self.scr.put(y, x, label, self.T("dim"), maxw=w)
        self.scr.put(y + 1, x, value, color or self.T("fg"), extra=curses.A_BOLD, maxw=w)

    def toggles(self, y, x, label, options, active, key):
        x0 = x
        x += self.scr.put(y, x, label + " ", self.T("dim"))
        for i, opt in enumerate(options):
            if i == active:
                x += self.scr.put(y, x, " %s " % opt, self.T("bg") if self.T("bg") >= 0 else 16, self.T("accent"), curses.A_BOLD)
            else:
                x += self.scr.put(y, x, " %s " % opt, self.T("fg"))
        x += self.scr.put(y, x, " [%s]  " % key, self.T("border"))
        return x - x0

    def span_toggle(self, y, x):
        return self.toggles(y, x, "Graph", [s[1] for s in SPANS], self.span_i, "g")

    def badge(self, y, x, state):
        text, role = STATE_BADGE[state]
        return self.scr.put(y, x, text, self.T(role), extra=curses.A_BOLD if state == NEEDS_YOU else 0)

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
                forecasts[k] = self.store.limits.forecast(k, self.store.tokens_between)
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
        try:
            self.task_rows, self.task_counts = tasks_mod.build(self.store)
            for i, r in enumerate(self.task_rows):
                if self.task_key == (r.depth, r.kind, r.text):
                    self.task_i = i
                    break
        except Exception as e:
            self.flash = "tasks error: %s" % e
        self.side_cache = {}
        for i, (_, _, side) in enumerate(self.pages):
            try:
                self.side_cache[i] = side()
            except Exception as e:      # a sidebar summary must never take the UI down
                self.side_cache[i] = ([], "error", str(e)[:22])
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

    def digit_page(self, k):
        """The page a digit key opens (1 = first ... 0 = tenth), clamped to the pages there are."""
        return min(DIGITS.index(k), len(self.pages) - 1)

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
                self.page = self.digit_page(name)
            elif name.isdecimal() and name.isascii():
                self.page = (int(name) - 1) % len(self.pages)
            else:
                self.page = next((i for i, p in enumerate(self.pages) if p[0].lower().startswith(name)), self.page)
            self.want_session = arg

    def save(self):
        self.cfg.update(theme=self.scr.theme_name, page=self.page, page_name=self.pages[self.page][0],
                        span=self.span_i, interval=self.interval_i,
                        graph=self.style, mini=self.mini, full_size=list(self.full_size))
        config.save(self.cfg)

    def on_key(self, key):
        k = key if isinstance(key, str) else None
        self.flash = ""
        if self.modal == "prompt":
            return self.key_prompt(key, k)
        if self.modal == "manual":
            return self.key_manual(key, k)
        if self.modal == "help":
            self.modal = None
            return True
        if k in ("q", "Q", "\x1b"):
            return False
        if k == "z":
            self.set_mini(not self.mini)
            return True
        if self.mini:
            return self.key_mini(key, k)
        settings, tasks, inspect = self.idx("Settings"), self.idx("Tasks"), self.idx("Inspect")
        d = 1 if (key == curses.KEY_DOWN or k == "j") else -1 if (key == curses.KEY_UP or k == "k") else 0
        if k is not None and len(k) == 1 and k in DIGITS:
            self.page = self.digit_page(k)
        elif k == "s":
            self.page = settings
        elif key in (curses.KEY_RIGHT, "\t") or k == "l":
            self.page = (self.page + 1) % len(self.pages)
        elif key in (curses.KEY_LEFT, curses.KEY_BTAB) or k == "h":
            self.page = (self.page - 1) % len(self.pages)
        elif d:
            if self.page == settings:
                self.theme_cursor = (self.theme_cursor + d) % len(THEME_ORDER)
            elif self.page == tasks:
                self.task_move(d)
            else:
                self.move(d)
        elif key in ("\n", "\r", curses.KEY_ENTER):
            if self.page == settings:
                self.scr.set_theme(THEME_ORDER[self.theme_cursor])
            elif self.page == tasks:
                self.task_open()
            else:
                self.page = inspect
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
            self.man_i = manual.topic_for_page(self.pages[self.page][0])
            self.man_scroll = 0
            self.modal = "manual"
        elif k == "?":
            self.modal = "help"
        elif k == "I":
            if self.tap_ok:
                self.flash = "tap is already installed"
            elif self.confirm("I", "⚡ press I again to install the tap (settings.json is backed up first)"):
                self.do_install()
        elif k == "U" and self.page == settings:
            if self.confirm("U", "press U again to remove the tap and restore your status line"):
                try:
                    self.flash = install.uninstall()
                except Exception as e:
                    self.flash = "uninstall failed: %s" % e
                self.tap_ok = install.installed()
        return True

    # ── frame ──────────────────────────────────────────────────────────────
    def draw(self):
        scr = self.scr
        scr.win.erase()
        h, w = scr.size
        if self.mini:
            self.fit_mini()
            self.draw_mini(h, w)
            scr.win.refresh()
            return
        if h < 16 or w < 70:
            scr.put(0, 0, "claudeMon needs at least 70×16 (now %d×%d)" % (w, h), self.T("warn"))
            scr.win.refresh()
            return
        self.draw_header(w)
        self.draw_sidebar(1, h - 2)
        x = SIDEBAR_W + 1
        title, render, _ = self.pages[self.page]
        try:
            render(1, x, h - 2, w - x)
        except Exception as e:
            scr.put(3, x + 2, "page error: %s" % e, self.T("crit"))
        self.draw_footer(h - 1, w)
        if self.modal == "help":
            self.draw_help(h, w)
        elif self.modal == "manual":
            self.draw_manual(h, w)
        elif self.modal == "prompt":
            self.draw_prompt(h, w)
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
        if not self.store.indexed:
            done, total = self.store.index_progress
            x += scr.put(0, x, "  indexing %d/%d…" % (done, total), self.T("info"), bg)
        if not self.tap_ok:
            x += 2
            x += self.chip(0, x, " ⚡ tap off: press I ", "warn")
        right = "⟳ %ds  %s  %s " % (self.interval, self.scr.theme_name, datetime.now().strftime("%H:%M:%S"))
        dot = self.T("ok") if time.time() - self.last_tick < self.interval + 2 else self.T("crit")
        scr.put(0, w - len(right) - 3, "●", dot, bg)
        scr.put(0, w - len(right) - 1, right, self.T("dim"), bg)

    def draw_sidebar(self, y0, y1):
        scr = self.scr
        avail = y1 - y0
        per = 4 if avail >= 4 * len(self.pages) else 3 if avail >= 3 * len(self.pages) else 1
        for i, (title, _, _) in enumerate(self.pages):
            y = y0 + i * per
            if y + per - 1 > y1:
                break
            active = i == self.page
            bg = self.T("hl_bg") if active else None
            if active:
                scr.fill(y, 0, per - (1 if per == 4 else 0), SIDEBAR_W, self.T("hl_bg"))
                scr.put(y, 0, "▌", self.T("accent"), bg)
            spark, line1, line2 = self.side_cache.get(i, ([], "", ""))
            num = "s" if i == len(self.pages) - 1 else "%d" % ((i + 1) % 10)
            scr.put(y, 1, num, self.T("accent") if active else self.T("dim"), bg)
            scr.put(y, 3, title, self.T("title") if active else self.T("fg"), bg, curses.A_BOLD)
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
            x += self.chip(y, x, " ⚡ I install tap ", "warn") + 2
        for k, label in keys:
            if x + len(k) + len(label) + 3 > w - 30:
                break
            x += scr.put(y, x, k, self.T("accent"), extra=curses.A_BOLD)
            x += scr.put(y, x, " %s  " % label, self.T("dim"))
        msg = self.flash or ("claudeMon v%s" % __version__)
        scr.put(y, w - len(msg) - 2, msg, self.T("info") if self.flash else self.T("border"))

    def draw_help(self, h, w):
        lines = [
            "claudeMon — a task manager for Claude Code",
            "",
            "1-9 0 s    jump to a page          ← → / Tab  previous / next page",
            "↑ ↓  j k   select a session        ⏎          inspect the selected session",
            "g / G      graph range 5m…24h      o          overall vs per-session (burn)",
            "e          model · effort split    a          include finished sessions",
            "t          next theme              u          update interval 1/2/5/10 s",
            "b          graph style: blocks · braille · dots · line · ascii",
            "r          refresh now             q / Esc    quit",
            "z          mini view: a small window with limits and sessions (z again restores the size)",
            "",
            "m          manual                  I I        install the tap (U U on Settings removes it)",
            "",
            "⚡ Limits, cost and alerts need the tap: press I twice, or run `claudemon install`.",
            "Everything else is read from ~/.claude transcripts. No tokens are used.",
        ]
        bw = min(w - 4, max(len(l) for l in lines) + 6)
        bh = len(lines) + 4
        y, x = (h - bh) // 2, (w - bw) // 2
        self.scr.fill(y, x, bh, bw, self.T("hl_bg"))
        self.scr.box(y, x, bh, bw, "Help", focus=True)
        for i, l in enumerate(lines):
            self.scr.put(y + 2 + i, x + 3, l, self.T("title") if i == 0 else self.T("fg"), self.T("hl_bg"))

    # ── mini view ──────────────────────────────────────────────────────────
    def resize(self, rows, cols):
        """Ask the terminal to resize its window (xterm CSI 8 t; Terminal and iTerm honour it)."""
        if not can_resize():
            return
        self.sized = (rows, cols)
        self.title("\033[8;%d;%dt" % (rows, cols))

    def set_mini(self, on):
        if on == self.mini:
            return
        if on:
            h, w = self.scr.size
            if h >= 16 and w >= 70:               # remember a real full-size window, not a tiny one
                self.full_size = (h, w)
            self.mini = True
            self.fit_mini()
        else:
            self.mini = False
            self.resize(*self.full_size)
        self.flash = "mini view: z for the full view" if on else ""

    def mini_rows(self):
        n = len(self.session_list())
        return 6 + max(1, min(n, MINI_MAX)) + (1 if n > MINI_MAX else 0)

    def fit_mini(self):
        """Keep the window just tall enough for the session list as sessions come and go."""
        want = (self.mini_rows(), MINI_W)
        if want != self.sized:
            self.resize(*want)

    def key_mini(self, key, k):
        d = 1 if (key == curses.KEY_DOWN or k == "j") else -1 if (key == curses.KEY_UP or k == "k") else 0
        if d:
            self.move(d)
        elif key in ("\n", "\r", curses.KEY_ENTER):
            self.page = self.idx("Inspect")
            self.set_mini(False)
        elif k is not None and len(k) == 1 and (k in DIGITS or k == "s"):   # a page key opens that page in the full view
            self.page = self.idx("Settings") if k == "s" else self.digit_page(k)
            self.set_mini(False)
        elif k == "t":
            i = (THEME_ORDER.index(self.scr.theme_name) + 1) % len(THEME_ORDER)
            self.scr.set_theme(THEME_ORDER[i])
            self.theme_cursor = i
            self.flash = "theme: " + THEME_ORDER[i]
        elif k == "b":
            self.style = STYLES[(STYLES.index(self.style) + 1) % len(STYLES)]
            self.scr.style = self.style
            self.flash = "graphs: " + self.style
        elif k == "a":
            self.show_all = not self.show_all
            self.flash = "all recent sessions" if self.show_all else "live sessions"
        elif k == "r":
            self.tick(force=True)
        elif k == "I":
            if self.tap_ok:
                self.flash = "tap is already installed"
            elif self.confirm("I", "⚡ I again installs the tap"):
                self.do_install()
        return True

    def mini_limit(self, y, w, key, label):
        scr = self.scr
        f = self.forecasts.get(key)
        weekly = key == "seven_day"
        scr.put(y, 1, label, self.T("dim"))
        gx, gw = 5, max(8, w - 33)
        if not f or f.pct is None:
            scr.gauge(y, gx, gw, 0)
            msg = "⚡ I I installs the tap" if not self.tap_ok else "not reported" if self.not_reported(key) else "waiting for data"
            scr.put(y, gx + gw + 2, msg, self.T("warn") if not self.tap_ok else self.T("dim"), maxw=w - gx - gw - 3)
            return
        frac = f.pct / 100
        scr.gauge(y, gx, gw, frac)
        x = gx + gw + 1
        x += scr.put(y, x, "%4d%%" % round(f.pct), scr.level_color(frac), extra=curses.A_BOLD)
        eta = f.eta(f.rate)
        if eta and not (f.resets and eta > f.resets):
            note, role = "full ≈ %s" % fclock(eta, weekly), "warn"
        elif f.resets:
            note, role = "resets %s" % fclock(f.resets, weekly), "dim"
        else:
            note, role = "flat", "dim"
        if f.stale:
            note += " · stale"
        scr.put(y, x + 2, note, self.T(role), maxw=w - x - 3)

    def draw_mini(self, h, w):
        scr = self.scr
        if h < 6 or w < 40:
            scr.put(0, 0, "mini needs 40×6 (z for the full view)", self.T("warn"))
            return
        now = time.time()
        live = self.store.live_sessions()
        bg = self.T("hl_bg")
        scr.fill(0, 0, 1, w, bg)
        x = scr.put(0, 1, "◆ ", self.T("accent"), bg, curses.A_BOLD) + 1
        x += scr.put(0, x, "claudeMon", self.T("title"), bg, curses.A_BOLD)
        clock = datetime.now().strftime("%H:%M:%S ")
        end = w - len(clock) - 3                      # header text stops short of the clock
        x += scr.put(0, x, "  %d live" % len(live), self.T("fg"), bg, maxw=end - x)
        counts = Counter(s.state(now) for s in live)
        for state in (NEEDS_YOU, WORKING, IDLE):
            text, role = STATE_BADGE[state]
            sym, word = text.split(" ", 1)
            item = "  %s %d %s" % (sym, counts[state], word.lower())
            if counts[state] and x + len(item) <= end:
                x += scr.put(0, x, item, self.T(role), bg, curses.A_BOLD if state == NEEDS_YOU else 0)
        dot = self.T("ok") if now - self.last_tick < self.interval + 2 else self.T("crit")
        scr.put(0, w - len(clock) - 2, "●", dot, bg)
        scr.put(0, w - len(clock), clock, self.T("dim"), bg)

        self.mini_limit(1, w, "five_hour", "5h")
        self.mini_limit(2, w, "seven_day", "7d")

        spark = self.store.series(1800, 30, lambda c: c.usage.total)
        burn = self.store.series(60, 1, lambda c: c.usage.total)[0]
        scr.put(3, 1, "burn", self.T("dim"))
        sw = max(8, min(30, w - 46))
        scr.spark(3, 6, spark, sw)
        x = 7 + sw
        x += scr.put(3, x, "%s/min" % ftok(burn), self.T("fg"), extra=curses.A_BOLD)
        warm = sum(1 for s in live if (s.t.cache_expires() or 0) > now)
        u = self.store.totals(now - 300)
        hit = u.cache_read / u.prompt if u.prompt else None
        scr.put(3, x, "   cache %d/%d warm · hit %s" % (warm, len(live), fpct(hit)), self.T("dim"), maxw=w - x - 1)

        scr.put(4, 0, "─" * w, self.T("border"))
        scr.put(4, 2, " Sessions ", self.T("title"), extra=curses.A_BOLD)

        sessions = self.session_list()
        sel = self.selected(sessions)
        room = max(1, h - 6)
        shown = sessions[:room] if len(sessions) <= room else sessions[:room - 1]
        if sel in sessions and sel not in shown:              # keep the selection on screen
            shown = shown[:-1] + [sel]
        y = 5
        if not sessions:
            scr.put(y, 2, "no live Claude Code sessions", self.T("dim"))
        nw = max(8, w - 50)                           # columns after the name: model 18, ctx 8, rate 9, doing 12
        for s in shown:
            focus = s is sel
            rbg = bg if focus else None
            if focus:
                scr.fill(y, 0, 1, w, bg)
                scr.put(y, 0, "▌", self.T("accent"), rbg)
            state = s.state(now)
            text, role = STATE_BADGE[state]
            scr.put(y, 1, text.split(" ", 1)[0], self.T(role), rbg, curses.A_BOLD)
            scr.put(y, 3, clip(s.name, nw - 1), self.T("title") if focus else self.T("fg"), rbg,
                    curses.A_BOLD if state == NEEDS_YOU or focus else 0)
            x = 3 + nw
            scr.put(y, x, clip("%s·%s" % (short_model(s.model), s.effort or "?"), 17), self.T("dim"), rbg)
            used, size = s.context()
            frac = used / size if size else 0
            scr.put(y, x + 18, "ctx", self.T("dim"), rbg)
            scr.put(y, x + 22, "%4s" % fpct(frac), scr.level_color(frac), rbg)
            rate = self.store.series(60, 1, lambda c: c.usage.total, [s])[0]
            scr.put(y, x + 26, "%8s" % (ftok(rate) + "/m"), self.T("fg"), rbg)
            pending = sorted(list(s.t.pending_tools.values()), key=lambda p: p[1] or 0)
            agents = sum(1 for a in list(s.agents.values()) if not a.finished)
            doing = pending[-1][0] if pending else ""
            if agents:
                doing = ("%s ◇%d" % (doing, agents)).strip()
            n_loops = len(s.loops())
            if n_loops:
                doing = ("%s ⟲%d" % (doing, n_loops)).strip()
            scr.put(y, x + 36, clip(doing, w - x - 37), self.T("crit") if n_loops else self.T("info"), rbg)
            y += 1
        if len(sessions) > len(shown):
            scr.put(y, 3, "+%d more (z for the full view)" % (len(sessions) - len(shown)), self.T("dim"))

        fy = h - 1
        msg = self.flash or ("" if self.tap_ok else "⚡ tap off: I I")
        x = 1
        for key, label in (("z", "full"), ("q", "quit"), ("↑↓", "select"), ("⏎", "inspect"), ("1-0", "page"), ("t", "theme")):
            if x + len(key) + len(label) + 3 > w - len(msg) - 2:
                break
            x += scr.put(fy, x, key, self.T("accent"), extra=curses.A_BOLD)
            x += scr.put(fy, x, " %s  " % label, self.T("dim"))
        if msg:
            scr.put(fy, w - len(msg) - 2, msg, self.T("info") if self.flash else self.T("warn"))

    # ── tap prompt, manual, install ────────────────────────────────────────
    def idx(self, title):
        return next(i for i, p in enumerate(self.pages) if p[0] == title)

    def chip(self, y, x, text, role="warn"):
        """A reverse-video button-like label; returns its width."""
        dark = self.T("bg") if self.T("bg") >= 0 else 16
        return self.scr.put(y, x, text, dark, self.T(role), curses.A_BOLD)

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

    def key_prompt(self, key, k):
        if k in ("i", "I", "\n", "\r") or key == curses.KEY_ENTER:
            self.do_install()
        else:
            self.flash = "tap skipped: press I any time to install it"
        self.modal = None
        return True

    def key_manual(self, key, k):
        n = len(manual.TOPICS)
        if k in ("q", "Q", "m", "M", "\x1b", "?"):
            self.modal = None
        elif key in (curses.KEY_DOWN, curses.KEY_RIGHT) or k in ("j", "l", "\t"):
            self.man_i, self.man_scroll = (self.man_i + 1) % n, 0
        elif key in (curses.KEY_UP, curses.KEY_LEFT, curses.KEY_BTAB) or k in ("k", "h"):
            self.man_i, self.man_scroll = (self.man_i - 1) % n, 0
        elif key == curses.KEY_NPAGE or k == " ":
            self.man_scroll += 8
        elif key == curses.KEY_PPAGE:
            self.man_scroll = max(0, self.man_scroll - 8)
        elif k == "g":
            self.man_scroll = 0
        elif k == "I":
            if self.confirm("I", "⚡ press I again to install the tap (settings.json is backed up first)"):
                self.do_install()
        return True

    def manual_lines(self, topic, width):
        out = []
        kw = min(28, max([len(e[2:].partition(" | ")[0]) for e in topic["body"] if e.startswith("> ")] + [6]) + 2)
        for e in topic["body"]:
            if e.startswith("# "):
                if out:
                    out.append(("blank", "", ""))
                out.append(("h", e[2:], ""))
            elif e.startswith("- "):
                for i, ln in enumerate(textwrap.wrap(e[2:], max(10, width - 2)) or [""]):
                    out.append(("b", ("• " if i == 0 else "  ") + ln, ""))
            elif e.startswith("! "):
                out.append(("blank", "", ""))
                for ln in textwrap.wrap(e[2:], max(10, width - 4)):
                    out.append(("c", " " + ln.ljust(width - 2), ""))
                out.append(("blank", "", ""))
            elif e.startswith("> "):
                k, _, t = e[2:].partition(" | ")
                for i, ln in enumerate(textwrap.wrap(t, max(10, width - kw - 2)) or [""]):
                    out.append(("k", k if i == 0 else "", ln, kw))
            elif e == "":
                out.append(("blank", "", ""))
            else:
                if out and out[-1][0] not in ("blank", "h"):
                    out.append(("blank", "", ""))
                for ln in textwrap.wrap(e, max(10, width)):
                    out.append(("p", ln, ""))
        return out

    def draw_manual(self, h, w):
        scr = self.scr
        bw, bh = w, h - 2
        x0, y0 = 0, 1
        scr.fill(y0, x0, bh, bw, self.T("hl_bg"))
        scr.box(y0, x0, bh, bw, "Manual", "m / Esc close", focus=True)
        lw = 24
        for i, t in enumerate(manual.TOPICS):
            ry = y0 + 2 + i
            if ry >= y0 + bh - 4:
                break
            cur = i == self.man_i
            tap = t["id"] == "tap"
            role = "warn" if tap else ("title" if cur else "fg")
            if cur:
                scr.put(ry, x0 + 1, "▌", self.T("accent"), self.T("hl_bg"))
            scr.put(ry, x0 + 3, clip(t["title"], lw - 4), self.T(role), self.T("hl_bg"), curses.A_BOLD if cur or tap else 0)
        if not self.tap_ok:
            self.chip(y0 + bh - 3, x0 + 2, " ⚡ I  Install tap ", "warn")
        else:
            scr.put(y0 + bh - 3, x0 + 2, "✓ tap installed", self.T("ok"), self.T("hl_bg"))
        for row in range(y0 + 1, y0 + bh - 1):
            scr.put(row, x0 + lw, "│", self.T("border"), self.T("hl_bg"))
        cx, cw = x0 + lw + 2, bw - lw - 4
        lines = self.manual_lines(manual.TOPICS[self.man_i], cw)
        inner = bh - 4
        self.man_scroll = max(0, min(self.man_scroll, max(0, len(lines) - inner)))
        for i, line in enumerate(lines[self.man_scroll:self.man_scroll + inner]):
            style, a, b = line[:3]
            ry = y0 + 2 + i
            bg = self.T("hl_bg")
            if style == "h":
                scr.put(ry, cx, a, self.T("title"), bg, curses.A_BOLD)
            elif style == "c":
                self.scr.put(ry, cx, a, self.T("bg") if self.T("bg") >= 0 else 16, self.T("warn"), curses.A_BOLD)
            elif style == "k":
                scr.put(ry, cx, a, self.T("accent"), bg, curses.A_BOLD)
                scr.put(ry, cx + (line[3] if len(line) > 3 else 18), b, self.T("fg"), bg)
            elif style == "b":
                scr.put(ry, cx, a, self.T("fg"), bg)
            elif style == "p":
                scr.put(ry, cx, a, self.T("fg"), bg)
        if len(lines) > inner:
            pct = int(100 * (self.man_scroll + inner) / len(lines))
            scr.put(y0 + bh - 2, x0 + bw - 12, "more %3d%%" % min(100, pct), self.T("dim"), self.T("hl_bg"))
        scr.put(y0 + bh - 2, cx, "↑↓ topic   PgUp/PgDn scroll   I install tap   Esc close", self.T("dim"), self.T("hl_bg"))

    def draw_prompt(self, h, w):
        scr = self.scr
        bw = min(w - 6, 78)
        text = [
            ("p", "Limits, session cost and exact context size come from Claude Code’s status line, and "
                  "permission prompts from its Notification hook. The claudeMon tap listens there. Without it "
                  "those panels stay empty and ‘Needs you’ is a best guess; everything else works already."),
            ("p", ""),
            ("h", "What installing does"),
            ("b", "• wraps your status line: it still prints exactly as before"),
            ("b", "• adds a Notification hook that records permission prompts"),
            ("b", "• copies tap.py to ~/.claude/claudemon/, so moving this folder is safe"),
            ("b", "• backs up settings.json first; `claudemon uninstall` reverses everything"),
            ("p", ""),
        ]
        lines = []
        for style, t in text:
            for ln in (textwrap.wrap(t, bw - 8) or [""]):
                lines.append((style, ln))
        bh = len(lines) + 7
        y, x = max(1, (h - bh) // 2), (w - bw) // 2
        scr.fill(y, x, bh, bw, self.T("hl_bg"))
        scr.box(y, x, bh, bw, "⚡ Welcome to claudeMon: install the tap?", focus=True, title_fg=self.T("warn"))
        for i, (style, ln) in enumerate(lines):
            scr.put(y + 2 + i, x + 3, ln, self.T("title") if style == "h" else self.T("fg"), self.T("hl_bg"),
                    curses.A_BOLD if style == "h" else 0)
        by = y + bh - 3
        cx = x + 3
        cx += self.chip(by, cx, "  I / ⏎  Install now  ", "ok") + 3
        cx += self.chip(by, cx, "  L  Later  ", "dim") + 3
        scr.put(by + 1, x + 3, "Later is fine: the ⚡ chip in the header stays until you install (I).", self.T("dim"), self.T("hl_bg"))

    def tap_callout(self, y, x, h, w, what):
        """A large, hard-to-miss panel shown where a page needs the tap."""
        scr = self.scr
        scr.box(y, x, h, w, "⚡ %s needs the claudeMon tap" % what, focus=True, title_fg=self.T("warn"))
        if self.tap_ok:
            lines = ["The tap is installed. Waiting for the next status-line refresh.",
                     "Send a message in any Claude Code session and data appears within seconds.",
                     "", "Limits are only reported on Pro, Max, Team and Enterprise logins."]
            for i, ln in enumerate(lines):
                scr.put(y + 2 + i, x + 3, ln, self.T("fg"))
            return
        lines = ["Claude Code reports account limits only through its status line.",
                 "The tap records each status-line refresh and still prints your status line unchanged.",
                 "Your settings.json is backed up first, and `claudemon uninstall` restores it exactly."]
        for i, ln in enumerate(lines):
            scr.put(y + 2 + i, x + 3, ln, self.T("fg"))
        self.chip(y + 6, x + 3, "  I I  Install the tap  ", "warn")
        scr.put(y + 6, x + 31, "press I twice to confirm", self.T("dim"))
        scr.put(y + 8, x + 3, "More in the manual: press m.", self.T("dim"))

    # ── page: tasks ────────────────────────────────────────────────────────
    def task_sel_idxs(self):
        return [i for i, r in enumerate(self.task_rows) if r.kind != "header"]

    def task_move(self, d):
        idxs = self.task_sel_idxs()
        if not idxs:
            return
        pos = idxs.index(self.task_i) if self.task_i in idxs else 0
        self.task_i = idxs[(pos + d) % len(idxs)]
        r = self.task_rows[self.task_i]
        self.task_key = (r.depth, r.kind, r.text)

    def task_open(self):
        if not self.task_rows or self.task_i >= len(self.task_rows):
            return
        r = self.task_rows[self.task_i]
        s = r.obj if r.kind == "session" else (r.obj[0] if r.kind in ("agent", "bg", "queued") else None)
        if s is not None:
            self.sel_sid = s.sid
            self.page = self.idx("Inspect")

    def task_detail(self, r, width):
        """Detail lines for a Tasks row: [(label, text, role)]."""
        now = time.time()
        L = []

        def kv(k, v, role="fg"):
            L.append((k, str(v), role))

        def para(text, role="fg", label=""):
            for i, ln in enumerate(textwrap.wrap(" ".join(str(text).split()), max(10, width)) or [""]):
                L.append((label if i == 0 else "", ln, role))

        if r.kind == "session":
            s = r.obj
            used, size = s.context()
            t = s.t.totals()
            kv("Session", s.name, "title")
            kv("State", s.state(now), STATE_ROLE_TUI.get(s.state(now), "dim"))
            kv("PID", (s.live or {}).get("pid", "—"))
            kv("Folder", (s.live or {}).get("cwd") or s.t.cwd or "—")
            kv("Model", "%s · %s" % (short_model(s.model), s.effort or "?"))
            kv("Mode", s.t.permission_mode or "—")
            kv("Context", "%s of %s  (%s)" % (ftok(used), ftok(size), fpct(used / size)))
            kv("Tokens", "%s total · %s out" % (ftok(t.total), ftok(t.output)))
            kv("Running", fdur((s.t.last_ts or now) - (s.t.started or now)))
            kv("Subagents", "%d live of %d" % (sum(1 for a in list(s.agents.values()) if not a.finished), len(s.agents)))
            if s.t.last_prompt:
                para(s.t.last_prompt, "dim", "Last prompt")
            for tid, (name, ts, summ) in list(s.t.pending_tools.items()):
                para("%s %s" % (name, summ), "warn", "Waiting on")
        elif r.kind == "tool":
            o = r.obj
            kv("Tool", o["name"], "title")
            kv("Running", fdur(now - o["ts"]) if o["ts"] else "—", "warn" if o["slow"] else "fg")
            if o["slow"]:
                para("Waiting longer than a quick tool should. It may be sitting on a permission prompt for you.", "warn")
            para(o["summary"], "fg", "Detail")
        elif r.kind == "agent":
            s, a = r.obj
            u = a.t.totals()
            kv("Subagent", a.label, "title")
            kv("Type", a.meta.get("agentType", "—"))
            kv("Model", "%s · %s" % (short_model(a.t.model), a.t.effort or "?"))
            kv("Running", fdur(now - (a.t.started or now)))
            kv("Output", ftok(u.output))
            kv("Rate", "%s tok/min" % ftok(a.t.totals(now - 300).total / 5))
            kv("Parent", s.name)
            kv("Agent id", a.id)
            for name, n in a.t.tools.most_common(4):
                kv("Tool use", "%s ×%d" % (name, n), "dim")
            for tid, (name, ts, summ) in list(a.t.pending_tools.items()):
                para("%s %s" % (name, summ), "warn", "Waiting on")
        elif r.kind == "bg":
            s, b = r.obj
            kv("Task", b.id, "title")
            kv("Tool", b.tool)
            kv("Status", b.status, "ok" if b.running else ("dim" if b.status == "completed" else "crit"))
            if b.started:
                kv("Started", fclock(b.started) + "  (%s ago)" % fdur(now - b.started))
            if b.ended:
                kv("Ended", fclock(b.ended))
            kv("Session", s.name)
            if b.summary:
                para(b.summary, "fg", "Command")
            if b.result:
                para(b.result, "dim", "Result")
            tail_lines = tasks_mod.tail(b.output) if b.output else None
            if tail_lines:
                L.append(("Output", "(last lines)", "dim"))
                for ln in tail_lines[-14:]:
                    L.append(("", clip(ln, width), "fg"))
            elif b.output:
                L.append(("Output", "file not readable (already cleaned up?)", "dim"))
        elif r.kind in ("proc", "cli"):
            p = r.obj
            kv("Process", p.pid, "title")
            kv("Parent", p.ppid)
            kv("Running", fdur(p.elapsed))
            kv("CPU", "%.1f%%" % p.cpu)
            kv("Memory", tasks_mod.fmem(p.rss))
            kv("Kind", p.kind)
            para(p.args, "fg", "Command")
        elif r.kind == "mcp":
            kv("MCP servers", len(r.obj), "title")
            for p in r.obj:
                para("pid %d  %s  %s" % (p.pid, tasks_mod.fmem(p.rss), p.label), "fg")
            para("MCP servers give Claude extra tools. They idle at near-zero CPU, but each stays in memory "
                 "while its session lives.", "dim")
        elif r.kind == "queued":
            s, ts, text = r.obj
            kv("Queued", fdur(now - ts) + " ago" if ts else "—", "warn")
            kv("Session", s.name)
            para(text, "fg", "Prompt")
            para("You typed this while Claude was busy. It is delivered when the current turn allows.", "dim")
        elif r.kind == "desktop":
            main, n, rss, cpu = r.obj
            kv("Claude Desktop", "%d processes" % n, "title")
            kv("Memory", tasks_mod.fmem(rss))
            kv("CPU", "%.1f%%" % cpu)
            kv("Running", fdur(main.elapsed))
            para("Desktop and Cowork sessions are not read directly. Their usage shows up in the account "
                 "limits when the tap is installed.", "dim")
        elif r.kind == "job":
            jid, st = r.obj
            kv("Job", st.get("name") or jid, "title")
            kv("State", st.get("state", "?"), "warn" if st.get("state") == "blocked" else "fg")
            kv("Tempo", st.get("tempo", "—"))
            kv("Tokens", ftok(st.get("tokens") or 0))
            kv("Folder", st.get("cwd", "—"))
            if st.get("intent"):
                para(st["intent"], "fg", "Intent")
            if st.get("detail"):
                para(st["detail"], "dim", "Latest")
            if st.get("needs"):
                para(st["needs"], "warn", "Needs you")
            if st.get("suggestedReply"):
                para(st["suggestedReply"], "info", "Suggested")
        elif r.kind == "sched":
            name, desc = r.obj
            kv("Scheduled task", name, "title")
            para(desc or "—", "fg", "What")
            para("Defined in ~/.claude/scheduled-tasks/%s/SKILL.md. Claude runs it on its schedule." % name, "dim")
        else:
            L.append(("", "Select a row with ↑ ↓", "dim"))
        return L

    def page_tasks(self, y, x, h, w):
        scr = self.scr
        c = self.task_counts
        scr.put(y, x + 1, "Tasks", self.T("title"), extra=curses.A_BOLD)
        scr.put(y, x + 9, "%d sessions · %d tools running · %d agents · %d background · %d processes · %d queued" % (
            c["sessions"], c["tools"], c["agents"], c["bg"], c["procs"], c["queued"]), self.T("dim"))
        lw = max(50, w * 58 // 100)
        rw = w - lw
        bh = h - 1
        scr.box(y + 1, x, bh, lw, "Running now", "↑↓ select · ⏎ inspect", focus=True)
        rows = self.task_rows
        inner = bh - 2
        if self.task_i >= len(rows) or (rows and rows[self.task_i].kind == "header"):
            idxs = self.task_sel_idxs()
            self.task_i = idxs[0] if idxs else 0
        if self.task_i < self.task_top:
            self.task_top = self.task_i
        elif self.task_i >= self.task_top + inner:
            self.task_top = self.task_i - inner + 1
        self.task_top = max(0, min(self.task_top, max(0, len(rows) - inner)))
        for n, r in enumerate(rows[self.task_top:self.task_top + inner]):
            ry = y + 2 + n
            sel = (self.task_top + n) == self.task_i
            bg = self.T("hl_bg") if sel else None
            if bg is not None:
                scr.fill(ry, x + 1, 1, lw - 2, bg)
            if r.kind == "header":
                scr.put(ry, x + 2, "── %s " % r.text + "─" * max(0, lw - 8 - len(r.text)), self.T("accent"), bg, curses.A_BOLD)
                continue
            ind = 2 + 2 * r.depth
            right = r.right
            scr.put(ry, x + ind, r.icon, self.T(r.role), bg, curses.A_BOLD)
            room = lw - ind - 4 - (len(right) + 2 if right else 0)
            scr.put(ry, x + ind + 2, clip(r.text, room), self.T(r.role), bg, curses.A_BOLD if r.kind == "session" else 0)
            if right:
                scr.put(ry, x + lw - 2 - len(right), right, self.T(r.right_role), bg)
        if not rows:
            scr.put(y + 3, x + 3, "Nothing running.", self.T("dim"))
        scr.box(y + 1, x + lw, bh, rw, "Details")
        if rows and self.task_i < len(rows):
            for n, (label, text, role) in enumerate(self.task_detail(rows[self.task_i], rw - 18)[:inner]):
                ry = y + 2 + n
                scr.put(ry, x + lw + 2, label, self.T("dim"), maxw=14)
                scr.put(ry, x + lw + 16, clip(text, rw - 18), self.T(role))

    def side_tasks(self):
        c = self.task_counts
        return [], "%d tools · %d agents" % (c["tools"], c["agents"]), "%d bg · %d queued" % (c["bg"], c["queued"])

    # ── sidebar summaries: (spark values, line 1, line 2) ──────────────────
    def side_burn(self):
        s = self.store.series(1800, 30, lambda c: c.usage.total)
        live = self.store.live_sessions()
        return s, "%d sessions" % len(live), "%s tok/min" % ftok(s[-1] if s else 0)

    def side_context(self):
        fr = [s.context()[0] / s.context()[1] for s in self.store.live_sessions() if s.context()[0]]
        if not fr:
            return [], "no live context", ""
        return [f * 100 for f in fr], "fullest %s" % fpct(max(fr)), "average %s" % fpct(sum(fr) / len(fr))

    def side_cache_(self):
        now = time.time()
        live = self.store.live_sessions()
        warm = sum(1 for s in live if (s.t.cache_expires() or 0) > now)
        u = self.store.totals(now - 300)
        hit = u.cache_read / u.prompt if u.prompt else None
        sp = self.store.series(1800, 30, lambda c: c.usage.cache_read / c.usage.prompt * 100 if c.usage.prompt else 0)
        return sp, "%d of %d warm" % (warm, len(live)), "hit %s" % fpct(hit)

    def side_traffic(self):
        out = self.store.series(1800, 30, lambda c: c.usage.output)
        inn = self.store.series(1800, 30, lambda c: c.usage.input + c.usage.cache_write)
        return out, "out %s/m" % ftok(out[-1]), "in %s/m" % ftok(inn[-1])

    def side_models(self):
        c = Counter()
        for _, call, _ in self.store.calls(time.time() - 3600):
            c[short_model(call.model)] += call.usage.output
        if not c:
            return [], "no calls in 1h", ""
        top, n = c.most_common(1)[0]
        return self.store.series(1800, 30, lambda c: c.usage.output), "%d models" % len(c), "%s %s" % (top, fpct(n / sum(c.values())))

    def not_reported(self, key):
        """True when the tap works but Claude Code reports no such window for this account
        (some plans report only the weekly limit), so waiting longer will not help."""
        return self.tap_ok and any(f and f.pct is not None for k, f in self.forecasts.items() if k != key)

    def side_limit(self, key):
        f = self.forecasts.get(key)
        if not f or f.pct is None:
            if self.not_reported(key):
                return [], "n/a", "not reported"
            return [], "no data", "⚡ install tap" if not self.tap_ok else "waiting for data"
        pts = [p for _, p in f.points][-30:]
        eta = f.eta(f.rate)
        if eta and f.resets and eta > f.resets:
            line = "resets first"
        else:
            line = "full %s" % fclock(eta, key == "seven_day") if eta else "flat"
        return pts, "%d%%" % round(f.pct), line

    def side_projects(self):
        c = Counter()
        for s, call, _ in self.store.calls(time.time() - 7 * 86400):
            c[s.project] += weight(call.usage)
        if not c:
            return [], "no projects", ""
        top, n = c.most_common(1)[0]
        return [], "%s ≈ %s" % (top, fpct(n / sum(c.values()))), "%d projects (7d)" % len(c)

    def side_inspect(self):
        s = self.selected()
        if not s:
            return [], "no session", ""
        n_loops = len(s.loops())
        return (self.store.series(1800, 30, lambda c: c.usage.output, [s]), clip(s.name, 12),
                "%d agents · %d loops" % (len(s.agents), n_loops))

    def side_settings(self):
        return [], "theme %s" % self.scr.theme_name, "tap %s" % ("on" if install.installed() else "off")

    # ── page 1: token burn ─────────────────────────────────────────────────
    def page_burn(self, y, x, h, w):
        scr = self.scr
        scr.put(y, x + 1, "Token burn", self.T("title"), extra=curses.A_BOLD)
        tx = x + 14
        tx += self.span_toggle(y, tx)
        tx_end = tx + self.toggles(y, tx, "Show", ["Sessions", "Overall"], 1 if self.overall else 0, "o")
        sessions = self.session_list()
        now = time.time()
        summary_h = 7
        gy, gh = y + 1, h - summary_h - 1
        if self.overall or not sessions:
            scr.box(gy, x, gh, w, "All sessions · tokens / min", "output overlay")
            n = self.nbuckets(w - 2)
            tot = self.per_min(self.store.series(self.span, n, lambda c: c.usage.total))
            out = self.per_min(self.store.series(self.span, n, lambda c: c.usage.output))
            top = self.chart(gy + 1, x + 1, gh - 2, w - 2, tot)
            if top:
                cv = Canvas(w - 2, gh - 2)
                vmax = max(out) or 1
                prev = None
                for px in range(cv.w):
                    v = out[min(len(out) - 1, px * len(out) // cv.w)]
                    py = int(v / vmax * (cv.h - 1))
                    if prev is not None:
                        cv.line(px - 1, prev, px, py, self.T("info"))
                    prev = py
                cv.render(scr, gy + 1, x + 1)
        else:
            cols = max(1, min(len(sessions), w // 36))
            rows = -(-len(sessions) // cols)
            ph = max(6, gh // max(1, rows))
            visible_rows = max(1, gh // ph)
            sel = self.selected(sessions)
            first_row = max(0, self.sel // cols - visible_rows + 1)
            pw = w // cols
            n = self.nbuckets(pw - 2)
            series = {s.sid: self.per_min(self.store.series(self.span, n, lambda c: c.usage.total, [s])) for s in sessions}
            vmax = max([max(v) for v in series.values()] + [1])
            for idx, s in enumerate(sessions):
                r, c = divmod(idx, cols)
                r -= first_row
                if r < 0 or r >= visible_rows:
                    continue
                py, px = gy + r * ph, x + c * pw
                state = s.state(now)
                focus = sel is s
                text, role = STATE_BADGE[state]
                scr.box(py, px, ph, pw - 1, clip(s.name, pw - 20), focus=focus)
                scr.put(py, px + pw - 3 - len(text), text, self.T(role), extra=curses.A_BOLD if state == NEEDS_YOU else 0)
                self.chart(py + 1, px + 1, ph - 3, pw - 3, series[s.sid], vmax=vmax, scale_fmt=None)
                used, size = s.context()
                info = "%s · %s  ctx %s  %s/m" % (short_model(s.model), s.effort or "?", fpct(used / size), ftok(series[s.sid][-1] if series[s.sid] else 0))
                loops = s.loops()
                scr.put(py + ph - 2, px + 2, clip(info, pw - 6), self.T("dim"))
                if loops:
                    tag = " ⟲%d " % len(loops)
                    scr.put(py + ph - 2, px + pw - 3 - len(tag), tag, self.T("bg") if self.T("bg") >= 0 else 16, self.T("crit"), curses.A_BOLD)
            if x + w - 12 > tx_end:                      # not on top of the toggles in a narrow window
                scr.put(gy - 1, x + w - 12, "max %s/m" % ftok(vmax), self.T("dim"))

        # summary
        sy = y + h - summary_h
        scr.box(sy, x, summary_h, w, "Now")
        burn = self.store.series(60, 1, lambda c: c.usage.total)[0]
        outn = self.store.series(60, 1, lambda c: c.usage.output)[0]
        live = self.store.live_sessions()
        groups = defaultdict(list)
        for s in live:
            groups[s.state(now)].append(s.name)
        loops = sum(len(s.loops()) for s in live)
        cells = [("Burn now", ftok(burn) + "/min", None), ("Output now", ftok(outn) + "/min", None),
                 ("Working", str(len(groups[WORKING])), self.T("ok")), ("Needs you", str(len(groups[NEEDS_YOU])), self.T("warn") if groups[NEEDS_YOU] else None),
                 ("Idle", str(len(groups[IDLE])), self.T("dim")), ("Loops", str(loops), self.T("crit") if loops else None)]
        cw = max(12, (w - 4) // len(cells))
        for i, (lab, val, col) in enumerate(cells):
            self.kv(sy + 1, x + 2 + i * cw, lab, val, col, cw - 1)
        ly = sy + 3
        for state in (WORKING, NEEDS_YOU, IDLE):
            text, role = STATE_BADGE[state]
            scr.put(ly, x + 2, text.split(" ", 1)[1], self.T(role))
            scr.put(ly, x + 14, clip(" · ".join(groups[state]) or "—", w - 17), self.T("fg"))
            ly += 1

    # ── page 2: context ────────────────────────────────────────────────────
    def page_context(self, y, x, h, w):
        scr = self.scr
        scr.put(y, x + 1, "Context", self.T("title"), extra=curses.A_BOLD)
        self.span_toggle(y, x + 11)
        sessions = self.session_list()
        sel = self.selected(sessions)
        scr.box(y + 1, x, h - 1, w, "Context window per session", "used / window")
        hdr = y + 2
        cols = [("Session", 22), ("Model", 11), ("Window", 0), ("Used", 15), ("Compact", 8), ("History", 22)]
        gauge_w = max(10, w - 4 - sum(c[1] for c in cols) - len(cols))
        cx = x + 2
        for name, cw in cols:
            scr.put(hdr, cx, name, self.T("dim"), extra=curses.A_UNDERLINE)
            cx += (cw or gauge_w) + 1
        row = hdr + 1
        for s in sessions:
            if row >= y + h - 1:
                break
            used, size = s.context()
            frac = used / size if size else 0
            bg = self.T("hl_bg") if s is sel else None
            if bg is not None:
                scr.fill(row, x + 1, 1, w - 2, bg)
            cx = x + 2
            scr.put(row, cx, clip(s.name, 21), self.T("fg"), bg)
            cx += 23
            scr.put(row, cx, short_model(s.model), self.T("dim"), bg)
            cx += 12
            scr.gauge(row, cx, gauge_w, frac, color=None)
            cx += gauge_w + 1
            scr.put(row, cx, "%s %s" % (fpct(frac).rjust(4), ftok(used) + "/" + ftok(size)), scr.level_color(frac), bg)
            cx += 16
            scr.put(row, cx, str(s.t.compactions).rjust(5), self.T("warn") if s.t.compactions else self.T("dim"), bg)
            cx += 9
            # the largest prompt per bucket: summing would overstate context size
            ctx = [0.0] * 22
            t0 = time.time() - self.span
            for c, a in s.all_calls(t0):
                if a is None:
                    i = min(21, int((c.ts - t0) / (self.span / 22)))
                    ctx[i] = max(ctx[i], c.usage.prompt)
            scr.spark(row, cx, ctx, 22, vmax=size)
            row += 1
        if sel and row + 6 < y + h - 1:
            row += 1
            ch = y + h - 2 - row
            scr.put(row, x + 2, "%s · context size per call" % sel.name, self.T("title"))
            calls = sorted((c for c, a in sel.all_calls(time.time() - self.span) if a is None), key=lambda c: c.ts)
            vals = [c.usage.prompt for c in calls]
            self.chart(row + 1, x + 2, ch - 1, w - 4, vals, vmax=sel.context()[1])

    # ── page 3: prompt cache ───────────────────────────────────────────────
    def page_cache(self, y, x, h, w):
        scr = self.scr
        now = time.time()
        scr.put(y, x + 1, "Prompt cache", self.T("title"), extra=curses.A_BOLD)
        self.span_toggle(y, x + 16)
        sessions = self.session_list()
        table_h = min(len(sessions) + 3, max(5, h // 3))
        chart_h = max(4, (h - table_h - 5) * 2 // 3)
        writes_h = max(4, h - table_h - 5 - chart_h)
        n = self.nbuckets(w - 2)
        reads = self.store.series(self.span, n, lambda c: c.usage.cache_read)
        prompts = self.store.series(self.span, n, lambda c: c.usage.prompt)
        ratio = [r / p if p else 0 for r, p in zip(reads, prompts)]
        # carry the last ratio across empty buckets so the line does not drop to zero
        last = 0
        for i, (r, p) in enumerate(zip(ratio, prompts)):
            if p:
                last = r
            else:
                ratio[i] = last
        scr.box(y + 1, x, chart_h, w, "Hit ratio", "100%")
        self.chart(y + 2, x + 1, chart_h - 2, w - 2, ratio, vmax=1.0, scale_fmt=None)
        wy = y + 1 + chart_h
        scr.box(wy, x, writes_h, w, "Cache writes per minute")
        self.chart(wy + 1, x + 1, writes_h - 2, w - 2, self.per_min(self.store.series(self.span, n, lambda c: c.usage.cache_write)), color=self.T("info"))
        sy = wy + writes_h
        u5 = self.store.totals(now - 300)
        live = self.store.live_sessions()
        warm = sum(1 for s in live if (s.t.cache_expires() or 0) > now)
        misses = sum(1 for _, c, _ in self.store.calls(now - 300) if c.usage.prompt > MISS_FLOOR and c.usage.cache_read < 0.1 * c.usage.prompt)
        cells = [("Hit ratio", fpct(u5.cache_read / u5.prompt) if u5.prompt else "—"), ("Warm", "%d of %d" % (warm, len(live))),
                 ("Reads now", ftok(u5.cache_read / 5) + "/min"), ("Writes now", ftok(u5.cache_write / 5) + "/min"), ("Misses, 5 min", str(misses))]
        cw = (w - 4) // len(cells)
        for i, (lab, val) in enumerate(cells):
            self.kv(sy, x + 2 + i * cw, lab, val, w=cw - 1)
        ty = sy + 2
        scr.box(ty, x, h - (ty - y), w, "Sessions")
        bar_w = max(8, w - 82)
        heads = [("Session", 24), ("Cache", 8), ("Expires", 8), ("Time left", bar_w), ("Hit", 5), ("Miss", 5), ("Re-cache if cold", 17)]
        cx = x + 2
        for name, cw_ in heads:
            scr.put(ty + 1, cx, name, self.T("dim"), extra=curses.A_UNDERLINE)
            cx += cw_ + 1
        sel = self.selected(sessions)
        row = ty + 2
        for s in sessions:
            if row >= y + h - 1:
                break
            exp = s.t.cache_expires()
            left = (exp - now) if exp else None
            is_warm = left is not None and left > 0
            calls = [c for c, a in s.all_calls(0) if a is None]
            tot_p = sum(c.usage.prompt for c in calls)
            hit = sum(c.usage.cache_read for c in calls) / tot_p if tot_p else None
            miss = sum(1 for c in calls if c.usage.prompt > MISS_FLOOR and c.usage.cache_read < 0.1 * c.usage.prompt)
            bg = self.T("hl_bg") if s is sel else None
            if bg is not None:
                scr.fill(row, x + 1, 1, w - 2, bg)
            cx = x + 2
            scr.put(row, cx, clip(s.name, 23), self.T("fg"), bg)
            cx += 25
            scr.put(row, cx, "● Warm" if is_warm else "○ Cold", self.T("ok") if is_warm else self.T("dim"), bg)
            cx += 9
            scr.put(row, cx, fdur(left) if is_warm else "—", self.T("fg"), bg)
            cx += 9
            frac = (left / s.t.cache_ttl) if is_warm else 0
            scr.gauge(row, cx, bar_w, frac, color=scr.level_color(1 - frac) if is_warm else self.T("border"))
            cx += bar_w + 1
            scr.put(row, cx, fpct(hit).rjust(4), self.T("fg"), bg)
            cx += 6
            scr.put(row, cx, str(miss).rjust(4), self.T("warn") if miss else self.T("dim"), bg)
            cx += 6
            scr.put(row, cx, ftok(s.context()[0]).rjust(8) + ("  1h TTL" if s.t.cache_ttl == 3600 else "  5m TTL"), self.T("dim"), bg)
            row += 1

    # ── page 4: traffic ────────────────────────────────────────────────────
    def page_traffic(self, y, x, h, w):
        scr = self.scr
        scr.put(y, x + 1, "Traffic", self.T("title"), extra=curses.A_BOLD)
        self.span_toggle(y, x + 11)
        n = self.nbuckets(w - 2)
        panes = [
            ("Tokens out / min", lambda c: c.usage.output, self.T("accent")),
            ("Fresh input / min  (uncached + cache writes)", lambda c: c.usage.input + c.usage.cache_write, self.T("info")),
            ("Cache reads / min", lambda c: c.usage.cache_read, self.T("ok")),
        ]
        ph = (h - 5) // len(panes)
        for i, (title, fn, col) in enumerate(panes):
            py = y + 1 + i * ph
            vals = self.per_min(self.store.series(self.span, n, fn))
            scr.box(py, x, ph, w, title, "now %s/m" % ftok(vals[-1] if vals else 0))
            self.chart(py + 1, x + 1, ph - 2, w - 2, vals, color=None if i == 0 else col)
        u = self.store.totals(time.time() - self.span)
        sy = y + 1 + len(panes) * ph
        scr.box(sy, x, h - (sy - y), w, "Totals · last %s" % SPANS[self.span_i][1])
        cells = [("Output", ftok(u.output)), ("Thinking", ftok(u.thinking)), ("Thinking share", fpct(u.thinking / u.output) if u.output else "—"),
                 ("Uncached in", ftok(u.input)), ("Cache writes", ftok(u.cache_write)), ("Cache reads", ftok(u.cache_read))]
        cw = (w - 4) // len(cells)
        for i, (lab, val) in enumerate(cells):
            self.kv(sy + 1, x + 2 + i * cw, lab, val, w=cw - 1)

    # ── page 5: models ─────────────────────────────────────────────────────
    def page_models(self, y, x, h, w):
        scr = self.scr
        now = time.time()
        scr.put(y, x + 1, "Models", self.T("title"), extra=curses.A_BOLD)
        tx = x + 10 + self.span_toggle(y, x + 10)
        self.toggles(y, tx, "Show", ["Model", "Model · effort"], 1 if self.by_effort else 0, "e")
        key = (lambda c: "%s · %s" % (short_model(c.model), c.effort or "?")) if self.by_effort else (lambda c: short_model(c.model))
        out = Counter()
        effort = defaultdict(Counter)
        users = defaultdict(Counter)
        think = Counter()
        for s, c, a in self.store.calls(now - self.span):
            k = key(c)
            out[k] += c.usage.output
            think[k] += c.usage.thinking
            effort[k][c.effort or "?"] += c.usage.output
            users[k][s.name + (" (subagent)" if a else "")] += c.usage.output
        if not out:
            scr.box(y + 1, x, h - 1, w, "Models")
            scr.put(y + 3, x + 3, "No API calls in the last %s. Try a longer range with g." % SPANS[self.span_i][1], self.T("dim"))
            return
        models = [m for m, _ in out.most_common(4)]
        total = sum(out.values())
        foot = 6
        pw = w // len(models)
        n = self.nbuckets(pw - 2)
        for i, m in enumerate(models):
            px = x + i * pw
            col = self.T("series")[i % len(self.T("series"))]
            vals = self.per_min(self.store.series(self.span, n, lambda c, m=m: c.usage.output if key(c) == m else 0))
            scr.box(y + 1, px, h - foot - 1, pw - 1, m, fpct(out[m] / total), title_fg=col)
            self.chart(y + 2, px + 1, h - foot - 5, pw - 3, vals, color=col)
            ef = effort[m]
            ef_t = sum(ef.values()) or 1
            scr.put(y + h - foot - 3, px + 2, clip("Effort " + " · ".join("%s %s" % (e, fpct(v / ef_t)) for e, v in ef.most_common()), pw - 5), self.T("fg"))
            us = users[m]
            us_t = sum(us.values()) or 1
            scr.put(y + h - foot - 2, px + 2, clip("Used by " + ", ".join("%s %s" % (u, fpct(v / us_t)) for u, v in us.most_common(3)), pw - 5), self.T("dim"))
        sy = y + h - foot
        scr.box(sy, x, foot, w, "Output share · last %s" % SPANS[self.span_i][1])
        bx = x + 2
        bw = w - 4
        for i, m in enumerate(out.most_common()):
            seg = max(1, round(m[1] / total * bw))
            col = self.T("series")[i % len(self.T("series"))]
            scr.put(sy + 1, bx, "█" * min(seg, x + 2 + bw - bx), col)
            bx += seg
        lx = x + 2
        for i, (m, v) in enumerate(out.most_common()):
            col = self.T("series")[i % len(self.T("series"))]
            lx += scr.put(sy + 2, lx, "■ ", col)
            lx += scr.put(sy + 2, lx, "%s %s   " % (m, fpct(v / total)), self.T("fg"))
        tt = sum(think.values())
        self.kv(sy + 3, x + 2, "Thinking share of output", fpct(tt / total) if total else "—", w=30)
        self.kv(sy + 3, x + 34, "Output tokens", ftok(total), w=20)

    # ── pages 6, 7: limits ─────────────────────────────────────────────────
    def page_limit(self, key, y, x, h, w):
        scr = self.scr
        cfg = WINDOWS[key]
        f = self.forecasts.get(key)
        weekly = key == "seven_day"
        scr.put(y, x + 1, "%s limit" % cfg["label"], self.T("title"), extra=curses.A_BOLD)
        if not f or f.pct is None:
            if self.not_reported(key):
                scr.box(y + 1, x, h - 1, w, "%s limit: not reported" % cfg["label"])
                lines = ["The tap is working, but Claude Code reports no %s limit for this account;" % cfg["label"].lower(),
                         "it reports only the other window. This page fills in if one starts being reported."]
                for i, ln in enumerate(lines):
                    scr.put(y + 3 + i, x + 3, ln, self.T("fg"), maxw=w - 6)
                return
            self.tap_callout(y + 1, x, h - 1, w, "%s limit" % cfg["label"])
            return
        now = time.time()
        end = f.resets or (now + cfg["span"])
        start = end - cfg["span"]
        foot = 8
        ch_h = h - foot - 4             # chart rows; the box adds two borders and an axis row
        label_w = 5
        cw = w - 2 - label_w
        scr.box(y + 1, x, ch_h + 3, w, "%s · %s → %s" % (cfg["label"], fdate(start, weekly), fdate(end, weekly)),
                "observed %s ago" % fdur(now - f.observed))
        cy, cx = y + 2, x + 1 + label_w
        cv = Canvas(cw, ch_h)

        def px(t):
            return (t - start) / (end - start) * (cv.w - 1)

        def py(p):
            return max(0, min(cv.h - 1, p / 100 * (cv.h - 1)))

        # observed area: step-hold between observations
        pts = f.points
        if pts:
            j = 0
            cur = 0.0
            last_x = int(px(min(now, f.observed)))
            for X in range(0, last_x + 1):
                t = start + X / (cv.w - 1) * (end - start)
                while j < len(pts) and pts[j][0] <= t:
                    cur = pts[j][1]
                    j += 1
                if j == 0:
                    continue
                cv.column(X, py(cur) + 1, lambda fr: scr.level_color(fr))
        # blind-spot jumps
        for t0, t1, dp, local in f.gaps:
            for X in range(int(px(t0)), int(px(t1)) + 1):
                if 0 <= X < cv.w:
                    cv.vline_cells(X // 2, "░", self.T("border"))
        # projections: rate (dashed), worst / best (dotted fan)
        x_now, y_now = px(f.observed), py(f.pct)
        for rate, col, dash in ((f.best, self.T("dim"), 1), (f.worst, self.T("warn"), 1), (f.rate, self.T("crit"), 3)):
            if not rate or rate <= 0:
                continue
            eta = f.eta(rate)
            t_end = min(eta, end)
            p_end = f.pct + rate * (t_end - f.observed)
            cv.line(x_now, y_now, px(t_end), py(p_end), col, dash=dash)
        eta = f.eta(f.rate)
        if eta and eta < end:
            c0 = int(px(eta)) // 2
            for col_i in range(c0, cv.cols):
                for r in range(cv.rows):
                    if (r, col_i) not in cv.text and not cv.bits[r][col_i]:
                        cv.text[(r, col_i)] = ("╱", self.T("crit"))
            lab = "full ≈ %s" % fclock(eta, weekly)
            cv.label(max(0, min(cv.cols - len(lab), c0 - len(lab) - 1)), 0, lab, self.T("crit"))
        ncol = int(x_now) // 2
        cv.vline_cells(min(cv.cols - 1, ncol), "┊", self.T("info"))
        cv.render(scr, cy, cx, grid=("┈", max(2, ch_h // 4), self.T("border")))
        for frac in (1.0, 0.5, 0.0):
            scr.put(cy + int((1 - frac) * (ch_h - 1)), x + 1, ("%d%%" % (frac * 100)).rjust(4), self.T("dim"))
        # time axis
        ticks = 6 if not weekly else 7
        ay = cy + ch_h
        for i in range(ticks + 1):
            t = start + i * (end - start) / ticks
            lab = datetime.fromtimestamp(t).strftime("%a" if weekly else "%H:%M")
            tx = cx + int(i / ticks * (cw - 1))
            scr.put(ay, min(tx, cx + cw - len(lab)), lab, self.T("dim"))
        # now + forecast boxes
        fy = y + h - foot
        scr.box(fy, x, foot, 34, "Now")
        unit, uname = cfg["unit"], cfg["unit_name"]
        self.kv(fy + 1, x + 2, "Used", "%.0f%%" % f.pct, scr.level_color(f.pct / 100), 10)
        scr.gauge(fy + 3, x + 2, 28, f.pct / 100)
        self.kv(fy + 4, x + 2, "Rate", ("%.1f %%/%s" % (f.rate * unit, uname)) if f.rate else "—", w=14)
        if not weekly:
            self.kv(fy + 4, x + 17, "Session rate", ("%.0f %%/5h" % (f.rate * 5 * 3600)) if f.rate else "—", w=15)
        else:
            self.kv(fy + 4, x + 17, "Resets", fclock(f.resets, True), w=15)
        bx = x + 35
        bw = w - 35
        scr.box(fy, bx, foot, bw, "Limit hit forecast", f.note or "rolling %s window" % fdur(cfg["recent"]))
        cells = [("Projected", f.rate), ("Worst", f.worst), ("Best", f.best)]
        for i, (lab, rate) in enumerate(cells):
            e = f.eta(rate)
            if not rate:
                val = "∞"
            elif f.resets and e and e > f.resets:
                val = "after reset"
            else:
                val = fclock(e, weekly)
            col = self.T("crit") if lab == "Projected" and val not in ("∞", "after reset") else self.T("fg")
            self.kv(fy + 1, bx + 2 + i * 16, lab, val, col, 15)
        self.kv(fy + 1, bx + 50, "Resets in", fdur((f.resets or now) - now), w=14)
        gy = fy + 4
        if f.gaps:
            scr.put(gy, bx + 2, "Unattributed jumps (usage seen while this machine was silent):", self.T("warn"))
            for t0, t1, dp, local in f.gaps[-2:]:
                gy += 1
                scr.put(gy, bx + 4, clip("+%.0f%%  %s → %s   local tokens then: %s" % (dp, fclock(t0, weekly), fclock(t1, weekly), ftok(local or 0)), bw - 6), self.T("fg"))
        else:
            scr.put(gy, bx + 2, "Projected = recent rate · Worst = busiest slice · Best = average since period start", self.T("dim"))
            scr.put(gy + 1, bx + 2, "Gaps over 15 min are excluded from rates and marked ░ on the chart.", self.T("dim"))

    # ── page 8: projects ───────────────────────────────────────────────────
    def page_projects(self, y, x, h, w):
        scr = self.scr
        now = time.time()
        f7 = self.forecasts.get("seven_day")
        start = (f7.resets - 7 * 86400) if f7 and f7.resets else now - 7 * 86400
        scr.put(y, x + 1, "Projects", self.T("title"), extra=curses.A_BOLD)
        scr.put(y, x + 12, "%s → now" % fclock(start, True), self.T("dim"))
        by_proj = Counter()
        by_sub = defaultdict(Counter)
        days = defaultdict(lambda: [0.0] * 7)
        toks = 0
        for s, c, a in self.store.calls(start):
            wt = weight(c.usage)
            by_proj[s.project] += wt
            by_sub[s.project][short_model(c.model)] += wt
            d = int((c.ts - start) // 86400)
            if 0 <= d < 7:
                days[s.project][d] += wt
            toks += c.usage.total
        total = sum(by_proj.values())
        self.kv(y + 1, x + 2, "Weekly limit used", "%d%%" % round(f7.pct) if f7 and f7.pct is not None else "—", w=20)
        self.kv(y + 1, x + 24, "Tokens", ftok(toks), w=14)
        self.kv(y + 1, x + 40, "Projects", str(len(by_proj)), w=10)
        scr.box(y + 4, x, h - 4 - 5, w, "Share of usage", "cost-weighted tokens")
        if not total:
            scr.put(y + 6, x + 3, "No usage recorded in this period.", self.T("dim"))
            return
        dname = [datetime.fromtimestamp(start + i * 86400).strftime("%a")[:2] for i in range(7)]
        bar_w = max(10, w - 62)
        row = y + 5
        scr.put(row, x + 2, "Project", self.T("dim"), extra=curses.A_UNDERLINE)
        scr.put(row, x + 24 + bar_w + 1, "share  of wk", self.T("dim"), extra=curses.A_UNDERLINE)
        scr.put(row, x + 24 + bar_w + 15, " ".join(dname), self.T("dim"))
        row += 1
        for i, (proj, v) in enumerate(by_proj.most_common()):
            if row >= y + h - 6:
                break
            col = self.T("series")[i % len(self.T("series"))]
            share = v / total
            scr.put(row, x + 2, clip(proj, 21), self.T("fg"), extra=curses.A_BOLD)
            scr.gauge(row, x + 24, bar_w, share, color=col)
            wk = (" ≈%d%%" % round(share * f7.pct)) if f7 and f7.pct is not None else ""
            scr.put(row, x + 24 + bar_w + 1, ("%s" % fpct(share)).rjust(5) + wk.rjust(7), self.T("fg"))
            dv = days[proj]
            dm = max(dv) or 1
            for d in range(7):
                ch = " ▁▂▃▄▅▆▇█"[int(round(dv[d] / dm * 8))] if dv[d] else "·"
                scr.put(row, x + 24 + bar_w + 15 + d * 3, ch * 2, col)
            row += 1
            for model, mv in by_sub[proj].most_common(2):
                if row >= y + h - 6 or len(by_sub[proj]) < 2:
                    break
                scr.put(row, x + 4, clip(model, 19), self.T("dim"))
                scr.gauge(row, x + 24, bar_w, mv / total, color=col, empty=" ")
                scr.put(row, x + 24 + bar_w + 1, fpct(mv / total).rjust(5), self.T("dim"))
                row += 1
        cy = y + h - 5
        scr.box(cy, x, 5, w, "Composition")
        bx, bw = x + 2, w - 4
        lx = x + 2
        for i, (proj, v) in enumerate(by_proj.most_common()):
            col = self.T("series")[i % len(self.T("series"))]
            seg = max(1, round(v / total * bw))
            scr.put(cy + 1, bx, "█" * max(0, min(seg, x + 2 + bw - bx)), col)
            bx += seg
            if i < 6:
                lx += scr.put(cy + 2, lx, "■ ", col)
                lx += scr.put(cy + 2, lx, "%s %s  " % (proj, fpct(v / total)), self.T("fg"))

    # ── page 9: inspect ────────────────────────────────────────────────────
    def page_inspect(self, y, x, h, w):
        scr = self.scr
        now = time.time()
        sessions = self.session_list()
        s = self.selected(sessions)
        scr.put(y, x + 1, "Inspect", self.T("title"), extra=curses.A_BOLD)
        scr.put(y, x + 11, "↑↓ to switch session (%d of %d)" % (self.sel + 1, len(sessions)) if s else "", self.T("dim"))
        if not s:
            scr.box(y + 1, x, h - 1, w, "No sessions")
            return
        lw = min(48, w // 2)
        info_h = 17
        scr.box(y + 1, x, info_h, lw, s.name, focus=True)
        used, size = s.context()
        tot = s.t.totals()
        dur = (s.t.last_ts or now) - (s.t.started or now)
        rows = [
            ("State", None), ("Title", s.t.title or "—"), ("Project", s.project), ("Branch", s.t.git_branch or "—"),
            ("Model", "%s  (%s)" % (short_model(s.model), s.model or "?")), ("Effort", s.effort or "—"),
            ("Mode", s.t.permission_mode or "—"), ("PID", str((s.live or {}).get("pid", "—"))),
            ("Running", fdur(dur)), ("Tokens", "%s total · %s out" % (ftok(tot.total), ftok(tot.output))),
            ("Cost", ("$%.2f" % s.cost()) if s.cost() is not None else "— (tap)"),
            ("Compacts", "%d   API errors %d" % (s.t.compactions, s.t.api_errors)),
            ("Context", None), ("Prompt", s.t.last_prompt or "—"),
        ]
        for i, (k, v) in enumerate(rows):
            ry = y + 2 + i
            scr.put(ry, x + 2, k, self.T("dim"))
            if k == "State":
                self.badge(ry, x + 12, s.state(now))
                st = s.t.stuck_tool(now)
                if st:
                    scr.put(ry, x + 26, clip("%s waiting %s" % (st[0], fdur(st[1])), lw - 28), self.T("warn") if st[1] > 30 else self.T("dim"))
            elif k == "Context":
                scr.gauge(ry, x + 12, lw - 26, used / size)
                scr.put(ry, x + lw - 13, "%s %s" % (fpct(used / size), ftok(used)), scr.level_color(used / size))
            else:
                scr.put(ry, x + 12, clip(v, lw - 14), self.T("fg"))
        # right: burn chart
        rx, rw = x + lw, w - lw
        ch = 8
        scr.box(y + 1, rx, ch, rw, "Tokens / min · main + subagents", SPANS[self.span_i][1])
        n = self.nbuckets(rw - 2)
        self.chart(y + 2, rx + 1, ch - 2, rw - 2, self.per_min(self.store.series(self.span, n, lambda c: c.usage.total, [s])))
        # tools
        ty = y + 1 + ch
        scr.box(ty, rx, info_h - ch, rw, "Top tools")
        tools = Counter()
        for t, _ in s.transcripts():
            tools.update(t.tools)
        tmax = max(tools.values()) if tools else 1
        for i, (name, n_) in enumerate(tools.most_common(info_h - ch - 2)):
            scr.put(ty + 1 + i, rx + 2, clip(name, 14), self.T("fg"))
            scr.gauge(ty + 1 + i, rx + 17, max(5, rw - 26), n_ / tmax, color=self.T("series")[i % len(self.T("series"))], empty=" ")
            scr.put(ty + 1 + i, rx + rw - 7, str(n_).rjust(5), self.T("dim"))
        # subagents
        ay = y + 1 + info_h
        loops = s.loops()
        loop_h = min(len(loops) + 3, 7) if loops else 3
        ah = h - info_h - 1 - loop_h
        scr.box(ay, x, ah, w, "Subagents", "%d" % len(s.agents))
        heads = [("Agent", 34), ("Type", 16), ("Model", 11), ("Effort", 7), ("Out", 7), ("Tok/min", 8), ("Status", 10)]
        cx = x + 2
        for name, cw in heads:
            scr.put(ay + 1, cx, name, self.T("dim"), extra=curses.A_UNDERLINE)
            cx += cw + 1
        agents = sorted(list(s.agents.values()), key=lambda a: (a.finished, -(a.t.last_ts or 0)))
        for i, a in enumerate(agents[: max(0, ah - 3)]):
            ry = ay + 2 + i
            u = a.t.totals()
            recent = a.t.totals(now - 300)
            cx = x + 2
            vals = [clip(a.label, 33), clip(a.meta.get("agentType", "?"), 15), short_model(a.t.model), (a.t.effort or "—")[:6],
                    ftok(u.output), ftok(recent.total / 5)]
            for (name, cw), v in zip(heads, vals):
                scr.put(ry, cx, v, self.T("fg") if name == "Agent" else self.T("dim"))
                cx += cw + 1
            scr.put(ry, cx, "done" if a.finished else "running", self.T("dim") if a.finished else self.T("ok"))
        if not agents:
            scr.put(ay + 2, x + 2, "No subagents in this session.", self.T("dim"))
        # loops
        ly = ay + ah
        scr.box(ly, x, loop_h, w, "Loop watch", "files read ≥3× with no edit between", title_fg=self.T("crit") if loops else None)
        if not loops:
            scr.put(ly + 1, x + 2, "No re-read loops detected. ", self.T("ok"))
        for i, (path, worst, current, a) in enumerate(loops[: loop_h - 2]):
            who = ("subagent " + clip(a.label, 18)) if a else "main"
            home = os.path.expanduser("~")
            p = path.replace(home, "~")
            scr.put(ly + 1 + i, x + 2, "⟲ %d×" % worst, self.T("crit"), extra=curses.A_BOLD)
            scr.put(ly + 1 + i, x + 9, clip(p, w - 40), self.T("fg"))
            scr.put(ly + 1 + i, x + w - 30, clip("%s · now %d since edit" % (who, current), 28), self.T("dim"))

    # ── page 0: settings ───────────────────────────────────────────────────
    def page_settings(self, y, x, h, w):
        scr = self.scr
        scr.put(y, x + 1, "Settings", self.T("title"), extra=curses.A_BOLD)
        tw = min(46, w // 2)
        scr.box(y + 1, x, len(THEME_ORDER) + 3, tw, "Theme", "↑↓ ⏎")
        for i, name in enumerate(THEME_ORDER):
            t = THEMES[name]
            ry = y + 2 + i
            cur = i == self.theme_cursor
            mark = "▸" if cur else " "
            on = "●" if name == self.scr.theme_name else " "
            scr.put(ry, x + 2, mark + on + " " + name, self.T("accent") if cur else self.T("fg"), extra=curses.A_BOLD if cur else 0)
            sx = x + 18
            for j, c in enumerate(t["grad"] + [None] + t["series"][:5]):
                if c is None:
                    sx += 1
                    continue
                scr.put(ry, sx, "██", c)
                sx += 2
        ix = x + tw
        iw = w - tw
        scr.box(y + 1, ix, len(THEME_ORDER) + 3, iw, "Data sources")
        st = install.safe_status()
        lines = [
            ("settings.json", st["error"], self.T("crit")),
        ] if st["error"] else []
        lines += [
            ("Transcripts", "read-only, ~/.claude/projects", self.T("ok")),
            ("Live registry", "~/.claude/sessions", self.T("ok")),
            ("Status-line tap", "installed" if st["statusline"] else "not installed (press I)", self.T("ok") if st["statusline"] else self.T("warn")),
            ("Notification hook", "installed" if st["hook"] else "not installed (press I)", self.T("ok") if st["hook"] else self.T("warn")),
            ("Limit samples", str(sum(len(v) for v in self.store.limits.obs.values())), self.T("fg")),
            ("Sessions indexed", str(len(self.store.sessions)), self.T("fg")),
            ("Update every", "%d s  (u)" % self.interval, self.T("fg")),
            ("Graph range", "%s  (g)" % SPANS[self.span_i][1], self.T("fg")),
        ]
        for i, (k, v, col) in enumerate(lines):
            scr.put(y + 2 + i, ix + 2, k, self.T("dim"))
            scr.put(y + 2 + i, ix + 22, clip(v, iw - 24), col)
        if self.tap_ok:
            scr.put(y + 2 + len(lines) + 1, ix + 2, "✓ tap installed · U U to remove", self.T("ok"))
        else:
            self.chip(y + 2 + len(lines) + 1, ix + 2, " ⚡ I I  Install the tap ", "warn")
        py = y + len(THEME_ORDER) + 5
        if py + 6 < y + h:
            ph = h - (py - y)
            vals = [max(1, 14 + 8 * math.sin(i / 7.0) + 4 * math.sin(i / 2.6 + 1) + 16 * math.exp(-((i - 44) / 3.0) ** 2))
                    for i in range(72)]
            bw = w // len(STYLES)
            if bw < 14:                                    # too narrow for five: just the active style
                scr.box(py, x, ph, w, "Graph style: " + self.style, "b")
                self.chart(py + 1, x + 1, ph - 4, w - 2, vals, scale_fmt=None)
                scr.gauge(y + h - 2, x + 2, w - 4, 0.72)
            else:
                for i, name in enumerate(STYLES):
                    bx = x + i * bw
                    cw = bw if i < len(STYLES) - 1 else w - bw * (len(STYLES) - 1)
                    on = name == self.style
                    scr.box(py, bx, ph, cw, name, "● b" if on else "", focus=on)
                    keep = scr.style
                    scr.style = name
                    self.chart(py + 1, bx + 1, ph - 5, cw - 2, vals, scale_fmt=None, style=name)
                    scr.gauge(py + ph - 3, bx + 2, cw - 4, 0.72)
                    scr.style = keep
                    scr.put(py + ph - 2, bx + 2, clip(STYLE_NOTE[name], cw - 4), self.T("dim"))


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
