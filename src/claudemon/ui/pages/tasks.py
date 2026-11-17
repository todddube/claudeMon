"""Page 2, Tasks: the tree of everything Claude is doing now (built by tasks_tree), and its details."""

import curses
import textwrap
import time

from claudemon.core.fmt import fclock, fdur, fpct, ftok
from claudemon.sources.store import IDLE, NEEDS_YOU, WORKING, short_model
from claudemon.ui import widgets as W
from claudemon.ui.draw import clip
from claudemon.ui.pages import Page
from claudemon.ui.pages import tasks_tree as tasks_mod

ID = "tasks"
STATE_ROLE_TUI = {WORKING: "ok", NEEDS_YOU: "warn", IDLE: "dim"}


class State:
    """The Tasks page's own state: the tree, its counts, the cursor and the scroll."""

    def __init__(self):
        self.rows, self.counts = [], dict(sessions=0, tools=0, agents=0, bg=0, procs=0, queued=0)
        self.i, self.key, self.top = 0, None, 0


def sel_idxs(ctx):
    st = ctx.page_state[ID]
    return [i for i, r in enumerate(st.rows) if r.kind != "header"]


def move(ctx, d):
    st = ctx.page_state[ID]
    idxs = sel_idxs(ctx)
    if not idxs:
        return
    pos = idxs.index(st.i) if st.i in idxs else 0
    st.i = idxs[(pos + d) % len(idxs)]
    r = st.rows[st.i]
    st.key = (r.depth, r.kind, r.text)


def open_row(ctx):
    st = ctx.page_state[ID]
    if not st.rows or st.i >= len(st.rows):
        return
    r = st.rows[st.i]
    s = r.obj if r.kind == "session" else (r.obj[0] if r.kind in ("agent", "bg", "queued") else None)
    if s is not None:
        ctx.go_page("inspect", s.sid)


