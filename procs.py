"""Process snapshot: Claude Code CLIs, what they have spawned, and Claude Desktop.

One `ps` call per refresh. Child processes are classified so the Tasks page can
show MCP servers apart from shell commands the agent is running right now.
"""

import os
import subprocess

DESKTOP_MARK = "/Claude.app/"


class Proc:
    __slots__ = ("pid", "ppid", "elapsed", "cpu", "rss", "comm", "args", "children")

    def __init__(self, pid, ppid, elapsed, cpu, rss, comm, args):
        self.pid, self.ppid, self.elapsed = pid, ppid, elapsed
        self.cpu, self.rss, self.comm, self.args = cpu, rss, comm, args
        self.children = []

    @property
    def kind(self):
        a = self.args
        low = a.lower()
        if " mcp" in low or "mcp-server" in low or "modelcontextprotocol" in low or low.endswith("mcp"):
            return "mcp"
        if os.path.basename(self.comm) in ("caffeinate",):
            return "keep-awake"
        if os.path.basename(self.comm) in ("zsh", "bash", "sh", "fish"):
            return "shell"
        return "process"

    @property
    def label(self):
        a = self.args
        if a.startswith(("/bin/zsh -c", "/bin/bash -c", "zsh -c", "bash -c", "sh -c")):
            a = a.split(" -c ", 1)[1]
            # Claude Code wraps commands as: source <snapshot> && eval '<cmd>' ...
            if "eval " in a:
                a = a.split("eval ", 1)[1]
            a = a.strip("'\" ")
        return " ".join(a.split())

    def descendants(self):
        out = []
        for c in self.children:
            out.append(c)
            out.extend(c.descendants())
        return out


def parse_etime(text):
    """ps etime: [[dd-]hh:]mm:ss -> seconds."""
    days = 0
    if "-" in text:
        d, text = text.split("-", 1)
        days = int(d)
    parts = [int(p) for p in text.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, s = parts
    return days * 86400 + h * 3600 + m * 60 + s


def snapshot():
    try:
        out = subprocess.run(["ps", "-axo", "pid=,ppid=,etime=,%cpu=,rss=,comm=,args="],
                             capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    procs = {}
    for line in out.splitlines():
        parts = line.split(None, 6)
        if len(parts) < 6:
            continue
        try:
            pid, ppid = int(parts[0]), int(parts[1])
            p = Proc(pid, ppid, parse_etime(parts[2]), float(parts[3]), int(parts[4]),
                     parts[5], parts[6] if len(parts) > 6 else parts[5])
        except ValueError:
            continue
        procs[pid] = p
    for p in procs.values():
        parent = procs.get(p.ppid)
        if parent is not None and parent is not p:
            parent.children.append(p)
    return procs


def is_claude_cli(p):
    base = os.path.basename(p.comm)
    if base == "claude":
        return True
    return base == "node" and ("claude-code" in p.args or "/bin/claude" in p.args)


class Processes:
    def __init__(self):
        self.procs = {}

    def refresh(self):
        # CLAUDEMON_DEMO hides the real process list so screenshots show only demo data
        self.procs = {} if os.environ.get("CLAUDEMON_DEMO") else snapshot()

    def get(self, pid):
        try:
            return self.procs.get(int(pid))
        except (TypeError, ValueError):
            return None

    def clis(self):
        return sorted((p for p in self.procs.values() if is_claude_cli(p)), key=lambda p: p.pid)

    def desktop(self):
        """(main process or None, helper count, total RSS kB, total CPU %) for Claude Desktop."""
        group = [p for p in self.procs.values() if DESKTOP_MARK in p.args]
        if not group:
            return None, 0, 0, 0.0
        main = next((p for p in group if p.args.endswith("/MacOS/Claude")), group[0])
        return main, len(group), sum(p.rss for p in group), sum(p.cpu for p in group)
