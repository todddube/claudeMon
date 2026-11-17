"""Page 3, Context: how full each session's context window is, and its history."""

import curses
import time

from claudemon.core.fmt import fpct, ftok
from claudemon.sources.store import short_model
from claudemon.ui import widgets as W
from claudemon.ui.draw import clip
from claudemon.ui.pages import Page


def render(ctx, y, x, h, w):
    scr = ctx.scr
    scr.put(y, x + 1, "Context", ctx.T("title"), extra=curses.A_BOLD)
    W.span_toggle(ctx, y, x + 11)
    sessions = ctx.session_list()
    sel = ctx.selected(sessions)
    scr.box(y + 1, x, h - 1, w, "Context window per session", "used / window")
    hdr = y + 2
    cols = [("Session", 22), ("Model", 11), ("Window", 0), ("Used", 15), ("Compact", 8), ("History", 22)]
    gauge_w = max(10, w - 4 - sum(c[1] for c in cols) - len(cols))
    cx = x + 2
    for name, cw in cols:
        scr.put(hdr, cx, name, ctx.T("dim"), extra=curses.A_UNDERLINE)
        cx += (cw or gauge_w) + 1
    row = hdr + 1
    for s in sessions:
        if row >= y + h - 1:
            break
        used, size = s.context()
        frac = used / size if size else 0
        bg = ctx.T("hl_bg") if s is sel else None
        if bg is not None:
            scr.fill(row, x + 1, 1, w - 2, bg)
        cx = x + 2
        scr.put(row, cx, clip(s.name, 21), ctx.T("fg"), bg)
        cx += 23
        scr.put(row, cx, short_model(s.model), ctx.T("dim"), bg)
        cx += 12
        scr.gauge(row, cx, gauge_w, frac, color=None)
        cx += gauge_w + 1
        scr.put(row, cx, "%s %s" % (fpct(frac).rjust(4), ftok(used) + "/" + ftok(size)), scr.level_color(frac), bg)
        cx += 16
        scr.put(row, cx, str(s.t.compactions).rjust(5), ctx.T("warn") if s.t.compactions else ctx.T("dim"), bg)
        cx += 9
        # the largest prompt per bucket: summing would overstate context size
        hist = [0.0] * 22
        t0 = time.time() - ctx.span
        for c, a in s.all_calls(t0):
            if a is None:
                i = min(21, int((c.ts - t0) / (ctx.span / 22)))
                hist[i] = max(hist[i], c.usage.prompt)
        scr.spark(row, cx, hist, 22, vmax=size)
        row += 1
    if sel and row + 6 < y + h - 1:
        row += 1
        ch = y + h - 2 - row
        scr.put(row, x + 2, "%s · context size per call" % sel.name, ctx.T("title"))
        calls = sorted((c for c, a in sel.all_calls(time.time() - ctx.span) if a is None), key=lambda c: c.ts)
        vals = [c.usage.prompt for c in calls]
        W.chart(ctx, row + 1, x + 2, ch - 1, w - 4, vals, vmax=sel.context()[1])


def side(ctx):
    fr = [s.context()[0] / s.context()[1] for s in ctx.store.live_sessions() if s.context()[0]]
    if not fr:
        return [], "no live context", ""
    return [f * 100 for f in fr], "fullest %s" % fpct(max(fr)), "average %s" % fpct(sum(fr) / len(fr))


PAGE = Page("context", "Context", "3", render, side, manual_topic="Context")
