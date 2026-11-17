"""Page 0, Inspect: everything about the selected session."""

import curses
import os
import time
from collections import Counter

from claudemon.core.fmt import fdur, fpct, ftok
from claudemon.sources.store import short_model
from claudemon.ui import widgets as W
from claudemon.ui.draw import clip
from claudemon.ui.pages import Page
from claudemon.ui.widgets import SPANS


def render(ctx, y, x, h, w):
    scr = ctx.scr
    now = time.time()
    sessions = ctx.session_list()
    s = ctx.selected(sessions)
    scr.put(y, x + 1, "Inspect", ctx.T("title"), extra=curses.A_BOLD)
    scr.put(y, x + 11, "↑↓ to switch session (%d of %d)" % (ctx.sel + 1, len(sessions)) if s else "", ctx.T("dim"))
    if not s:
        scr.box(y + 1, x, h - 1, w, "No sessions")
        return
    lw = min(48, w // 2)
    info_h = 17
    scr.box(y + 1, x, info_h, lw, s.name, focus=True)
    used, size = s.context()
    tot = s.t.totals()
    dur = (s.t.last_ts or now) - (s.t.started or now)
    rows = [
        ("State", None), ("Title", s.t.title or "—"), ("Project", s.project), ("Branch", s.t.git_branch or "—"),
        ("Model", "%s  (%s)" % (short_model(s.model), s.model or "?")), ("Effort", s.effort or "—"),
        ("Mode", s.t.permission_mode or "—"), ("PID", str((s.live or {}).get("pid", "—"))),
        ("Running", fdur(dur)), ("Tokens", "%s total · %s out" % (ftok(tot.total), ftok(tot.output))),
        ("Cost", ("$%.2f" % s.cost()) if s.cost() is not None else "— (tap)"),
        ("Compacts", "%d   API errors %d" % (s.t.compactions, s.t.api_errors)),
        ("Context", None), ("Prompt", s.t.last_prompt or "—"),
    ]
    for i, (k, v) in enumerate(rows):
        ry = y + 2 + i
        scr.put(ry, x + 2, k, ctx.T("dim"))
        if k == "State":
            W.badge(ctx, ry, x + 12, s.state(now))
            st = s.t.stuck_tool(now)
            if st:
                scr.put(ry, x + 26, clip("%s waiting %s" % (st[0], fdur(st[1])), lw - 28), ctx.T("warn") if st[1] > 30 else ctx.T("dim"))
        elif k == "Context":
            scr.gauge(ry, x + 12, lw - 26, used / size)
            scr.put(ry, x + lw - 13, "%s %s" % (fpct(used / size), ftok(used)), scr.level_color(used / size))
        else:
            scr.put(ry, x + 12, clip(v, lw - 14), ctx.T("fg"))
    # right: burn chart
    rx, rw = x + lw, w - lw
    ch = 8
    scr.box(y + 1, rx, ch, rw, "Tokens / min · main + subagents", SPANS[ctx.span_i][1])
    n = W.nbuckets(ctx, rw - 2)
    W.chart(ctx, y + 2, rx + 1, ch - 2, rw - 2, W.per_min(ctx, ctx.store.series(ctx.span, n, lambda c: c.usage.total, [s])))
    # tools
    ty = y + 1 + ch
    scr.box(ty, rx, info_h - ch, rw, "Top tools")
    tools = Counter()
    for t, _ in s.transcripts():
        tools.update(t.tools)
    tmax = max(tools.values()) if tools else 1
    for i, (name, n_) in enumerate(tools.most_common(info_h - ch - 2)):
        scr.put(ty + 1 + i, rx + 2, clip(name, 14), ctx.T("fg"))
        scr.gauge(ty + 1 + i, rx + 17, max(5, rw - 26), n_ / tmax, color=ctx.T("series")[i % len(ctx.T("series"))], empty=" ")
        scr.put(ty + 1 + i, rx + rw - 7, str(n_).rjust(5), ctx.T("dim"))
    # subagents
    ay = y + 1 + info_h
    loops = s.loops()
    loop_h = min(len(loops) + 3, 7) if loops else 3
    ah = h - info_h - 1 - loop_h
    scr.box(ay, x, ah, w, "Subagents", "%d" % len(s.agents))
    heads = [("Agent", 34), ("Type", 16), ("Model", 11), ("Effort", 7), ("Out", 7), ("Tok/min", 8), ("Status", 10)]
    cx = x + 2
    for name, cw in heads:
        scr.put(ay + 1, cx, name, ctx.T("dim"), extra=curses.A_UNDERLINE)
        cx += cw + 1
    agents = sorted(list(s.agents.values()), key=lambda a: (a.finished, -(a.t.last_ts or 0)))
    for i, a in enumerate(agents[: max(0, ah - 3)]):
        ry = ay + 2 + i
        u = a.t.totals()
        recent = a.t.totals(now - 300)
        cx = x + 2
        vals = [clip(a.label, 33), clip(a.meta.get("agentType", "?"), 15), short_model(a.t.model), (a.t.effort or "—")[:6],
                ftok(u.output), ftok(recent.total / 5)]
        for (name, cw), v in zip(heads, vals):
            scr.put(ry, cx, v, ctx.T("fg") if name == "Agent" else ctx.T("dim"))
            cx += cw + 1
        scr.put(ry, cx, "done" if a.finished else "running", ctx.T("dim") if a.finished else ctx.T("ok"))
    if not agents:
        scr.put(ay + 2, x + 2, "No subagents in this session.", ctx.T("dim"))
    # loops
    ly = ay + ah
    scr.box(ly, x, loop_h, w, "Loop watch", "files read ≥3× with no edit between", title_fg=ctx.T("crit") if loops else None)
    if not loops:
        scr.put(ly + 1, x + 2, "No re-read loops detected. ", ctx.T("ok"))
    for i, (path, worst, current, a) in enumerate(loops[: loop_h - 2]):
        who = ("subagent " + clip(a.label, 18)) if a else "main"
        home = os.path.expanduser("~")
        p = path.replace(home, "~")
        scr.put(ly + 1 + i, x + 2, "⟲ %d×" % worst, ctx.T("crit"), extra=curses.A_BOLD)
        scr.put(ly + 1 + i, x + 9, clip(p, w - 40), ctx.T("fg"))
        scr.put(ly + 1 + i, x + w - 30, clip("%s · now %d since edit" % (who, current), 28), ctx.T("dim"))


def side(ctx):
    s = ctx.selected()
    if not s:
        return [], "no session", ""
    n_loops = len(s.loops())
    return (ctx.store.series(1800, 30, lambda c: c.usage.output, [s]), clip(s.name, 12),
            "%d agents · %d loops" % (len(s.agents), n_loops))


PAGE = Page("inspect", "Inspect", "0", render, side, manual_topic="Inspect")
