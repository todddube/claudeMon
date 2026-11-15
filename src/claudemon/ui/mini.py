"""The mini view (z): a small window with both limits, the burn rate and one row per session."""

import curses
import time
from collections import Counter
from datetime import datetime

from claudemon.core.fmt import fclock, fpct, ftok
from claudemon.sources.store import IDLE, NEEDS_YOU, WORKING, short_model
from claudemon.ui.draw import STYLES, clip
from claudemon.ui.themes import ORDER as THEME_ORDER
from claudemon.ui import widgets as W
from claudemon.ui.widgets import STATE_BADGE

MINI_W, MINI_MAX = 74, 10   # mini view: window width, most session rows before "+n more"


def set_mini(ctx, on):
    if on == ctx.mini:
        return
    if on:
        h, w = ctx.scr.size
        if h >= 16 and w >= 70:               # remember a real full-size window, not a tiny one
            ctx.full_size = (h, w)
        ctx.mini = True
        fit(ctx)
    else:
        ctx.mini = False
        ctx.resize(*ctx.full_size)
    ctx.flash = "mini view: z for the full view" if on else ""


def height(ctx):
    n = len(ctx.session_list())
    return 6 + max(1, min(n, MINI_MAX)) + (1 if n > MINI_MAX else 0)


def fit(ctx):
    """Keep the window just tall enough for the session list as sessions come and go."""
    want = (height(ctx), MINI_W)
    if want != ctx.sized:
        ctx.resize(*want)


def on_key(ctx, key, k):
    """The mini view's keys; always True, so no global key runs behind it."""
    d = W.updown(key, k)
    if d:
        ctx.move(d)
    elif W.is_enter(key):
        ctx.go_page("inspect")
        set_mini(ctx, False)
    elif ctx.page_for_key(k):                  # a page key opens that page in the full view
        ctx.go_page(ctx.page_for_key(k))
        set_mini(ctx, False)
    elif k in ("m", "M", "?"):                 # the manual and help need the full view
        set_mini(ctx, False)
        if k == "?":
            ctx.modal = "help"
        else:
            ctx.man_i, ctx.man_scroll, ctx.modal = 0, 0, "manual"
    elif k == "t":
        i = (THEME_ORDER.index(ctx.scr.theme_name) + 1) % len(THEME_ORDER)
        ctx.scr.set_theme(THEME_ORDER[i])
        ctx.theme_cursor = i
        ctx.flash = "theme: " + THEME_ORDER[i]
    elif k == "b":
        ctx.style = STYLES[(STYLES.index(ctx.style) + 1) % len(STYLES)]
        ctx.scr.style = ctx.style
        ctx.flash = "graphs: " + ctx.style
    elif k == "a":
        ctx.show_all = not ctx.show_all
        ctx.flash = "all recent sessions" if ctx.show_all else "live sessions"
    elif k == "r":
        ctx.tick(force=True)
    elif k == "I":
        if ctx.tap_ok:
            ctx.flash = "tap is already installed"
        elif ctx.confirm("I", "⚡ I again installs the tap"):
            ctx.do_install()
    return True


def limit(ctx, y, w, key, label):
    """One gauge row for a limit window: bar, percent, and the full or reset time."""
    scr = ctx.scr
    f = ctx.forecasts.get(key)
    weekly = key == "seven_day"
    scr.put(y, 1, label, ctx.T("dim"))
    gx, gw = 5, max(8, w - 33)
    if not f or f.pct is None:
        scr.gauge(y, gx, gw, 0)
        msg = "⚡ I I installs the tap" if not ctx.tap_ok else "not reported" if ctx.not_reported(key) else "waiting for data"
        scr.put(y, gx + gw + 2, msg, ctx.T("warn") if not ctx.tap_ok else ctx.T("dim"), maxw=w - gx - gw - 3)
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
    scr.put(y, x + 2, note, ctx.T(role), maxw=w - x - 3)


