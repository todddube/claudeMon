"""Drawing helpers shared by the pages, the mini view and the modals.

Each takes the App (`ctx`) first and draws on `ctx.scr` in the current theme and graph style.
"""

import curses

from claudemon.core.fmt import ftok
from claudemon.sources.store import DONE, IDLE, NEEDS_YOU, WORKING
from claudemon.ui.draw import GLYPHS, Canvas, blocks

SPANS = [(300, "5m"), (900, "15m"), (3600, "1h"), (6 * 3600, "6h"), (86400, "24h")]
STATE_BADGE = {
    WORKING: ("● Working", "ok"),
    NEEDS_YOU: ("▲ Needs you", "warn"),
    IDLE: ("○ Idle", "dim"),
    DONE: ("· Done", "dim"),
}


def updown(key, k):
    """1 for ↓ or j, -1 for ↑ or k, else 0."""
    return 1 if (key == curses.KEY_DOWN or k == "j") else -1 if (key == curses.KEY_UP or k == "k") else 0


def is_enter(key):
    return key in ("\n", "\r", curses.KEY_ENTER)


def grad_fn(ctx):
    return lambda frac: ctx.scr.grad_color(frac)


def chart(ctx, y, x, h, w, values, vmax=None, color=None, line=None, scale_fmt=ftok, grid=True, style=None):
    """Area chart in the chosen graph style filling an h×w cell rectangle; returns the scale used."""
    style = style or ctx.style
    if h < 1 or w < 2:
        return 0
    top = vmax if vmax is not None else (max(values) if values else 0)
    color_fn = (lambda f: color) if color is not None else grad_fn(ctx)
    g = ("." if style == "ascii" else "┈", max(2, h // 3), ctx.T("border")) if grid and h >= 4 else None
    if style in ("braille", "line"):
        cv = Canvas(w, h)
        if style == "line":
            cv.trace(values, top or 1, color_fn)
        else:
            cv.area(values, top or 1, color_fn, line)
        cv.render(ctx.scr, y, x, ctx.T("accent"), grid=g)
    else:
        blocks(ctx.scr, y, x, h, w, values, top or 1, color_fn, g, GLYPHS[style])
    if scale_fmt and top:
        lab = scale_fmt(top)
        ctx.scr.put(y, x + w - len(lab), lab, ctx.T("dim"))
    return top


def nbuckets(ctx, w):
    return max(2, min(w * (2 if ctx.style in ("braille", "line") else 1), ctx.span // 5))


def per_min(ctx, values):
    size = ctx.span / max(1, len(values))
    return [v * 60 / size for v in values]


def kv(ctx, y, x, label, value, color=None, w=14):
    ctx.scr.put(y, x, label, ctx.T("dim"), maxw=w)
    ctx.scr.put(y + 1, x, value, color or ctx.T("fg"), extra=curses.A_BOLD, maxw=w)


def toggles(ctx, y, x, label, options, active, key):
    x0 = x
    x += ctx.scr.put(y, x, label + " ", ctx.T("dim"))
    for i, opt in enumerate(options):
        if i == active:
            x += ctx.scr.put(y, x, " %s " % opt, ctx.T("bg") if ctx.T("bg") >= 0 else 16, ctx.T("accent"), curses.A_BOLD)
        else:
            x += ctx.scr.put(y, x, " %s " % opt, ctx.T("fg"))
    x += ctx.scr.put(y, x, " [%s]  " % key, ctx.T("border"))
    return x - x0


def span_toggle(ctx, y, x):
    return toggles(ctx, y, x, "Graph", [s[1] for s in SPANS], ctx.span_i, "g")


def badge(ctx, y, x, state):
    text, role = STATE_BADGE[state]
    return ctx.scr.put(y, x, text, ctx.T(role), extra=curses.A_BOLD if state == NEEDS_YOU else 0)


def chip(ctx, y, x, text, role="warn"):
    """A reverse-video button-like label; returns its width."""
    dark = ctx.T("bg") if ctx.T("bg") >= 0 else 16
    return ctx.scr.put(y, x, text, dark, ctx.T(role), curses.A_BOLD)


def tap_callout(ctx, y, x, h, w, what):
    """A large, hard-to-miss panel shown where a page needs the tap."""
    scr = ctx.scr
    scr.box(y, x, h, w, "⚡ %s needs the claudeMon tap" % what, focus=True, title_fg=ctx.T("warn"))
    if ctx.tap_ok:
        lines = ["The tap is installed. Waiting for the next status-line refresh.",
                 "Send a message in any Claude Code session and data appears within seconds.",
                 "", "Limits are only reported on Pro, Max, Team and Enterprise logins."]
        for i, ln in enumerate(lines):
            scr.put(y + 2 + i, x + 3, ln, ctx.T("fg"))
        return
    lines = ["Claude Code reports account limits only through its status line.",
             "The tap records each status-line refresh and still prints your status line unchanged.",
             "Your settings.json is backed up first, and `claudemon uninstall` restores it exactly."]
    for i, ln in enumerate(lines):
        scr.put(y + 2 + i, x + 3, ln, ctx.T("fg"))
    chip(ctx, y + 6, x + 3, "  I I  Install the tap  ", "warn")
    scr.put(y + 6, x + 31, "press I twice to confirm", ctx.T("dim"))
    scr.put(y + 8, x + 3, "More in the manual: press m.", ctx.T("dim"))
