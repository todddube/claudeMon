"""Page 9, Projects: each project's share of this week's usage."""

import curses
import time
from collections import Counter, defaultdict
from datetime import datetime

from claudemon.core.fmt import fclock, fpct, ftok
from claudemon.sources.store import short_model, weight
from claudemon.ui import widgets as W
from claudemon.ui.draw import clip
from claudemon.ui.pages import Page


def render(ctx, y, x, h, w):
    scr = ctx.scr
    now = time.time()
    f7 = ctx.forecasts.get("seven_day")
    start = (f7.resets - 7 * 86400) if f7 and f7.resets else now - 7 * 86400
    scr.put(y, x + 1, "Projects", ctx.T("title"), extra=curses.A_BOLD)
    scr.put(y, x + 12, "%s → now" % fclock(start, True), ctx.T("dim"))
    by_proj = Counter()
    by_sub = defaultdict(Counter)
    days = defaultdict(lambda: [0.0] * 7)
    toks = 0
    for s, c, a in ctx.store.calls(start):
        wt = weight(c.usage)
        by_proj[s.project] += wt
        by_sub[s.project][short_model(c.model)] += wt
        d = int((c.ts - start) // 86400)
        if 0 <= d < 7:
            days[s.project][d] += wt
        toks += c.usage.total
    total = sum(by_proj.values())
    W.kv(ctx, y + 1, x + 2, "Weekly limit used", "%d%%" % round(f7.pct) if f7 and f7.pct is not None else "—", w=20)
    W.kv(ctx, y + 1, x + 24, "Tokens", ftok(toks), w=14)
    W.kv(ctx, y + 1, x + 40, "Projects", str(len(by_proj)), w=10)
    scr.box(y + 4, x, h - 4 - 5, w, "Share of usage", "cost-weighted tokens")
    if not total:
        scr.put(y + 6, x + 3, "No usage recorded in this period.", ctx.T("dim"))
        return
    dname = [datetime.fromtimestamp(start + i * 86400).strftime("%a")[:2] for i in range(7)]
    bar_w = max(10, w - 62)
    row = y + 5
    scr.put(row, x + 2, "Project", ctx.T("dim"), extra=curses.A_UNDERLINE)
    scr.put(row, x + 24 + bar_w + 1, "share  of wk", ctx.T("dim"), extra=curses.A_UNDERLINE)
    scr.put(row, x + 24 + bar_w + 15, " ".join(dname), ctx.T("dim"))
    row += 1
    for i, (proj, v) in enumerate(by_proj.most_common()):
        if row >= y + h - 6:
            break
        col = ctx.T("series")[i % len(ctx.T("series"))]
        share = v / total
        scr.put(row, x + 2, clip(proj, 21), ctx.T("fg"), extra=curses.A_BOLD)
        scr.gauge(row, x + 24, bar_w, share, color=col)
        wk = (" ≈%d%%" % round(share * f7.pct)) if f7 and f7.pct is not None else ""
        scr.put(row, x + 24 + bar_w + 1, ("%s" % fpct(share)).rjust(5) + wk.rjust(7), ctx.T("fg"))
        dv = days[proj]
        dm = max(dv) or 1
        for d in range(7):
            ch = " ▁▂▃▄▅▆▇█"[int(round(dv[d] / dm * 8))] if dv[d] else "·"
            scr.put(row, x + 24 + bar_w + 15 + d * 3, ch * 2, col)
        row += 1
        for model, mv in by_sub[proj].most_common(2):
            if row >= y + h - 6 or len(by_sub[proj]) < 2:
                break
            scr.put(row, x + 4, clip(model, 19), ctx.T("dim"))
            scr.gauge(row, x + 24, bar_w, mv / total, color=col, empty=" ")
            scr.put(row, x + 24 + bar_w + 1, fpct(mv / total).rjust(5), ctx.T("dim"))
            row += 1
    cy = y + h - 5
    scr.box(cy, x, 5, w, "Composition")
    bx, bw = x + 2, w - 4
    lx = x + 2
    for i, (proj, v) in enumerate(by_proj.most_common()):
        col = ctx.T("series")[i % len(ctx.T("series"))]
        seg = max(1, round(v / total * bw))
        scr.put(cy + 1, bx, "█" * max(0, min(seg, x + 2 + bw - bx)), col)
        bx += seg
        if i < 6:
            lx += scr.put(cy + 2, lx, "■ ", col)
            lx += scr.put(cy + 2, lx, "%s %s  " % (proj, fpct(v / total)), ctx.T("fg"))


def side(ctx):
    c = Counter()
    for s, call, _ in ctx.store.calls(time.time() - 7 * 86400):
        c[s.project] += weight(call.usage)
    if not c:
        return [], "no projects", ""
    top, n = c.most_common(1)[0]
    return [], "%s ≈ %s" % (top, fpct(n / sum(c.values()))), "%d projects (7d)" % len(c)


PAGE = Page("projects", "Projects", "9", render, side, manual_topic="Projects")