def detail(ctx, r, width):
    """Detail lines for a Tasks row: [(label, text, role)]."""
    now = time.time()
    L = []

    def kv(k, v, role="fg"):
        L.append((k, str(v), role))

    def para(text, role="fg", label=""):
        for i, ln in enumerate(textwrap.wrap(" ".join(str(text).split()), max(10, width)) or [""]):
            L.append((label if i == 0 else "", ln, role))

    if r.kind == "session":
        s = r.obj
        used, size = s.context()
        t = s.t.totals()
        kv("Session", s.name, "title")
        kv("State", s.state(now), STATE_ROLE_TUI.get(s.state(now), "dim"))
        kv("PID", (s.live or {}).get("pid", "—"))
        kv("Folder", (s.live or {}).get("cwd") or s.t.cwd or "—")
        kv("Model", "%s · %s" % (short_model(s.model), s.effort or "?"))
        kv("Mode", s.t.permission_mode or "—")
        kv("Context", "%s of %s  (%s)" % (ftok(used), ftok(size), fpct(used / size)))
        kv("Tokens", "%s total · %s out" % (ftok(t.total), ftok(t.output)))
        kv("Running", fdur((s.t.last_ts or now) - (s.t.started or now)))
        kv("Subagents", "%d live of %d" % (sum(1 for a in list(s.agents.values()) if not a.finished), len(s.agents)))
        if s.t.last_prompt:
            para(s.t.last_prompt, "dim", "Last prompt")
        for tid, (name, ts, summ) in list(s.t.pending_tools.items()):
            para("%s %s" % (name, summ), "warn", "Waiting on")
    elif r.kind == "tool":
        o = r.obj
        kv("Tool", o["name"], "title")
        kv("Running", fdur(now - o["ts"]) if o["ts"] else "—", "warn" if o["slow"] else "fg")
        if o["slow"]:
            para("Waiting longer than a quick tool should. It may be sitting on a permission prompt for you.", "warn")
        para(o["summary"], "fg", "Detail")
    elif r.kind == "agent":
        s, a = r.obj
        u = a.t.totals()
        kv("Subagent", a.label, "title")
        kv("Type", a.meta.get("agentType", "—"))
        kv("Model", "%s · %s" % (short_model(a.t.model), a.t.effort or "?"))
        kv("Running", fdur(now - (a.t.started or now)))
        kv("Output", ftok(u.output))
        kv("Rate", "%s tok/min" % ftok(a.t.totals(now - 300).total / 5))
        kv("Parent", s.name)
        kv("Agent id", a.id)
        for name, n in a.t.tools.most_common(4):
            kv("Tool use", "%s ×%d" % (name, n), "dim")
        for tid, (name, ts, summ) in list(a.t.pending_tools.items()):
            para("%s %s" % (name, summ), "warn", "Waiting on")
    elif r.kind == "bg":
        s, b = r.obj
        kv("Task", b.id, "title")
        kv("Tool", b.tool)
        kv("Status", b.status, "ok" if b.running else ("dim" if b.status == "completed" else "crit"))
        if b.started:
            kv("Started", fclock(b.started) + "  (%s ago)" % fdur(now - b.started))
        if b.ended:
            kv("Ended", fclock(b.ended))
        kv("Session", s.name)
        if b.summary:
            para(b.summary, "fg", "Command")
        if b.result:
            para(b.result, "dim", "Result")
        tail_lines = tasks_mod.tail(b.output) if b.output else None
        if tail_lines:
            L.append(("Output", "(last lines)", "dim"))
            for ln in tail_lines[-14:]:
                L.append(("", clip(ln, width), "fg"))
        elif b.output:
            L.append(("Output", "file not readable (already cleaned up?)", "dim"))
    elif r.kind in ("proc", "cli"):
        p = r.obj
        kv("Process", p.pid, "title")
        kv("Parent", p.ppid)
        kv("Running", fdur(p.elapsed))
        kv("CPU", "%.1f%%" % p.cpu)
        kv("Memory", tasks_mod.fmem(p.rss))
        kv("Kind", p.kind)
        para(p.args, "fg", "Command")
    elif r.kind == "mcp":
        kv("MCP servers", len(r.obj), "title")
        for p in r.obj:
            para("pid %d  %s  %s" % (p.pid, tasks_mod.fmem(p.rss), p.label), "fg")
        para("MCP servers give Claude extra tools. They idle at near-zero CPU, but each stays in memory "
             "while its session lives.", "dim")
    elif r.kind == "queued":
        s, ts, text = r.obj
        kv("Queued", fdur(now - ts) + " ago" if ts else "—", "warn")
        kv("Session", s.name)
        para(text, "fg", "Prompt")
        para("You typed this while Claude was busy. It is delivered when the current turn allows.", "dim")
    elif r.kind == "desktop":
        main, n, rss, cpu = r.obj
        kv("Claude Desktop", "%d processes" % n, "title")
        kv("Memory", tasks_mod.fmem(rss))
        kv("CPU", "%.1f%%" % cpu)
        kv("Running", fdur(main.elapsed))
        para("Desktop and Cowork sessions are not read directly. Their usage shows up in the account "
             "limits when the tap is installed.", "dim")
    elif r.kind == "job":
        jid, st = r.obj
        kv("Job", st.get("name") or jid, "title")
        kv("State", st.get("state", "?"), "warn" if st.get("state") == "blocked" else "fg")
        kv("Tempo", st.get("tempo", "—"))
        kv("Tokens", ftok(st.get("tokens") or 0))
        kv("Folder", st.get("cwd", "—"))
        if st.get("intent"):
            para(st["intent"], "fg", "Intent")
        if st.get("detail"):
            para(st["detail"], "dim", "Latest")
        if st.get("needs"):
            para(st["needs"], "warn", "Needs you")
        if st.get("suggestedReply"):
            para(st["suggestedReply"], "info", "Suggested")
    elif r.kind == "sched":
        name, desc = r.obj
        kv("Scheduled task", name, "title")
        para(desc or "—", "fg", "What")
        para("Defined in ~/.claude/scheduled-tasks/%s/SKILL.md. Claude runs it on its schedule." % name, "dim")
    else:
        L.append(("", "Select a row with ↑ ↓", "dim"))
    return L


