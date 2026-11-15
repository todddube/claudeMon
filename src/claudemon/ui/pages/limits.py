"""Pages 7 and 8, Session limit and Weekly limit: one module draws both windows."""

import curses
import time
from datetime import datetime

from claudemon.core.fmt import fclock, fdate, fdur, ftok
from claudemon.sources.limits import WINDOWS
from claudemon.ui import widgets as W
from claudemon.ui.draw import Canvas, clip
from claudemon.ui.pages import Page


def render(ctx, key, y, x, h, w):
    scr = ctx.scr
    cfg = WINDOWS[key]
    f = ctx.forecasts.get(key)
    weekly = key == "seven_day"
    scr.put(y, x + 1, "%s limit" % cfg["label"], ctx.T("title"), extra=curses.A_BOLD)
    if not f or f.pct is None:
        if ctx.not_reported(key):
            scr.box(y + 1, x, h - 1, w, "%s limit: not reported" % cfg["label"])
            lines = ["The tap is working, but Claude Code reports no %s limit for this account;" % cfg["label"].lower(),
                     "it reports only the other window. This page fills in if one starts being reported."]
            for i, ln in enumerate(lines):
                scr.put(y + 3 + i, x + 3, ln, ctx.T("fg"), maxw=w - 6)
            return
        W.tap_callout(ctx, y + 1, x, h - 1, w, "%s limit" % cfg["label"])
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
                cv.vline_cells(X // 2, "░", ctx.T("border"))
    # projections: rate (dashed), worst / best (dotted fan)
    x_now, y_now = px(f.observed), py(f.pct)
    for rate, col, dash in ((f.best, ctx.T("dim"), 1), (f.worst, ctx.T("warn"), 1), (f.rate, ctx.T("crit"), 3)):
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
                    cv.text[(r, col_i)] = ("╱", ctx.T("crit"))
        lab = "full ≈ %s" % fclock(eta, weekly)
        cv.label(max(0, min(cv.cols - len(lab), c0 - len(lab) - 1)), 0, lab, ctx.T("crit"))
    ncol = int(x_now) // 2
    cv.vline_cells(min(cv.cols - 1, ncol), "┊", ctx.T("info"))
    cv.render(scr, cy, cx, grid=("┈", max(2, ch_h // 4), ctx.T("border")))
    for frac in (1.0, 0.5, 0.0):
        scr.put(cy + int((1 - frac) * (ch_h - 1)), x + 1, ("%d%%" % (frac * 100)).rjust(4), ctx.T("dim"))
    # time axis
    ticks = 6 if not weekly else 7
    ay = cy + ch_h
    for i in range(ticks + 1):
        t = start + i * (end - start) / ticks
        lab = datetime.fromtimestamp(t).strftime("%a" if weekly else "%H:%M")
        tx = cx + int(i / ticks * (cw - 1))
        scr.put(ay, min(tx, cx + cw - len(lab)), lab, ctx.T("dim"))
    # now + forecast boxes
    fy = y + h - foot
    scr.box(fy, x, foot, 34, "Now")
    unit, uname = cfg["unit"], cfg["unit_name"]
    W.kv(ctx, fy + 1, x + 2, "Used", "%.0f%%" % f.pct, scr.level_color(f.pct / 100), 10)
    scr.gauge(fy + 3, x + 2, 28, f.pct / 100)
    W.kv(ctx, fy + 4, x + 2, "Rate", ("%.1f %%/%s" % (f.rate * unit, uname)) if f.rate else "—", w=14)
    if not weekly:
        W.kv(ctx, fy + 4, x + 17, "Session rate", ("%.0f %%/5h" % (f.rate * 5 * 3600)) if f.rate else "—", w=15)
    else:
        W.kv(ctx, fy + 4, x + 17, "Resets", fclock(f.resets, True), w=15)
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
        col = ctx.T("crit") if lab == "Projected" and val not in ("∞", "after reset") else ctx.T("fg")
        W.kv(ctx, fy + 1, bx + 2 + i * 16, lab, val, col, 15)
    W.kv(ctx, fy + 1, bx + 50, "Resets in", fdur((f.resets or now) - now), w=14)
    gy = fy + 4
    if f.gaps:
        scr.put(gy, bx + 2, "Unattributed jumps (usage seen while this machine was silent):", ctx.T("warn"))
        for t0, t1, dp, local in f.gaps[-2:]:
            gy += 1
            scr.put(gy, bx + 4, clip("+%.0f%%  %s → %s   local tokens then: %s" % (dp, fclock(t0, weekly), fclock(t1, weekly), ftok(local or 0)), bw - 6), ctx.T("fg"))
    else:
        scr.put(gy, bx + 2, "Projected = recent rate · Worst = busiest slice · Best = average since period start", ctx.T("dim"))
        scr.put(gy + 1, bx + 2, "Gaps over 15 min are excluded from rates and marked ░ on the chart.", ctx.T("dim"))


def side(ctx, key):
    f = ctx.forecasts.get(key)
    if not f or f.pct is None:
        if ctx.not_reported(key):
            return [], "n/a", "not reported"
        return [], "no data", "⚡ install tap" if not ctx.tap_ok else "waiting for data"
    pts = [p for _, p in f.points][-30:]
    eta = f.eta(f.rate)
    if eta and f.resets and eta > f.resets:
        line = "resets first"
    else:
        line = "full %s" % fclock(eta, key == "seven_day") if eta else "flat"
    return pts, "%d%%" % round(f.pct), line


def render_session(ctx, y, x, h, w):
    render(ctx, "five_hour", y, x, h, w)


def side_session(ctx):
    return side(ctx, "five_hour")


def render_weekly(ctx, y, x, h, w):
    render(ctx, "seven_day", y, x, h, w)


def side_weekly(ctx):
    return side(ctx, "seven_day")


SESSION = Page("session_limit", "Session limit", "7", render_session, side_session, manual_topic="Session limit")
WEEKLY = Page("weekly_limit", "Weekly limit", "8", render_weekly, side_weekly, manual_topic="Weekly limit")
