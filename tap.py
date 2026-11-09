#!/usr/bin/env python3
"""Status-line and hook tap for claudeMon. Standalone: imports nothing from
the package, so Claude Code can run it directly and it starts fast.
`claudemon install` copies this file to ~/.claude/claudemon/tap.py.

  tap.py statusline -- <your original status-line command...>
      Saves the status-line JSON for claudeMon, records rate-limit
      observations, then hands over to your original command (exec) on the
      same input, so your status line, its exit code and its timing are
      exactly as before.

  tap.py hook <Event>
      Records the last hook event per session, which is how claudeMon knows
      a session is waiting on a permission prompt.

Any failure is swallowed: the tap must never break the status line.
"""

import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime

HOME = os.path.expanduser(os.environ.get("CLAUDE_CONFIG_DIR", "~/.claude"))
STATE = os.path.join(HOME, "claudemon")
STATUS = os.path.join(STATE, "status")
LIMITS = os.path.join(STATE, "limits.jsonl")
LAST = os.path.join(STATE, "tap_last.json")
MIN_INTERVAL = 60      # seconds between unchanged limit observations
WINDOWS = ("five_hour", "seven_day")
SAME_WINDOW_S = 600    # resets_at values this close belong to the same limit window
SID_RE = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
MARK = ["#", "claudemon"]   # the installer's marker, in case a command is run without a shell


def _safe_sid(sid):
    """A session id usable as a file name, or None (never a path)."""
    return sid if isinstance(sid, str) and SID_RE.match(sid) else None


def _epoch(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value / 1000 if value > 1e12 else float(value)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _write_json(path, obj):
    tmp = "%s.%d.tmp" % (path, os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(obj, fh)
    os.replace(tmp, path)


def _read_json(path):
    try:
        with open(path, "rb") as fh:
            v = json.loads(fh.read())
    except (OSError, ValueError):
        return {}
    return v if isinstance(v, dict) else {}


def _window_order(resets, peak_resets):
    """-1 older window than the peak's, 0 the same window, 1 newer, None unknown.

    Unknown (no resets_at on either side) means no filtering at all: without a
    reset time a drop could be a real reset, so it must not be taken for stale."""
    a, b = _epoch(resets), _epoch(peak_resets)
    if a is None or b is None:
        return None
    if abs(a - b) < SAME_WINDOW_S:
        return 0
    return 1 if a > b else -1


def record_status(raw):
    data = json.loads(raw)
    if not isinstance(data, dict):
        return
    sid = data.get("session_id")
    if sid is None:
        sid = "unknown"
    elif not _safe_sid(sid):
        return
    os.makedirs(STATUS, mode=0o700, exist_ok=True)
    data["_seen"] = time.time()
    _write_json(os.path.join(STATUS, sid + ".json"), data)

    rl = data.get("rate_limits")
    rl = rl if isinstance(rl, dict) else {}
    last = _read_json(LAST)
    peak = last.get("peak") if isinstance(last.get("peak"), dict) else {}
    row = {"ts": round(time.time(), 1), "sid": sid}
    for key in WINDOWS:
        w = rl.get(key)
        if not isinstance(w, dict):
            continue
        pct = w.get("used_percentage")
        if isinstance(pct, bool) or not isinstance(pct, (int, float)):
            continue
        resets = w.get("resets_at")
        pk = peak.get(key) if isinstance(peak.get(key), dict) else {}
        order = _window_order(resets, pk.get("resets"))
        if order == -1:
            continue    # an idle session still showing the previous window: stale
        if order == 0 and pct < (pk.get("pct") or 0):
            continue    # usage never falls within a window: a stale reading from an idle session
        row[key] = {"pct": pct, "resets": resets}
        if order is None or order == 1 or pct >= (pk.get("pct") or 0):
            peak[key] = {"pct": pct, "resets": resets}
    if len(row) == 2:
        return
    same = all(last.get(k) == row[k] for k in WINDOWS if k in row)
    if same and row["ts"] - (last.get("ts") or 0) < MIN_INTERVAL:
        return
    fd = os.open(LIMITS, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, (json.dumps(row) + "\n").encode("utf-8"))    # one write: O_APPEND keeps lines whole
    finally:
        os.close(fd)
    new_last = {k: last[k] for k in WINDOWS if k in last}
    new_last.update(row)
    new_last["peak"] = peak
    _write_json(LAST, new_last)


def _run(cmd, raw):
    """Fallback when exec is not possible: run the original in its own process group."""
    shell = len(cmd) == 1
    try:
        p = subprocess.Popen(cmd[0] if shell else cmd, shell=shell, stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, start_new_session=True)
    except Exception:
        return 0
    try:
        out, _ = p.communicate(raw, timeout=10)
        code = p.returncode
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)       # the whole tree, not just the shell
        except OSError:
            pass
        out, _ = p.communicate()
        code = 0
    try:
        sys.stdout.buffer.write(out or b"")      # partial output is still shown
        sys.stdout.flush()
    except Exception:
        pass
    return code


def statusline(cmd):
    raw = sys.stdin.buffer.read()
    try:
        record_status(raw)
    except Exception:
        pass
    if not cmd:
        return 0
    # Become the original command: same stdin bytes, inherited stdout/stderr,
    # its own exit code and signals, and no timeout or buffering of ours.
    try:
        tf = tempfile.TemporaryFile()
        tf.write(raw)
        tf.flush()
        tf.seek(0)
        os.dup2(tf.fileno(), 0)
        sys.stdout.flush()
        if len(cmd) == 1:                   # the installer passes the original as one shell string
            os.execv("/bin/sh", ["/bin/sh", "-c", cmd[0]])
        os.execvp(cmd[0], cmd)
    except Exception:
        pass
    return _run(cmd, raw)


def hook(event):
    try:
        data = json.loads(sys.stdin.buffer.read() or b"{}")
        sid = _safe_sid(data.get("session_id")) if isinstance(data, dict) else None
        if not sid:
            return 0
        os.makedirs(STATUS, mode=0o700, exist_ok=True)
        msg = data.get("message")
        _write_json(os.path.join(STATUS, sid + ".hook.json"), {
            "event": event,
            "ts": time.time(),
            "type": str(data.get("notification_type") or ""),
            "message": msg[:200] if isinstance(msg, str) else "",
            "tool": str(data.get("tool_name") or ""),
        })
    except Exception:
        pass
    return 0


def main(argv):
    argv = list(argv)
    if argv[-2:] == MARK:
        argv = argv[:-2]
    if len(argv) >= 2 and argv[1] == "statusline":
        rest = argv[2:]
        if rest and rest[0] == "--":
            rest = rest[1:]
        return statusline(rest)
    if len(argv) >= 3 and argv[1] == "hook":
        return hook(argv[2])
    sys.stderr.write(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
