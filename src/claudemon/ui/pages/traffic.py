"""Page 5, Traffic: output, fresh input and cache reads per minute."""

import curses
import time

from claudemon.core.fmt import fpct, ftok
from claudemon.ui import widgets as W
from claudemon.ui.pages import Page
from claudemon.ui.widgets import SPANS


def render(ctx, y, x, h, w):
    scr = ctx.scr
    scr.put(y, x + 1, "Traffic", ctx.T("title"), extra=curses.A_BOLD)
    W.span_toggle(ctx, y, x + 11)
    n = W.nbuckets(ctx, w - 2)
    panes = [
        ("Tokens out / min", lambda c: c.usage.output, ctx.T("accent")),
        ("Fresh input / min  (uncached + cache writes)", lambda c: c.usage.input + c.usage.cache_write, ctx.T("info")),
        ("Cache reads / min", lambda c: c.usage.cache_read, ctx.T("ok")),
    ]
    ph = (h - 5) // len(panes)
    for i, (title, fn, col) in enumerate(panes):
        py = y + 1 + i * ph
        vals = W.per_min(ctx, ctx.store.series(ctx.span, n, fn))
        scr.box(py, x, ph, w, title, "now %s/m" % ftok(vals[-1] if vals else 0))
        W.chart(ctx, py + 1, x + 1, ph - 2, w - 2, vals, color=None if i == 0 else col)
    u = ctx.store.totals(time.time() - ctx.span)
    sy = y + 1 + len(panes) * ph
    scr.box(sy, x, h - (sy - y), w, "Totals · last %s" % SPANS[ctx.span_i][1])
    cells = [("Output", ftok(u.output)), ("Thinking", ftok(u.thinking)), ("Thinking share", fpct(u.thinking / u.output) if u.output else "—"),
             ("Uncached in", ftok(u.input)), ("Cache writes", ftok(u.cache_write)), ("Cache reads", ftok(u.cache_read))]
    cw = (w - 4) // len(cells)
    for i, (lab, val) in enumerate(cells):
        W.kv(ctx, sy + 1, x + 2 + i * cw, lab, val, w=cw - 1)


def side(ctx):
    out = ctx.store.series(1800, 30, lambda c: c.usage.output)
    inn = ctx.store.series(1800, 30, lambda c: c.usage.input + c.usage.cache_write)
    return out, "out %s/m" % ftok(out[-1]), "in %s/m" % ftok(inn[-1])


PAGE = Page("traffic", "Traffic", "5", render, side, manual_topic="Traffic")
