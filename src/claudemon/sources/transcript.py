"""Incremental parser for Claude Code JSONL transcripts.

Each Transcript remembers its byte offset, so a refresh only reads lines
appended since the last one. Streaming writes the same API message several
times with growing usage; usage is keyed by message id and the last copy wins.
"""

import json
import os
import re
import threading
import time
from collections import Counter
from datetime import datetime

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
LOOP_THRESHOLD = 3          # reads of one file with no edit between them
NOTIFY_RE = re.compile(r"<task-id>([^<]+)</task-id>(.*?)</task-notification>", re.S)
BG_START_RE = re.compile(r"running in background with ID: (\w+)\. Output is being written to: (\S+?)\.?(?:\s|$)")
SKIP_KINDS = (b'"api-request-blob"', b'"api-request-shape"', b'"file-history-snapshot"')
STOP_TOOLS = {"TaskStop", "KillShell", "KillBash"}   # tools that stop a background task
READ_BLOCK = 4 << 20        # read big transcripts in blocks so the first index stays small in memory


def _str(v):
    """v when it is a string, else "" (records with odd shapes must not poison state)."""
    return v if isinstance(v, str) else ""


def _int(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def _dict(v):
    return v if isinstance(v, dict) else {}


def parse_ts(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return None


class Usage:
    __slots__ = ("input", "output", "cache_read", "cache_write", "thinking", "ttl_1h")

    def __init__(self, u=None):
        u = _dict(u)
        self.input = _int(u.get("input_tokens"))
        self.output = _int(u.get("output_tokens"))
        self.cache_read = _int(u.get("cache_read_input_tokens"))
        self.cache_write = _int(u.get("cache_creation_input_tokens"))
        self.thinking = _int(_dict(u.get("output_tokens_details")).get("thinking_tokens"))
        self.ttl_1h = bool(_dict(u.get("cache_creation")).get("ephemeral_1h_input_tokens"))

    @property
    def prompt(self):
        """Tokens the model saw as input on this call (its context size)."""
        return self.input + self.cache_read + self.cache_write

    @property
    def total(self):
        return self.prompt + self.output

    def add(self, other):
        self.input += other.input
        self.output += other.output
        self.cache_read += other.cache_read
        self.cache_write += other.cache_write
        self.thinking += other.thinking
        return self


class Call:
    """One API call: when it finished, what it used, which model and effort."""
    __slots__ = ("ts", "usage", "model", "effort")

    def __init__(self, ts, usage, model, effort):
        self.ts, self.usage, self.model, self.effort = ts, usage, model, effort


def summarize(name, args):
    """One line saying what a tool call is doing."""
    if not isinstance(args, dict):
        return ""
    if name in ("Agent", "Task"):
        kind = args.get("subagent_type") or "agent"
        return "%s: %s" % (kind, args.get("description") or "")
    for key in ("command", "file_path", "notebook_path", "pattern", "url", "query", "skill", "description", "prompt"):
        v = args.get(key)
        if isinstance(v, str) and v:
            if key == "pattern" and args.get("path"):
                v = "%s  in %s" % (v, args["path"])
            return " ".join(v.split())[:240]
    for v in args.values():
        if isinstance(v, str) and v:
            return " ".join(v.split())[:240]
    return ""


class BgTask:
    """A background shell or agent started by a tool call (run_in_background)."""
    __slots__ = ("id", "tool", "summary", "started", "output", "status", "ended", "result")

    def __init__(self, task_id, tool, summary, started, output):
        self.id, self.tool, self.summary, self.started, self.output = task_id, tool, summary, started, output
        self.status = "running"
        self.ended = None
        self.result = ""

    @property
    def running(self):
        return self.status == "running"


class Transcript:
    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()     # the indexer and the UI tick may overlap
        self._reset()

    def _reset(self):
        self.offset = 0
        self.mtime = 0.0
        self.inode = None
        self._partial = b""
        self.bad_records = 0          # lines that parsed as JSON but could not be ingested

        self.title = ""
        self.last_prompt = ""
        self.model = ""
        self.effort = ""
        self.permission_mode = ""
        self.cwd = ""
        self.git_branch = ""
        self.started = None
        self.last_ts = None
        self.compactions = 0
        self.api_errors = 0

        self.calls = {}               # message id -> Call; last streamed copy wins
        self.last_usage = None        # newest call with a prompt: its context size
        self.last_call_ts = None
        self.cache_ttl = 300          # seconds; 1h when the session writes 1h cache
        self.tools = Counter()
        self.pending_tools = {}       # tool_use id -> (name, timestamp, summary)
        self._seen_tools = set()
        self.tool_meta = {}           # tool_use id -> (name, summary) for every call
        self._stop_targets = {}       # TaskStop tool_use id -> the task id it stops
        self.bg_tasks = {}            # background task id -> BgTask
        self.queued = []              # prompts typed while Claude was busy: [(ts, text)]

        # loop detection: file -> reads since its last edit
        self.reads_since_edit = Counter()
        self.read_totals = Counter()
        self.loop_files = {}          # file -> worst consecutive-read streak

    # ── reading ────────────────────────────────────────────────────────────
    def refresh(self):
        with self._lock:
            return self._refresh()

    def _refresh(self):
        try:
            st = os.stat(self.path)
        except OSError:
            return False
        if st.st_size < self.offset or (self.inode is not None and st.st_ino != self.inode):
            self._reset()                     # rewritten, replaced or truncated: start over
        self.inode = st.st_ino
        if st.st_size == self.offset:
            return False
        self.mtime = st.st_mtime
        try:
            with open(self.path, "rb") as fh:
                fh.seek(self.offset)
                while True:
                    chunk = fh.read(READ_BLOCK)
                    if not chunk:
                        break
                    self.offset += len(chunk)
                    self._lines(chunk)
        except OSError:
            return False
        return True

    def _lines(self, chunk):
        lines = (self._partial + chunk).split(b"\n")
        self._partial = lines.pop()           # an unterminated tail waits for the next block
        for raw in lines:
            head = raw[:80]
            if not raw.strip() or any(k in head for k in SKIP_KINDS):
                continue                      # huge request dumps we never need
            try:
                rec = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                continue
            if not isinstance(rec, dict):
                continue
            try:
                self._ingest(rec)
            except Exception:                 # one odd record must never stop the monitor
                self.bad_records += 1

    def _ingest(self, rec):
        kind = rec.get("type")
        ts = parse_ts(rec.get("timestamp"))
        if ts:
            self.last_ts = ts if not self.last_ts else max(self.last_ts, ts)
            if not self.started:
                self.started = ts
        self.cwd = _str(rec.get("cwd")) or self.cwd
        self.git_branch = _str(rec.get("gitBranch")) or self.git_branch

        if kind == "assistant":
            self._assistant(rec, ts)
        elif kind == "user":
            self._user(rec)
        elif kind == "api-request":
            params = _dict(rec.get("params"))
            self.model = _str(params.get("model")) or self.model
            self.effort = _str(_dict(params.get("output_config")).get("effort")) or self.effort
        elif kind == "permission-mode":
            self.permission_mode = _str(rec.get("permissionMode")) or self.permission_mode
        elif kind == "ai-title":
            self.title = _str(rec.get("aiTitle")) or self.title
        elif kind == "last-prompt":
            self.last_prompt = _str(rec.get("lastPrompt")) or self.last_prompt
        elif kind == "queue-operation":
            self._queue(rec, ts)
        elif kind == "attachment":
            att = _dict(rec.get("attachment"))
            if att.get("type") == "queued_command":
                self._notifications(att.get("prompt"), ts)
        elif kind == "system":
            sub = _str(rec.get("subtype"))
            if sub == "compact_boundary":
                self.compactions += 1
                self.reads_since_edit.clear()   # context reset; re-reads are expected
            elif "error" in sub:
                self.api_errors += 1

    def _assistant(self, rec, ts):
        msg = _dict(rec.get("message"))
        mid = msg.get("id") or rec.get("uuid")
        if not isinstance(mid, str):
            mid = None
        model = _str(msg.get("model"))
        if model.startswith("<"):               # "<synthetic>" placeholder messages
            return
        if model:
            self.model = model
        usage = Usage(msg.get("usage"))
        self.calls[mid] = Call(ts, usage, model or self.model, self.effort)
        if usage.cache_write:
            self.cache_ttl = 3600 if usage.ttl_1h else 300
        if usage.prompt and ts:
            self.last_usage = usage
            self.last_call_ts = ts
        if rec.get("isApiErrorMessage"):
            self.api_errors += 1
        content = msg.get("content")
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            tid = block.get("id")
            if not isinstance(tid, str):
                continue
            if tid in self._seen_tools:
                continue                        # duplicate streamed copy
            self._seen_tools.add(tid)
            name = block.get("name") or "?"
            if not isinstance(name, str):
                name = "?"
            self.tools[name] += 1
            args = block.get("input")
            args = args if isinstance(args, dict) else {}
            if name in STOP_TOOLS:
                target = args.get("task_id") or args.get("shell_id")
                if isinstance(target, str):
                    self._stop_targets[tid] = target
            summary = summarize(name, args)
            self.pending_tools[tid] = (name, ts, summary)
            self.tool_meta[tid] = (name, summary)
            path = args.get("file_path") or args.get("notebook_path")
            if not isinstance(path, str):
                path = None
            if name == "Read" and path:
                self.read_totals[path] += 1
                self.reads_since_edit[path] += 1
                streak = self.reads_since_edit[path]
                if streak >= LOOP_THRESHOLD:
                    self.loop_files[path] = max(streak, self.loop_files.get(path, 0))
            elif name in EDIT_TOOLS and path:
                self.reads_since_edit[path] = 0

    def _user(self, rec):
        ts = parse_ts(rec.get("timestamp"))
        content = _dict(rec.get("message")).get("content")
        if isinstance(content, str):
            self._notifications(content, ts)
            return
        if not isinstance(content, list):
            return
        result = rec.get("toolUseResult") if isinstance(rec.get("toolUseResult"), dict) else {}
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                self._notifications(block.get("text"), ts)
            if block.get("type") != "tool_result":
                continue
            tid = block.get("tool_use_id")
            if not isinstance(tid, str):
                continue
            self.pending_tools.pop(tid, None)
            text = block.get("content")
            if isinstance(text, list):
                text = " ".join(b.get("text") or "" for b in text if isinstance(b, dict) and isinstance(b.get("text"), str))
            if not isinstance(text, str):
                text = ""
            target = self._stop_targets.pop(tid, None)
            if target and not block.get("is_error"):
                self._stopped(result.get("task_id") or target, ts)
            m = BG_START_RE.search(text)
            task_id = result.get("backgroundTaskId") or (m.group(1) if m else None)
            if task_id and task_id not in self.bg_tasks:
                name, summary = self.tool_meta.get(tid, ("?", ""))
                self.bg_tasks[task_id] = BgTask(task_id, name, summary, ts, m.group(2) if m else "")

    def _stopped(self, task_id, ts):
        """A TaskStop/KillShell call succeeded: its task will never send a notification."""
        task = self.bg_tasks.get(task_id)
        if task is not None and task.running:
            task.status = "stopped"
            task.ended = ts

    def _notifications(self, text, ts):
        """Background tasks report completion as <task-notification> messages."""
        if not isinstance(text, str) or "<task-notification>" not in text:
            return
        for task_id, body in NOTIFY_RE.findall(text):
            task = self.bg_tasks.get(task_id)
            if task is None:
                task = self.bg_tasks[task_id] = BgTask(task_id, "task", "", None, "")
            status = re.search(r"<status>([^<]+)</status>", body)
            summary = re.search(r"<summary>(.*?)</summary>", body, re.S)
            out = re.search(r"<output-file>([^<]+)</output-file>", body)
            task.status = status.group(1).strip() if status else "completed"
            task.ended = task.ended or ts
            if summary:
                task.result = summary.group(1).strip()[:300]
            if out and not task.output:
                task.output = out.group(1).strip()

    def _queue(self, rec, ts):
        text = rec.get("content") or ""
        if not isinstance(text, str):
            return
        if "<task-notification>" in text:
            self._notifications(text, ts)
            return
        if rec.get("operation") == "enqueue":
            self.queued.append((ts, text))
        elif text:
            self.queued = [q for q in self.queued if q[1] != text]
        else:
            self.queued = []

    # ── derived numbers ────────────────────────────────────────────────────
    def totals(self, since=0):
        t = Usage()
        for c in list(self.calls.values()):
            if (c.ts or 0) >= since:
                t.add(c.usage)
        return t

    def stuck_tool(self, now=None):
        """The oldest tool call still waiting on a result: (name, seconds)."""
        now = now or time.time()
        oldest = None
        for name, ts, _ in list(self.pending_tools.values()):
            if ts and (oldest is None or ts < oldest[1]):
                oldest = (name, ts)
        return (oldest[0], now - oldest[1]) if oldest else None

    def cache_expires(self):
        """Epoch seconds when this session's prompt cache goes cold."""
        if not self.last_call_ts:
            return None
        return self.last_call_ts + self.cache_ttl