def render(ctx, y, x, h, w):
    st = ctx.page_state[ID]
    scr = ctx.scr
    c = st.counts
    scr.put(y, x + 1, "Tasks", ctx.T("title"), extra=curses.A_BOLD)
    scr.put(y, x + 9, "%d sessions · %d tools running · %d agents · %d background · %d processes · %d queued" % (
        c["sessions"], c["tools"], c["agents"], c["bg"], c["procs"], c["queued"]), ctx.T("dim"))
    lw = max(50, w * 58 // 100)
    rw = w - lw
    bh = h - 1
    scr.box(y + 1, x, bh, lw, "Running now", "↑↓ select · ⏎ inspect", focus=True)
    rows = st.rows
    inner = bh - 2
    if st.i >= len(rows) or (rows and rows[st.i].kind == "header"):
        idxs = sel_idxs(ctx)
        st.i = idxs[0] if idxs else 0
    if st.i < st.top:
        st.top = st.i
    elif st.i >= st.top + inner:
        st.top = st.i - inner + 1
    st.top = max(0, min(st.top, max(0, len(rows) - inner)))
    for n, r in enumerate(rows[st.top:st.top + inner]):
        ry = y + 2 + n
        sel = (st.top + n) == st.i
        bg = ctx.T("hl_bg") if sel else None
        if bg is not None:
            scr.fill(ry, x + 1, 1, lw - 2, bg)
        if r.kind == "header":
            scr.put(ry, x + 2, "── %s " % r.text + "─" * max(0, lw - 8 - len(r.text)), ctx.T("accent"), bg, curses.A_BOLD)
            continue
        ind = 2 + 2 * r.depth
        right = r.right
        scr.put(ry, x + ind, r.icon, ctx.T(r.role), bg, curses.A_BOLD)
        room = lw - ind - 4 - (len(right) + 2 if right else 0)
        scr.put(ry, x + ind + 2, clip(r.text, room), ctx.T(r.role), bg, curses.A_BOLD if r.kind == "session" else 0)
        if right:
            scr.put(ry, x + lw - 2 - len(right), right, ctx.T(r.right_role), bg)
    if not rows:
        scr.put(y + 3, x + 3, "Nothing running.", ctx.T("dim"))
    scr.box(y + 1, x + lw, bh, rw, "Details")
    if rows and st.i < len(rows):
        for n, (label, text, role) in enumerate(detail(ctx, rows[st.i], rw - 18)[:inner]):
            ry = y + 2 + n
            scr.put(ry, x + lw + 2, label, ctx.T("dim"), maxw=14)
            scr.put(ry, x + lw + 16, clip(text, rw - 18), ctx.T(role))


def side(ctx):
    st = ctx.page_state[ID]
    c = st.counts
    return [], "%d tools · %d agents" % (c["tools"], c["agents"]), "%d bg · %d queued" % (c["bg"], c["queued"])


def tick(ctx):
    """Rebuild the tree every tick (on any page, and in mini), keeping the cursor on the same row."""
    st = ctx.page_state[ID]
    st.rows, st.counts = tasks_mod.build(ctx.store)
    for i, r in enumerate(st.rows):
        if st.key == (r.depth, r.kind, r.text):
            st.i = i
            break


def on_key(ctx, key, k):
    """↑↓ move the cursor, ⏎ opens the row's session in Inspect."""
    d = W.updown(key, k)
    if d:
        move(ctx, d)
    elif W.is_enter(key):
        open_row(ctx)
    else:
        return False
    return True


PAGE = Page(ID, "Tasks", "2", render, side, on_key=on_key, tick=tick, manual_topic="Tasks", state=State)