def draw(ctx, h, w):
    """Header, both limits, burn, one row per session and the footer, in an h x w window."""
    scr = ctx.scr
    if h < 6 or w < 40:
        scr.put(0, 0, "mini needs 40×6 (z for the full view)", ctx.T("warn"))
        return
    now = time.time()
    live = ctx.store.live_sessions()
    bg = ctx.T("hl_bg")
    scr.fill(0, 0, 1, w, bg)
    x = scr.put(0, 1, "◆ ", ctx.T("accent"), bg, curses.A_BOLD) + 1
    x += scr.put(0, x, "claudeMon", ctx.T("title"), bg, curses.A_BOLD)
    clock = datetime.now().strftime("%H:%M:%S ")
    end = w - len(clock) - 3                      # header text stops short of the clock
    x += scr.put(0, x, "  %d live" % len(live), ctx.T("fg"), bg, maxw=end - x)
    counts = Counter(s.state(now) for s in live)
    for state in (NEEDS_YOU, WORKING, IDLE):
        text, role = STATE_BADGE[state]
        sym, word = text.split(" ", 1)
        item = "  %s %d %s" % (sym, counts[state], word.lower())
        if counts[state] and x + len(item) <= end:
            x += scr.put(0, x, item, ctx.T(role), bg, curses.A_BOLD if state == NEEDS_YOU else 0)
    dot = ctx.T("ok") if now - ctx.last_tick < ctx.interval + 2 else ctx.T("crit")
    scr.put(0, w - len(clock) - 2, "●", dot, bg)
    scr.put(0, w - len(clock), clock, ctx.T("dim"), bg)

    limit(ctx, 1, w, "five_hour", "5h")
    limit(ctx, 2, w, "seven_day", "7d")

    spark = ctx.store.series(1800, 30, lambda c: c.usage.total)
    burn = ctx.store.series(60, 1, lambda c: c.usage.total)[0]
    scr.put(3, 1, "burn", ctx.T("dim"))
    sw = max(8, min(30, w - 46))
    scr.spark(3, 6, spark, sw)
    x = 7 + sw
    x += scr.put(3, x, "%s/min" % ftok(burn), ctx.T("fg"), extra=curses.A_BOLD)
    warm = sum(1 for s in live if (s.t.cache_expires() or 0) > now)
    u = ctx.store.totals(now - 300)
    hit = u.cache_read / u.prompt if u.prompt else None
    scr.put(3, x, "   cache %d/%d warm · hit %s" % (warm, len(live), fpct(hit)), ctx.T("dim"), maxw=w - x - 1)

    scr.put(4, 0, "─" * w, ctx.T("border"))
    scr.put(4, 2, " Sessions ", ctx.T("title"), extra=curses.A_BOLD)

    sessions = ctx.session_list()
    sel = ctx.selected(sessions)
    room = max(1, h - 6)
    shown = sessions[:room] if len(sessions) <= room else sessions[:room - 1]
    if sel in sessions and sel not in shown:              # keep the selection on screen
        shown = shown[:-1] + [sel]
    y = 5
    if not sessions:
        scr.put(y, 2, "no live Claude Code sessions", ctx.T("dim"))
    nw = max(8, w - 50)                           # columns after the name: model 18, ctx 8, rate 9, doing 12
    for s in shown:
        focus = s is sel
        rbg = bg if focus else None
        if focus:
            scr.fill(y, 0, 1, w, bg)
            scr.put(y, 0, "▌", ctx.T("accent"), rbg)
        state = s.state(now)
        text, role = STATE_BADGE[state]
        scr.put(y, 1, text.split(" ", 1)[0], ctx.T(role), rbg, curses.A_BOLD)
        scr.put(y, 3, clip(s.name, nw - 1), ctx.T("title") if focus else ctx.T("fg"), rbg,
                curses.A_BOLD if state == NEEDS_YOU or focus else 0)
        x = 3 + nw
        scr.put(y, x, clip("%s·%s" % (short_model(s.model), s.effort or "?"), 17), ctx.T("dim"), rbg)
        used, size = s.context()
        frac = used / size if size else 0
        scr.put(y, x + 18, "ctx", ctx.T("dim"), rbg)
        scr.put(y, x + 22, "%4s" % fpct(frac), scr.level_color(frac), rbg)
        rate = ctx.store.series(60, 1, lambda c: c.usage.total, [s])[0]
        scr.put(y, x + 26, "%8s" % (ftok(rate) + "/m"), ctx.T("fg"), rbg)
        pending = sorted(list(s.t.pending_tools.values()), key=lambda p: p[1] or 0)
        agents = sum(1 for a in list(s.agents.values()) if not a.finished)
        doing = pending[-1][0] if pending else ""
        if agents:
            doing = ("%s ◇%d" % (doing, agents)).strip()
        n_loops = len(s.loops())
        if n_loops:
            doing = ("%s ⟲%d" % (doing, n_loops)).strip()
        scr.put(y, x + 36, clip(doing, w - x - 37), ctx.T("crit") if n_loops else ctx.T("info"), rbg)
        y += 1
    if len(sessions) > len(shown):
        scr.put(y, 3, "+%d more (z for the full view)" % (len(sessions) - len(shown)), ctx.T("dim"))

    fy = h - 1
    msg = ctx.flash or ("" if ctx.tap_ok else "⚡ tap off: I I")
    x = 1
    for key, label in (("z", "full"), ("q", "quit"), ("↑↓", "select"), ("⏎", "inspect"), ("1-0", "page"), ("t", "theme")):
        if x + len(key) + len(label) + 3 > w - len(msg) - 2:
            break
        x += scr.put(fy, x, key, ctx.T("accent"), extra=curses.A_BOLD)
        x += scr.put(fy, x, " %s  " % label, ctx.T("dim"))
    if msg:
        scr.put(fy, w - len(msg) - 2, msg, ctx.T("info") if ctx.flash else ctx.T("warn"))
