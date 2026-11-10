"""Process snapshot: Claude Code CLIs, what they have spawned, and Claude Desktop.

One `ps` call per refresh. Child processes are classified so the Tasks page can
show MCP servers apart from shell commands the agent is running right now.
"""

import os
import re
import subprocess

DESKTOP_MARK = "/Claude.app/"
SHELLS = {"zsh", "bash", "sh", "fish", "dash", "ksh"}
LAUNCHERS = {"node", "npx", "npm", "pnpm", "yarn", "bun", "bunx", "deno", "uv", "uvx", "pipx", "docker", "python", "ruby",
             "claude"}                                  # claude mcp serve
KNOWN_EXES = SHELLS | {"claude", "node", "caffeinate"}
# "mcp" as a whole part of a name or path: mcp-server-x, @scope/mcp, .bin/mcp, x_mcp, /mcp/
MCP_RE = re.compile(r"(?:^|[/@_.-])mcp(?:$|[/@_.-])|modelcontextprotocol")
COMM_MAX = 15            # macOS ps cuts comm to 16 characters unless it is the last column


def exe_from(comm, args):
    """The executable path. When ps truncated comm, recover the full path from args
    (it can contain spaces: "Application Support"), matching known executable names."""
    if len(comm) < COMM_MAX or not args.startswith(comm):
        return comm
    # the path ends before the first " -" (an option), so a later argument is never taken for it
    m = re.match(r"(\S(?:(?! -).)*?/(?:%s))(?=\s|$)" % "|".join(sorted(map(re.escape, KNOWN_EXES))), args)
    return m.group(1) if m else comm


def _launcher(base):
    base = base.lower()
    return base in LAUNCHERS or re.match(r"(python|node)[\d.]*$", base) is not None


def mcp_argv(argv):
    """True when an argv runs an MCP server: the program itself, or the first
    script/package a launcher (node, npx, uvx, python...) runs, is named for MCP."""
    if not argv:
        return False
    base = os.path.basename(argv[0])
    if MCP_RE.search(base.lower()):
        return True
    if not _launcher(base):
        return False
    operands = [a for a in argv[1:] if not a.startswith("-")][:2]
    return any(MCP_RE.search(a.lower()) for a in operands)


class Proc:
    __slots__ = ("pid", "ppid", "elapsed", "cpu", "rss", "comm", "args", "children", "exe")

    def __init__(self, pid, ppid, elapsed, cpu, rss, comm, args):
        self.pid, self.ppid, self.elapsed = pid, ppid, elapsed
        self.cpu, self.rss, self.comm, self.args = cpu, rss, comm, args
        self.exe = exe_from(comm, args)
        self.children = []

    @property
    def kind(self):
        base = os.path.basename(self.exe)
        if base == "caffeinate":
            return "keep-awake"
        if base in SHELLS:
            # a shell wrapping an MCP launcher (sh -c "npx mcp-server-x") is that server;
            # Claude Code's own wrapper (zsh -c "source ... && eval '<cmd>'") is a shell
            rest = self.args.split(" -c ", 1)
            if len(rest) == 2 and mcp_argv(rest[1].strip("'\" ").split()):
                return "mcp"
            return "shell"
        if mcp_argv([self.exe] + self.args[len(self.exe):].split() if self.args.startswith(self.exe) else self.args.split()):
            return "mcp"
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
    base = os.path.basename(p.exe)
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
