"""Page 6, Models: output per model (or model and effort), and who used each."""

import curses
import time
from collections import Counter, defaultdict

from claudemon.core.fmt import fpct, ftok
from claudemon.sources.store import short_model
from claudemon.ui import widgets as W
from claudemon.ui.draw import clip
from claudemon.ui.pages import Page
from claudemon.ui.widgets import SPANS


def render(ctx, y, x, h, w):
    scr = ctx.scr
    now = time.time()
    scr.put(y, x + 1, "Models", ctx.T("title"), extra=curses.A_BOLD)
    tx = x + 10 + W.span_toggle(ctx, y, x + 10)
    W.toggles(ctx, y, tx, "Show", ["Model", "Model · effort"], 1 if ctx.by_effort else 0, "e")
    key = (lambda c: "%s · %s" % (short_model(c.model), c.effort or "?")) if ctx.by_effort else (lambda c: short_model(c.model))
    out = Counter()
    effort = defaultdict(Counter)
    users = defaultdict(Counter)
    think = Counter()
    for s, c, a in ctx.store.calls(now - ctx.span):
        k = key(c)
        out[k] += c.usage.output
        think[k] += c.usage.thinking
        effort[k][c.effort or "?"] += c.usage.output
        users[k][s.name + (" (subagent)" if a else "")] += c.usage.output
    if not out:
        scr.box(y + 1, x, h - 1, w, "Models")
        scr.put(y + 3, x + 3, "No API calls in the last %s. Try a longer range with g." % SPANS[ctx.span_i][1], ctx.T("dim"))
        return
    models = [m for m, _ in out.most_common(4)]
    total = sum(out.values())
    foot = 6
    pw = w // len(models)
    n = W.nbuckets(ctx, pw - 2)
    for i, m in enumerate(models):
        px = x + i * pw
        col = ctx.T("series")[i % len(ctx.T("series"))]
        vals = W.per_min(ctx, ctx.store.series(ctx.span, n, lambda c, m=m: c.usage.output if key(c) == m else 0))
        scr.box(y + 1, px, h - foot - 1, pw - 1, m, fpct(out[m] / total), title_fg=col)
        W.chart(ctx, y + 2, px + 1, h - foot - 5, pw - 3, vals, color=col)
        ef = effort[m]
        ef_t = sum(ef.values()) or 1
        scr.put(y + h - foot - 3, px + 2, clip("Effort " + " · ".join("%s %s" % (e, fpct(v / ef_t)) for e, v in ef.most_common()), pw - 5), ctx.T("fg"))
        us = users[m]
        us_t = sum(us.values()) or 1
        scr.put(y + h - foot - 2, px + 2, clip("Used by " + ", ".join("%s %s" % (u, fpct(v / us_t)) for u, v in us.most_common(3)), pw - 5), ctx.T("dim"))
    sy = y + h - foot
    scr.box(sy, x, foot, w, "Output share · last %s" % SPANS[ctx.span_i][1])
    bx = x + 2
    bw = w - 4
    for i, m in enumerate(out.most_common()):
        seg = max(1, round(m[1] / total * bw))
        col = ctx.T("series")[i % len(ctx.T("series"))]
        scr.put(sy + 1, bx, "█" * min(seg, x + 2 + bw - bx), col)
        bx += seg
    lx = x + 2
    for i, (m, v) in enumerate(out.most_common()):
        col = ctx.T("series")[i % len(ctx.T("series"))]
        lx += scr.put(sy + 2, lx, "■ ", col)
        lx += scr.put(sy + 2, lx, "%s %s   " % (m, fpct(v / total)), ctx.T("fg"))
    tt = sum(think.values())
    W.kv(ctx, sy + 3, x + 2, "Thinking share of output", fpct(tt / total) if total else "—", w=30)
    W.kv(ctx, sy + 3, x + 34, "Output tokens", ftok(total), w=20)


def side(ctx):
    c = Counter()
    for _, call, _ in ctx.store.calls(time.time() - 3600):
        c[short_model(call.model)] += call.usage.output
    if not c:
        return [], "no calls in 1h", ""
    top, n = c.most_common(1)[0]
    return ctx.store.series(1800, 30, lambda c: c.usage.output), "%d models" % len(c), "%s %s" % (top, fpct(n / sum(c.values())))


PAGE = Page("models", "Models", "6", render, side, manual_topic="Models")
