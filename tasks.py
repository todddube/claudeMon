"""Builds the Tasks tree: everything Claude is doing on this machine right now.

Each row is a Row(depth, icon, text, role, kind, obj, right). `kind` and `obj`
drive the detail pane; `role` is a theme colour role.
"""

import os
import time

from store import IDLE, NEEDS_YOU, WORKING, short_model

RECENT_DONE_S = 600          # finished background tasks stay visible this long
QUICK_TOOL_WARN_S = 45       # a non-long-running tool pending longer than this is flagged


class Row:
    __slots__ = ("depth", "icon", "text", "role", "kind", "obj", "right", "right_role")

    def __init__(self, depth, icon, text, role, kind, obj=None, right="", right_role="dim"):
        self.depth, self.icon, self.text, self.role = depth, icon, text, role
        self.kind, self.obj, self.right, self.right_role = kind, obj, right, right_role


def fdur(s):
    s = int(max(0, s or 0))
    if s >= 86400:
        return "%dd%02dh" % (s // 86400, s % 86400 // 3600)
    if s >= 3600:
        return "%dh%02dm" % (s // 3600, s % 3600 // 60)
    if s >= 60:
        return "%dm%02ds" % (s // 60, s % 60)
    return "%ds" % s


def fmem(kb):
    return "%.0fMB" % (kb / 1024) if kb < 1024 * 1024 else "%.1fGB" % (kb / 1024 / 1024)


STATE_ROLE = {WORKING: "ok", NEEDS_YOU: "warn", IDLE: "dim"}


def _tool_rows(t, depth, now, long_tools):
    rows = []
    for tid, (name, ts, summary) in sorted(t.pending_tools.items(), key=lambda kv: kv[1][1] or 0):
        if name in ("Agent", "Task"):
            continue                              # shown as the subagent itself
        age = now - ts if ts else 0
        slow = name not in long_tools and age > QUICK_TOOL_WARN_S
        rows.append(Row(depth, "⚙", "%s  %s" % (name, summary), "warn" if slow else "fg", "tool",
                        dict(id=tid, name=name, ts=ts, summary=summary, slow=slow),
                        fdur(age), "warn" if slow else "dim"))
    return rows


def build(store, now=None):
    from store import LONG_TOOLS
    now = now or time.time()
    procs = store.procs
    rows = []
    counts = dict(sessions=0, tools=0, agents=0, bg=0, procs=0, queued=0)
    claimed = set()

    rows.append(Row(0, "", "Claude Code sessions", "title", "header"))
    live = store.live_sessions()
    if not live:
        rows.append(Row(1, "·", "no live sessions", "dim", "none"))
    for s in live:
        counts["sessions"] += 1
        state = s.state(now)
        pid = (s.live or {}).get("pid")
        p = procs.get(pid)
        claimed.add(pid)
        mem = "  %s  cpu %.0f%%" % (fmem(p.rss), p.cpu) if p else ""
        rows.append(Row(0, "◆", "%s   %s · %s%s" % (s.name, short_model(s.model), s.effort or "?", mem),
                        "title", "session", s, state, STATE_ROLE.get(state, "dim")))
        tools = _tool_rows(s.t, 1, now, LONG_TOOLS)
        counts["tools"] += len(tools)
        rows.extend(tools)

        for a in sorted(s.agents.values(), key=lambda a: a.t.started or 0):
            if a.finished:
                continue
            counts["agents"] += 1
            rate = a.t.totals(now - 300).total / 5
            rows.append(Row(1, "◇", "%s  (%s)  %s · %s" % (a.label, a.meta.get("agentType", "agent"),
                                                          short_model(a.t.model), a.t.effort or "?"),
                            "info", "agent", (s, a),
                            "%s/m  %s" % (_tok(rate), fdur(now - (a.t.started or now))), "ok"))
            sub = _tool_rows(a.t, 2, now, LONG_TOOLS)
            counts["tools"] += len(sub)
            rows.extend(sub)

        for task in sorted(s.t.bg_tasks.values(), key=lambda b: b.started or 0):
            if task.running:
                counts["bg"] += 1
                rows.append(Row(1, "⧗", "bg %s  %s" % (task.tool, task.summary or task.id), "accent", "bg", (s, task),
                                "running " + fdur(now - task.started) if task.started else "running", "ok"))
            elif task.ended and now - task.ended < RECENT_DONE_S:
                ok = task.status == "completed"
                rows.append(Row(1, "✓" if ok else "✗", "bg %s  %s" % (task.tool, task.result or task.summary or task.id),
                                "dim" if ok else "crit", "bg", (s, task),
                                "%s %s ago" % (task.status, fdur(now - task.ended)), "dim" if ok else "crit"))

        if p:
            mcp = []
            for c in p.descendants():
                if c.kind == "mcp":
                    mcp.append(c)
                elif c.kind in ("shell", "process") and "ps -axo" not in c.args:
                    if c.ppid != p.pid and procs.get(c.ppid) and procs.get(c.ppid).kind == "mcp":
                        continue                  # a helper of an MCP server
                    counts["procs"] += 1
                    rows.append(Row(1, "▸", "pid %d  %s" % (c.pid, c.label), "fg", "proc", c,
                                    "%s  %.0f%%  %s" % (fmem(c.rss), c.cpu, fdur(c.elapsed))))
            if mcp:
                rows.append(Row(1, "⌁", "MCP servers: %d" % len(mcp), "dim", "mcp", mcp,
                                fmem(sum(m.rss for m in mcp))))

        for ts, text in s.t.queued:
            counts["queued"] += 1
            rows.append(Row(1, "✉", "queued: %s" % " ".join(text.split()), "warn", "queued", (s, ts, text),
                            fdur(now - ts) if ts else ""))

    others = [p for p in procs.clis() if p.pid not in claimed]
    desk = procs.desktop()
    if others or desk[0]:
        rows.append(Row(0, "", "Other Claude processes", "title", "header"))
    for p in others:
        rows.append(Row(0, "◆", "claude  pid %d  %s" % (p.pid, " ".join(p.args.split()[1:]) or "(no session file)"),
                        "fg", "cli", p, "%s  %.0f%%  up %s" % (fmem(p.rss), p.cpu, fdur(p.elapsed))))
        for c in p.descendants():
            if c.kind != "mcp":
                rows.append(Row(1, "▸", "pid %d  %s" % (c.pid, c.label), "dim", "proc", c, fmem(c.rss)))
    if desk[0]:
        main, n, rss, cpu = desk
        rows.append(Row(0, "▣", "Claude Desktop  %d processes" % n, "fg", "desktop", desk,
                        "%s  %.0f%%  up %s" % (fmem(rss), cpu, fdur(main.elapsed))))

    jobs = store.jobs()
    if jobs:
        rows.append(Row(0, "", "Background jobs", "title", "header"))
        for jid, st, mtime in jobs[:8]:
            state = st.get("state", "?")
            role = {"working": "ok", "blocked": "warn", "failed": "crit"}.get(state, "dim")
            rows.append(Row(0, "◈", "%s  %s" % (st.get("name") or jid, st.get("detail") or ""), "fg", "job", (jid, st),
                            "%s · %s ago" % (state, fdur(now - mtime)), role))

    sched = store.scheduled()
    if sched:
        rows.append(Row(0, "", "Scheduled tasks", "title", "header"))
        for name, desc in sched:
            rows.append(Row(0, "⏲", "%s  %s" % (name, desc), "fg", "sched", (name, desc)))
    return rows, counts


def _tok(n):
    for div, suf in ((1e6, "M"), (1e3, "k")):
        if n >= div:
            return "%.1f%s" % (n / div, suf)
    return "%d" % n


def tail(path, max_bytes=6000, lines=40):
    """The last lines of a background task's output file."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            fh.seek(max(0, size - max_bytes))
            data = fh.read().decode("utf-8", "replace")
    except OSError:
        return None
    out = data.splitlines()
    return out[-lines:]
