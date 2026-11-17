"""Page 4, Prompt cache: hit ratio, cache writes, and which sessions are warm."""

import curses
import time

from claudemon.core.fmt import fdur, fpct, ftok
from claudemon.ui import widgets as W
from claudemon.ui.draw import clip
from claudemon.ui.pages import Page

MISS_FLOOR = 2000      # a call this big with almost no cache read counts as a miss


def render(ctx, y, x, h, w):
    scr = ctx.scr
    now = time.time()
    scr.put(y, x + 1, "Prompt cache", ctx.T("title"), extra=curses.A_BOLD)
    W.span_toggle(ctx, y, x + 16)
    sessions = ctx.session_list()
    table_h = min(len(sessions) + 3, max(5, h // 3))
    chart_h = max(4, (h - table_h - 5) * 2 // 3)
    writes_h = max(4, h - table_h - 5 - chart_h)
    n = W.nbuckets(ctx, w - 2)
    reads = ctx.store.series(ctx.span, n, lambda c: c.usage.cache_read)
    prompts = ctx.store.series(ctx.span, n, lambda c: c.usage.prompt)
    ratio = [r / p if p else 0 for r, p in zip(reads, prompts)]
    # carry the last ratio across empty buckets so the line does not drop to zero
    last = 0
    for i, (r, p) in enumerate(zip(ratio, prompts)):
        if p:
            last = r
        else:
            ratio[i] = last
    scr.box(y + 1, x, chart_h, w, "Hit ratio", "100%")
    W.chart(ctx, y + 2, x + 1, chart_h - 2, w - 2, ratio, vmax=1.0, scale_fmt=None)
    wy = y + 1 + chart_h
    scr.box(wy, x, writes_h, w, "Cache writes per minute")
    W.chart(ctx, wy + 1, x + 1, writes_h - 2, w - 2, W.per_min(ctx, ctx.store.series(ctx.span, n, lambda c: c.usage.cache_write)), color=ctx.T("info"))
    sy = wy + writes_h
    u5 = ctx.store.totals(now - 300)
    live = ctx.store.live_sessions()
    warm = sum(1 for s in live if (s.t.cache_expires() or 0) > now)
    misses = sum(1 for _, c, _ in ctx.store.calls(now - 300) if c.usage.prompt > MISS_FLOOR and c.usage.cache_read < 0.1 * c.usage.prompt)
    cells = [("Hit ratio", fpct(u5.cache_read / u5.prompt) if u5.prompt else "—"), ("Warm", "%d of %d" % (warm, len(live))),
             ("Reads now", ftok(u5.cache_read / 5) + "/min"), ("Writes now", ftok(u5.cache_write / 5) + "/min"), ("Misses, 5 min", str(misses))]
    cw = (w - 4) // len(cells)
    for i, (lab, val) in enumerate(cells):
        W.kv(ctx, sy, x + 2 + i * cw, lab, val, w=cw - 1)
    ty = sy + 2
    scr.box(ty, x, h - (ty - y), w, "Sessions")
    bar_w = max(8, w - 82)
    heads = [("Session", 24), ("Cache", 8), ("Expires", 8), ("Time left", bar_w), ("Hit", 5), ("Miss", 5), ("Re-cache if cold", 17)]
    cx = x + 2
    for name, cw_ in heads:
        scr.put(ty + 1, cx, name, ctx.T("dim"), extra=curses.A_UNDERLINE)
        cx += cw_ + 1
    sel = ctx.selected(sessions)
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
        bg = ctx.T("hl_bg") if s is sel else None
        if bg is not None:
            scr.fill(row, x + 1, 1, w - 2, bg)
        cx = x + 2
        scr.put(row, cx, clip(s.name, 23), ctx.T("fg"), bg)
        cx += 25
        scr.put(row, cx, "● Warm" if is_warm else "○ Cold", ctx.T("ok") if is_warm else ctx.T("dim"), bg)
        cx += 9
        scr.put(row, cx, fdur(left) if is_warm else "—", ctx.T("fg"), bg)
        cx += 9
        frac = (left / s.t.cache_ttl) if is_warm else 0
        scr.gauge(row, cx, bar_w, frac, color=scr.level_color(1 - frac) if is_warm else ctx.T("border"))
        cx += bar_w + 1
        scr.put(row, cx, fpct(hit).rjust(4), ctx.T("fg"), bg)
        cx += 6
        scr.put(row, cx, str(miss).rjust(4), ctx.T("warn") if miss else ctx.T("dim"), bg)
        cx += 6
        scr.put(row, cx, ftok(s.context()[0]).rjust(8) + ("  1h TTL" if s.t.cache_ttl == 3600 else "  5m TTL"), ctx.T("dim"), bg)
        row += 1


def side(ctx):
    now = time.time()
    live = ctx.store.live_sessions()
    warm = sum(1 for s in live if (s.t.cache_expires() or 0) > now)
    u = ctx.store.totals(now - 300)
    hit = u.cache_read / u.prompt if u.prompt else None
    sp = ctx.store.series(1800, 30, lambda c: c.usage.cache_read / c.usage.prompt * 100 if c.usage.prompt else 0)
    return sp, "%d of %d warm" % (warm, len(live)), "hit %s" % fpct(hit)


PAGE = Page("cache", "Prompt cache", "4", render, side, manual_topic="Prompt cache")
