"""Discovers Claude Code sessions on this machine and keeps their numbers current.

Sources, all read-only:
  ~/.claude/sessions/<pid>.json            live registry: pid, name, busy/idle
  ~/.claude/projects/<proj>/<sid>.jsonl    the transcript
  ~/.claude/projects/<proj>/<sid>/subagents/agent-*.jsonl (+ .meta.json)
  ~/.claude/claudemon/status/<sid>.json    last status-line input (from the tap)
  ~/.claude/claudemon/status/<sid>.hook.json  last hook event (from the tap)
"""

import calendar
import glob
import json
import os
import re
import threading
import time

from limits import LimitLog
from limits import compact as compact_limits
from paths import JOBS_DIR, PROJECTS_DIR, SCHEDULED_DIR, SESSIONS_DIR, STATUS_DIR
from procs import Processes
from transcript import Transcript, Usage

HISTORY_S = 8 * 86400           # transcripts this recent feed the history pages
RESCAN_S = 20                   # how often to look for new transcript files
AGENT_SILENT_S = 600            # a subagent silent this long (and not mid-tool) counts as finished
AGENT_TOOL_MAX_S = 2 * 3600     # ...but one waiting on a tool is trusted for up to this long
PID_START_SLACK_S = 120         # registry startedAt vs the process's real start: more apart = pid reused
BIG_CONTEXT = ("opus-5", "fable")   # families with a 1M window by default; the tap's value wins
LONG_TOOLS = {"Agent", "Task", "Bash", "WebFetch", "WebSearch", "Monitor"}

WORKING, NEEDS_YOU, IDLE, DONE = "working", "needs you", "idle", "done"


def pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def proc_start(value):
    """Registry procStart ("Fri Nov  6 12:47:50 2026", UTC) -> epoch seconds, or None."""
    if not isinstance(value, str):
        return None
    try:
        return calendar.timegm(time.strptime(" ".join(value.split()), "%a %b %d %H:%M:%S %Y"))
    except ValueError:
        return None


def read_json(path):
    """A JSON object from path, or None (missing, unreadable, invalid or not an object)."""
    try:
        with open(path, "rb") as fh:
            v = json.loads(fh.read())
    except (OSError, ValueError):
        return None
    return v if isinstance(v, dict) else None


def weight(u):
    """Rough cost-proportional weight of a call, for 'share of usage' views.
    Cache reads are cheap, cache writes a little dearer than input, output dear."""
    return u.input + 1.25 * u.cache_write + 0.1 * u.cache_read + 5 * u.output


def short_model(model):
    """claude-opus-4-7[1m] -> Opus 4.7; also us.anthropic.… prefixes, @dates and legacy claude-3-5-sonnet-…"""
    raw = model if isinstance(model, str) else ""
    m = re.sub(r"\[.*?\]", "", raw.lower().split("anthropic.")[-1]).split("@")[0].split(":")[0]
    parts = m.replace("claude-", "").split("-")
    for fam in ("opus", "sonnet", "haiku", "fable"):
        if fam not in parts:
            continue
        i = parts.index(fam)
        ver = []
        for p in parts[i + 1:i + 3]:          # new style: family then version
            if not (p.isdigit() and len(p) <= 2):
                break
            ver.append(p)
        if not ver:                           # legacy style: version then family
            ver = [p for p in parts[:i] if p.isdigit() and len(p) <= 2][:2]
        return fam.capitalize() + (" " + ".".join(ver) if ver else "")
    return raw.replace("claude-", "") or "?"


class Agent:
    def __init__(self, path):
        self.id = os.path.basename(path)[len("agent-"):-len(".jsonl")]
        self.t = Transcript(path)
        self.meta_path = path[:-len(".jsonl")] + ".meta.json"
        self.meta = {}

    def refresh(self):
        self.t.refresh()
        self.meta = read_json(self.meta_path) or self.meta

    @property
    def label(self):
        return self.meta.get("description") or self.meta.get("agentType") or self.id[:8]

    @property
    def finished(self):
        if self.meta.get("finished") or self.meta.get("stoppedByUser"):
            return True
        if not self.t.last_ts:
            return False
        silent = time.time() - max(self.t.last_ts, self.t.mtime or 0)
        if self.t.pending_tools:              # blocked on a long tool call, not finished
            return silent > AGENT_TOOL_MAX_S
        return silent > AGENT_SILENT_S


