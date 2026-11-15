"""Page s, Settings: theme, data sources and the tap, and the graph styles."""

import curses
import math

from claudemon.tap import installer as install
from claudemon.ui import widgets as W
from claudemon.ui.draw import STYLE_NOTE, STYLES, clip
from claudemon.ui.pages import Page
from claudemon.ui.themes import ORDER as THEME_ORDER
from claudemon.ui.themes import THEMES
from claudemon.ui.widgets import SPANS


def render(ctx, y, x, h, w):
    scr = ctx.scr
    scr.put(y, x + 1, "Settings", ctx.T("title"), extra=curses.A_BOLD)
    tw = min(46, w // 2)
    scr.box(y + 1, x, len(THEME_ORDER) + 3, tw, "Theme", "↑↓ ⏎")
    for i, name in enumerate(THEME_ORDER):
        t = THEMES[name]
        ry = y + 2 + i
        cur = i == ctx.theme_cursor
        mark = "▸" if cur else " "
        on = "●" if name == ctx.scr.theme_name else " "
        scr.put(ry, x + 2, mark + on + " " + name, ctx.T("accent") if cur else ctx.T("fg"), extra=curses.A_BOLD if cur else 0)
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
        ("settings.json", st["error"], ctx.T("crit")),
    ] if st["error"] else []
    lines += [
        ("Transcripts", "read-only, ~/.claude/projects", ctx.T("ok")),
        ("Live registry", "~/.claude/sessions", ctx.T("ok")),
        ("Status-line tap", "installed" if st["statusline"] else "not installed (press I)", ctx.T("ok") if st["statusline"] else ctx.T("warn")),
        ("Notification hook", "installed" if st["hook"] else "not installed (press I)", ctx.T("ok") if st["hook"] else ctx.T("warn")),
        ("Limit samples", str(ctx.store.limit_samples()), ctx.T("fg")),
        ("Sessions indexed", str(ctx.store.session_count()), ctx.T("fg")),
        ("Update every", "%d s  (u)" % ctx.interval, ctx.T("fg")),
        ("Graph range", "%s  (g)" % SPANS[ctx.span_i][1], ctx.T("fg")),
    ]
    for i, (k, v, col) in enumerate(lines):
        scr.put(y + 2 + i, ix + 2, k, ctx.T("dim"))
        scr.put(y + 2 + i, ix + 22, clip(v, iw - 24), col)
    if ctx.tap_ok:
        scr.put(y + 2 + len(lines) + 1, ix + 2, "✓ tap installed · U U to remove", ctx.T("ok"))
    else:
        W.chip(ctx, y + 2 + len(lines) + 1, ix + 2, " ⚡ I I  Install the tap ", "warn")
    py = y + len(THEME_ORDER) + 5
    if py + 6 < y + h:
        ph = h - (py - y)
        vals = [max(1, 14 + 8 * math.sin(i / 7.0) + 4 * math.sin(i / 2.6 + 1) + 16 * math.exp(-((i - 44) / 3.0) ** 2))
                for i in range(72)]
        bw = w // len(STYLES)
        if bw < 14:                                    # too narrow for five: just the active style
            scr.box(py, x, ph, w, "Graph style: " + ctx.style, "b")
            W.chart(ctx, py + 1, x + 1, ph - 4, w - 2, vals, scale_fmt=None)
            scr.gauge(y + h - 2, x + 2, w - 4, 0.72)
        else:
            for i, name in enumerate(STYLES):
                bx = x + i * bw
                cw = bw if i < len(STYLES) - 1 else w - bw * (len(STYLES) - 1)
                on = name == ctx.style
                scr.box(py, bx, ph, cw, name, "● b" if on else "", focus=on)
                keep = scr.style
                scr.style = name
                W.chart(ctx, py + 1, bx + 1, ph - 5, cw - 2, vals, scale_fmt=None, style=name)
                scr.gauge(py + ph - 3, bx + 2, cw - 4, 0.72)
                scr.style = keep
                scr.put(py + ph - 2, bx + 2, clip(STYLE_NOTE[name], cw - 4), ctx.T("dim"))


def side(ctx):
    return [], "theme %s" % ctx.scr.theme_name, "tap %s" % ("on" if install.installed() else "off")


def on_key(ctx, key, k):
    """↑↓ move the theme cursor, ⏎ applies it, U U removes the tap."""
    d = W.updown(key, k)
    if d:
        ctx.theme_cursor = (ctx.theme_cursor + d) % len(THEME_ORDER)
    elif W.is_enter(key):
        ctx.scr.set_theme(THEME_ORDER[ctx.theme_cursor])
    elif k == "U":
        if ctx.confirm("U", "press U again to remove the tap and restore your status line"):
            try:
                ctx.flash = install.uninstall()
            except Exception as e:
                ctx.flash = "uninstall failed: %s" % e
            ctx.tap_ok = install.installed()
    else:
        return False
    return True


PAGE = Page("settings", "Settings", "s", render, side, on_key=on_key, manual_topic="Settings")
