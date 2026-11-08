#!/usr/bin/env python3
"""Status-line and hook tap for claudeMon. Standalone: imports nothing from
the package, so Claude Code can run it directly and it starts fast.

  tap.py statusline -- <your original status-line command...>
      Saves the status-line JSON for claudeMon, records rate-limit
      observations, then runs your original command on the same input so
      your status line looks exactly as before.

  tap.py hook <Event>
      Records the last hook event per session, which is how claudeMon knows
      a session is waiting on a permission prompt.

Any failure is swallowed: the tap must never break the status line.
"""

import json
import os
import subprocess
import sys
import time

HOME = os.path.expanduser(os.environ.get("CLAUDE_CONFIG_DIR", "~/.claude"))
STATE = os.path.join(HOME, "claudemon")
STATUS = os.path.join(STATE, "status")
LIMITS = os.path.join(STATE, "limits.jsonl")
LAST = os.path.join(STATE, "tap_last.json")
MIN_INTERVAL = 60      # seconds between unchanged limit observations


def _write_json(path, obj):
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w") as fh:
        json.dump(obj, fh)
    os.replace(tmp, path)


def record_status(raw):
    data = json.loads(raw)
    sid = data.get("session_id") or "unknown"
    os.makedirs(STATUS, exist_ok=True)
    data["_seen"] = time.time()
    _write_json(os.path.join(STATUS, sid + ".json"), data)

    rl = data.get("rate_limits") or {}
    row = {"ts": round(time.time(), 1), "sid": sid}
    for key in ("five_hour", "seven_day"):
        w = rl.get(key) or {}
        pct = w.get("used_percentage")
        if pct is not None:
            row[key] = {"pct": pct, "resets": w.get("resets_at")}
    if len(row) == 2:
        return
    try:
        with open(LAST) as fh:
            last = json.load(fh)
    except (OSError, ValueError):
        last = {}
    same = all(last.get(k) == row.get(k) for k in ("five_hour", "seven_day"))
    if same and row["ts"] - last.get("ts", 0) < MIN_INTERVAL:
        return
    with open(LIMITS, "a") as fh:
        fh.write(json.dumps(row) + "\n")
    _write_json(LAST, row)


def statusline(cmd):
    raw = sys.stdin.buffer.read()
    try:
        record_status(raw)
    except Exception:
        pass
    if not cmd:
        return 0
    try:
        shell = len(cmd) == 1               # the installer passes the original as one string
        out = subprocess.run(cmd[0] if shell else cmd, shell=shell, input=raw,
                             stdout=subprocess.PIPE, timeout=10)
        sys.stdout.buffer.write(out.stdout)
        return out.returncode
    except Exception:
        return 0


def hook(event):
    try:
        data = json.loads(sys.stdin.read() or "{}")
        sid = data.get("session_id")
        if not sid:
            return 0
        os.makedirs(STATUS, exist_ok=True)
        _write_json(os.path.join(STATUS, sid + ".hook.json"), {
            "event": event,
            "ts": time.time(),
            "type": data.get("notification_type") or "",
            "message": (data.get("message") or "")[:200],
            "tool": data.get("tool_name") or "",
        })
    except Exception:
        pass
    return 0


def main(argv):
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