class Session:
    def __init__(self, sid, path):
        self.sid = sid
        self.t = Transcript(path)
        self.agents = {}
        self.live = None            # registry entry while the process runs
        self.status = {}            # last status-line JSON
        self.hook = {}              # last hook event
        self.seen = 0.0

    # ── identity ───────────────────────────────────────────────────────────
    @property
    def project(self):
        cwd = (self.live or {}).get("cwd") or self.t.cwd
        return os.path.basename(cwd.rstrip("/")) if cwd else "?"

    @property
    def name(self):
        if self.live and self.live.get("name"):
            return self.live["name"]
        return self.t.title or self.project

    @property
    def model(self):
        m = (self.status.get("model") or {}).get("id") if self.status else None
        return self.t.model or m or ""

    @property
    def effort(self):
        e = (self.status.get("effort") or {}).get("level") if self.status else None
        return self.t.effort or e or ""

    # ── state ──────────────────────────────────────────────────────────────
    def state(self, now=None):
        now = now or time.time()
        if not self.live:
            return DONE
        hk = self.hook or {}
        last_activity = max(self.t.last_ts or 0, self.t.mtime or 0)
        if hk.get("event") == "Notification" and hk.get("ts", 0) >= last_activity - 1:
            kind = (hk.get("type") or "") + " " + (hk.get("message") or "").lower()
            if "idle" in kind or "waiting for your input" in kind:
                return IDLE
            return NEEDS_YOU
        if hk.get("event") == "PermissionRequest" and hk.get("ts", 0) >= last_activity - 1:
            return NEEDS_YOU
        status = self.live.get("status")
        if status == "busy":
            stuck = self.t.stuck_tool(now)
            if stuck and stuck[0] not in LONG_TOOLS and stuck[1] > 45 and now - last_activity > 45:
                return NEEDS_YOU          # a quick tool has waited too long: likely a prompt
            return WORKING
        if status in ("idle", None):
            return IDLE
        return NEEDS_YOU                  # any other registry state wants attention

    # ── numbers ────────────────────────────────────────────────────────────
    def context(self):
        """(tokens in context, window size)."""
        cw = (self.status or {}).get("context_window") or {}
        used = self.t.last_usage.prompt if self.t.last_usage else 0
        size = cw.get("context_window_size") or 0
        if not size:                      # no tap yet: infer from the model
            m = self.model
            big = "[1m]" in m or any(f in m for f in BIG_CONTEXT)
            size = 1_000_000 if big or used > 200_000 else 200_000
        return used, size

    def cost(self):
        return ((self.status or {}).get("cost") or {}).get("total_cost_usd")

    # The indexer thread adds to these dicts while the UI thread reads them, so
    # every reader iterates a snapshot (list(...)) rather than the live dict.
    def transcripts(self, agents=True):
        yield self.t, None
        if agents:
            for a in list(self.agents.values()):
                yield a.t, a

    def all_calls(self, since=0):
        for t, a in self.transcripts():
            for c in list(t.calls.values()):
                if c.ts and c.ts >= since:
                    yield c, a

    def loops(self):
        out = []
        for t, a in self.transcripts():
            for path, n in list(t.loop_files.items()):
                out.append((path, n, t.reads_since_edit.get(path, 0), a))
        return sorted(out, key=lambda r: -r[1])


