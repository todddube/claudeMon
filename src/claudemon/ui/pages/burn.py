"""Page 1, Token burn: tokens per minute per session (or overall), and who is working now."""

import curses
import time
from collections import defaultdict

from claudemon.core.fmt import fpct, ftok
from claudemon.sources.store import IDLE, NEEDS_YOU, WORKING, short_model
from claudemon.ui import widgets as W
from claudemon.ui.draw import Canvas, clip
from claudemon.ui.pages import Page
from claudemon.ui.widgets import STATE_BADGE


def render(ctx, y, x, h, w):
    scr = ctx.scr
    scr.put(y, x + 1, "Token burn", ctx.T("title"), extra=curses.A_BOLD)
    tx = x + 14
    tx += W.span_toggle(ctx, y, tx)
    tx_end = tx + W.toggles(ctx, y, tx, "Show", ["Sessions", "Overall"], 1 if ctx.overall else 0, "o")
    sessions = ctx.session_list()
    now = time.time()
    summary_h = 7
    gy, gh = y + 1, h - summary_h - 1
    if ctx.overall or not sessions:
        scr.box(gy, x, gh, w, "All sessions · tokens / min", "output overlay")
        n = W.nbuckets(ctx, w - 2)
        tot = W.per_min(ctx, ctx.store.series(ctx.span, n, lambda c: c.usage.total))
        out = W.per_min(ctx, ctx.store.series(ctx.span, n, lambda c: c.usage.output))
        top = W.chart(ctx, gy + 1, x + 1, gh - 2, w - 2, tot)
        if top:
            cv = Canvas(w - 2, gh - 2)
            vmax = max(out) or 1
            prev = None
            for px in range(cv.w):
                v = out[min(len(out) - 1, px * len(out) // cv.w)]
                py = int(v / vmax * (cv.h - 1))
                if prev is not None:
                    cv.line(px - 1, prev, px, py, ctx.T("info"))
                prev = py
            cv.render(scr, gy + 1, x + 1)
    else:
        cols = max(1, min(len(sessions), w // 36))
        rows = -(-len(sessions) // cols)
        ph = max(6, gh // max(1, rows))
        visible_rows = max(1, gh // ph)
        sel = ctx.selected(sessions)
        first_row = max(0, ctx.sel // cols - visible_rows + 1)
        pw = w // cols
        n = W.nbuckets(ctx, pw - 2)
        series = {s.sid: W.per_min(ctx, ctx.store.series(ctx.span, n, lambda c: c.usage.total, [s])) for s in sessions}
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
            scr.put(py, px + pw - 3 - len(text), text, ctx.T(role), extra=curses.A_BOLD if state == NEEDS_YOU else 0)
            W.chart(ctx, py + 1, px + 1, ph - 3, pw - 3, series[s.sid], vmax=vmax, scale_fmt=None)
            used, size = s.context()
            info = "%s · %s  ctx %s  %s/m" % (short_model(s.model), s.effort or "?", fpct(used / size), ftok(series[s.sid][-1] if series[s.sid] else 0))
            loops = s.loops()
            scr.put(py + ph - 2, px + 2, clip(info, pw - 6), ctx.T("dim"))
            if loops:
                tag = " ⟲%d " % len(loops)
                scr.put(py + ph - 2, px + pw - 3 - len(tag), tag, ctx.T("bg") if ctx.T("bg") >= 0 else 16, ctx.T("crit"), curses.A_BOLD)
        if x + w - 12 > tx_end:                      # not on top of the toggles in a narrow window
            scr.put(gy - 1, x + w - 12, "max %s/m" % ftok(vmax), ctx.T("dim"))

    # summary
    sy = y + h - summary_h
    scr.box(sy, x, summary_h, w, "Now")
    burn = ctx.store.series(60, 1, lambda c: c.usage.total)[0]
    outn = ctx.store.series(60, 1, lambda c: c.usage.output)[0]
    live = ctx.store.live_sessions()
    groups = defaultdict(list)
    for s in live:
        groups[s.state(now)].append(s.name)
    loops = sum(len(s.loops()) for s in live)
    cells = [("Burn now", ftok(burn) + "/min", None), ("Output now", ftok(outn) + "/min", None),
             ("Working", str(len(groups[WORKING])), ctx.T("ok")), ("Needs you", str(len(groups[NEEDS_YOU])), ctx.T("warn") if groups[NEEDS_YOU] else None),
             ("Idle", str(len(groups[IDLE])), ctx.T("dim")), ("Loops", str(loops), ctx.T("crit") if loops else None)]
    cw = max(12, (w - 4) // len(cells))
    for i, (lab, val, col) in enumerate(cells):
        W.kv(ctx, sy + 1, x + 2 + i * cw, lab, val, col, cw - 1)
    ly = sy + 3
    for state in (WORKING, NEEDS_YOU, IDLE):
        text, role = STATE_BADGE[state]
        scr.put(ly, x + 2, text.split(" ", 1)[1], ctx.T(role))
        scr.put(ly, x + 14, clip(" · ".join(groups[state]) or "—", w - 17), ctx.T("fg"))
        ly += 1


def side(ctx):
    s = ctx.store.series(1800, 30, lambda c: c.usage.total)
    live = ctx.store.live_sessions()
    return s, "%d sessions" % len(live), "%s tok/min" % ftok(s[-1] if s else 0)


PAGE = Page("burn", "Token burn", "1", render, side, manual_topic="Token burn")