class Store:
    def __init__(self):
        self.sessions = {}
        self.limits = LimitLog()
        self.procs = Processes()
        self.lock = threading.RLock()
        self.indexed = False
        self.index_progress = (0, 0)
        self._last_scan = 0.0
        self.tap_seen = False

    # ── discovery ──────────────────────────────────────────────────────────
    def start(self):
        threading.Thread(target=self.index, daemon=True).start()

    def index(self):
        """Read every recent transcript once. Never raises; always ends with indexed=True."""
        self.index_errors = 0
        try:
            paths = self._recent_transcripts()
            self.index_progress = (0, len(paths))
            for i, (sid, path) in enumerate(paths):
                try:
                    with self.lock:
                        s = self._session(sid, path)
                    s.t.refresh()
                    self._refresh_agents(s, scan=True)
                except Exception:             # one bad transcript must not stop the rest
                    self.index_errors += 1
                self.index_progress = (i + 1, len(paths))
        except Exception:
            self.index_errors += 1
        finally:
            self._last_scan = time.time()
            self.indexed = True

    def _recent_transcripts(self):
        now = time.time()
        found = []
        for path in glob.glob(str(PROJECTS_DIR / "*" / "*.jsonl")):
            try:
                if now - os.path.getmtime(path) <= HISTORY_S:
                    found.append((os.path.basename(path)[:-6], path))
            except OSError:
                pass
        return found

    def _session(self, sid, path):
        s = self.sessions.get(sid)
        if s is None:
            s = self.sessions[sid] = Session(sid, path)
        return s

    def _refresh_agents(self, s, scan=False):
        if scan:
            folder = s.t.path[:-6] + "/subagents"
            for path in glob.glob(folder + "/agent-*.jsonl"):
                aid = os.path.basename(path)[len("agent-"):-len(".jsonl")]
                with self.lock:               # both threads scan: check and insert together
                    if aid not in s.agents:
                        s.agents[aid] = Agent(path)
        for a in list(s.agents.values()):
            a.refresh()

    # ── per-tick refresh ───────────────────────────────────────────────────
    def is_live(self, entry, now=None):
        """A registry entry whose process is running and is the one that wrote it.

        A crash can leave sessions/<pid>.json behind; if the pid is later reused
        by an unrelated process, its start time will not match the registry's
        procStart (the process's own start, in UTC; unlike the session's
        startedAt it stays put across /clear and /resume)."""
        pid = entry.get("pid")
        if not pid_alive(pid):
            return False
        p = self.procs.get(pid)
        started = proc_start(entry.get("procStart"))
        if p is None or started is None:
            return True                       # no process table (demo, ps failed) or no start time: trust the pid
        return abs(((now or time.time()) - p.elapsed) - started) <= PID_START_SLACK_S

    def refresh(self):
        now = time.time()
        self.procs.refresh()                  # first: the registry check below uses it
        live = {}
        for path in glob.glob(str(SESSIONS_DIR / "*.json")):
            entry = read_json(path)
            sid = entry.get("sessionId") if entry else None
            if isinstance(sid, str) and sid and self.is_live(entry, now):
                live[sid] = entry

        rescan = now - self._last_scan > RESCAN_S
        with self.lock:
            if rescan and self.indexed:
                for sid, path in self._recent_transcripts():
                    self._session(sid, path)
                self._last_scan = now
            for sid, entry in live.items():
                if sid not in self.sessions:
                    hits = glob.glob(str(PROJECTS_DIR / "*" / (sid + ".jsonl")))
                    if hits:
                        self._session(sid, hits[0])
            sessions = list(self.sessions.values())

        for s in sessions:
            s.live = live.get(s.sid)
            try:
                if s.live or (rescan and self.indexed):
                    s.t.refresh()
                    self._refresh_agents(s, scan=True)
                st = read_json(STATUS_DIR / (s.sid + ".json")) if s.live else None
                if st:
                    s.status = st
                    self.tap_seen = True
                hk = read_json(STATUS_DIR / (s.sid + ".hook.json")) if s.live else None
                if hk:
                    s.hook = hk
            except Exception:                 # one bad session must not take the others down
                pass
        try:
            self.limits.refresh()
        except Exception:
            pass
        if any(self.limits.obs.values()):
            self.tap_seen = True

    # ── queries ────────────────────────────────────────────────────────────
    def jobs(self):
        """Claude jobs (~/.claude/jobs/<id>/state.json): [(id, state dict, mtime)]."""
        out = []
        for path in glob.glob(str(JOBS_DIR / "*" / "state.json")):
            st = read_json(path)
            if st:
                out.append((os.path.basename(os.path.dirname(path)), st, os.path.getmtime(path)))
        return sorted(out, key=lambda j: -j[2])

    def scheduled(self):
        """Scheduled tasks: [(name, description)] from each SKILL.md front matter."""
        out = []
        for path in sorted(glob.glob(str(SCHEDULED_DIR / "*" / "SKILL.md"))):
            meta = {}
            try:
                with open(path) as fh:
                    lines = fh.read(4000).splitlines()
            except OSError:
                continue
            if lines and lines[0].strip() == "---":
                for line in lines[1:]:
                    if line.strip() == "---":
                        break
                    if ":" in line:
                        k, v = line.split(":", 1)
                        meta[k.strip()] = v.strip()
            out.append((meta.get("name") or os.path.basename(os.path.dirname(path)), meta.get("description", "")))
        return out

    def session_for_pid(self, pid):
        with self.lock:
            for s in self.sessions.values():
                if s.live and s.live.get("pid") == pid:
                    return s
        return None

    def live_sessions(self):
        with self.lock:
            out = [s for s in self.sessions.values() if s.live]
        order = {NEEDS_YOU: 0, WORKING: 1, IDLE: 2, DONE: 3}
        return sorted(out, key=lambda s: (order[s.state()], -(s.t.last_ts or 0)))

    def recent_sessions(self, since):
        with self.lock:
            return [s for s in self.sessions.values() if s.live or (s.t.last_ts or 0) >= since]

    def calls(self, since, sessions=None):
        for s in sessions if sessions is not None else self.recent_sessions(since):
            for c, a in s.all_calls(since):
                yield s, c, a

    def prune_state(self, keep_s=HISTORY_S):
        """Delete tap status files for sessions not seen in keep_s, and compact the limits log."""
        cutoff = time.time() - keep_s
        for path in glob.glob(str(STATUS_DIR / "*.json")):
            try:
                if os.path.getmtime(path) < cutoff:
                    os.unlink(path)
            except OSError:
                pass
        compact_limits()

    def tokens_between(self, t0, t1):
        total = 0
        with self.lock:
            sessions = list(self.sessions.values())
        for s in sessions:
            for c, _ in s.all_calls(t0):
                if c.ts <= t1:
                    total += c.usage.total
        return total

    def series(self, span, n, metric, sessions=None, now=None):
        """Bucket `metric(call) -> number` into n buckets covering the last `span` s."""
        now = now or time.time()
        t0 = now - span
        size = span / n
        out = [0.0] * n
        for _, c, _ in self.calls(t0, sessions):
            i = int((c.ts - t0) / size)
            if 0 <= i < n:
                out[i] += metric(c)
        return out

    def totals(self, since, sessions=None):
        u = Usage()
        for _, c, _ in self.calls(since, sessions):
            u.add(c.usage)
        return u
