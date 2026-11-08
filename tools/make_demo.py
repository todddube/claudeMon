#!/usr/bin/env python3
"""Generate a synthetic ~/.claude tree for demos and README screenshots.

    tools/make_demo.py OUTDIR [--no-tap] [--pid PID]
    CLAUDE_CONFIG_DIR=OUTDIR CLAUDEMON_DEMO=1 ./claudemon.py

Eight "live" sessions (working, needs-you, idle), subagents, a background task,
a queued prompt, a re-read loop, five days of history, and a limit log with a
blind spot. Everything is relative to "now", so regenerate right before use.
"""

import argparse
import json
import math
import os
import random
import shutil
import time
from datetime import datetime, timezone

NOW = time.time()
H = 3600
FILES = ["src/app.py", "src/cart.py", "src/checkout.py", "src/models.py", "src/api/orders.py",
         "tests/test_cart.py", "tests/test_orders.py", "README.md", "package.json", "docs/setup.md"]
BASH = ["npm test", "pytest -q", "git status --short", "make build", "ls -la src", "python manage.py check"]

# name, project, model, effort, state, ctx fraction, window, tokens/call out, call gap s, wave, title
SESSIONS = [
    dict(name="web shop", proj="web_shop", model="claude-opus-5-5", effort="medium", state="working", ctx=.68,
         win=1_000_000, out=900, dt=17, wave=5, mins=220, title="Checkout flow rewrite", branch="feature/checkout",
         pending="npm test -- --watch=false",
         agents=[("Review checkout flow", "Explore", "claude-haiku-5-5", "low", False),
                 ("Draft migration notes", "general-purpose", "claude-sonnet-5-5", "high", False),
                 ("Audit cart tests", "code-reviewer", "claude-sonnet-5-5", "medium", True)]),
    dict(name="api refactor", proj="web_shop", model="claude-opus-5-5", effort="medium", state="working", ctx=.41,
         win=1_000_000, out=700, dt=20, wave=4, mins=150, title="Orders API refactor", branch="refactor/orders",
         pending="pytest -q tests/test_orders.py", bg=("pytest -q --maxfail=1", "running"),
         bg_done=("npm run lint", "completed"), queued="also add pagination to the orders endpoint"),
    dict(name="migration", proj="firmware", model="claude-opus-5-5", effort="xhigh", state="working", ctx=.86,
         win=1_000_000, out=1300, dt=24, wave=3, mins=260, title="Schema migration", branch="db/v2",
         pending="python migrate.py --dry-run", compact=[.38, .7]),
    dict(name="docs", proj="docs", model="claude-sonnet-5-5", effort="medium", state="working", ctx=.33,
         win=200_000, out=500, dt=26, wave=6, mins=90, title="Rewrite setup guide", branch="docs/setup",
         pending="make docs", loop="docs/setup.md"),
    dict(name="firmware", proj="firmware", model="claude-sonnet-5-5", effort="high", state="working", ctx=.52,
         win=200_000, out=800, dt=18, wave=2, mins=130, title="Sensor driver timing", branch="main",
         pending="make flash"),
    dict(name="data cleanup", proj="docs", model="claude-haiku-5-5", effort="low", state="working", ctx=.27,
         win=200_000, out=350, dt=15, wave=7, mins=70, title="Normalize CSV exports", branch="main",
         pending="python clean.py", think=False),
    dict(name="tests", proj="web_shop", model="claude-opus-5-5", effort="medium", state="needs", ctx=.58,
         win=1_000_000, out=600, dt=24, wave=3, mins=110, title="Fix flaky checkout tests", branch="fix/flaky",
         pending="Edit"),
    dict(name="release notes", proj="docs", model="claude-sonnet-5-5", effort="medium", state="idle", ctx=.19,
         win=200_000, out=400, dt=30, wave=2, mins=45, title="Draft v2 release notes", branch="release/2.0",
         idle_min=14),
]
HISTORY_PROJECTS = [("web_shop", "claude-opus-5-5", "medium", 1.0), ("firmware", "claude-sonnet-5-5", "high", .55),
                    ("docs", "claude-sonnet-5-5", "medium", .25), ("tools", "claude-haiku-5-5", "low", .08)]


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def slug(path):
    return path.replace("/", "-")


def tool_input(tool, cwd, rng, file=None):
    f = file or rng.choice(FILES)
    if tool == "Read":
        return {"file_path": "%s/%s" % (cwd, f)}
    if tool in ("Edit", "Write"):
        return {"file_path": "%s/%s" % (cwd, f), "old_string": "a", "new_string": "b", "content": "x"}
    if tool == "Grep":
        return {"pattern": rng.choice(["TODO", "def checkout", "class Cart"]), "path": cwd + "/src"}
    return {"command": rng.choice(BASH)}


def gen_transcript(sp, sid, start, end, cwd, home, live=True, history_calls=None):
    """Return (records, bg_files). `end` is the time of the last API call."""
    rng = random.Random(sp["name"] + sid)
    recs, bg_files = [], []

    def add(rec, ts):
        rec["timestamp"] = iso(ts)
        rec["sessionId"] = sid
        rec["cwd"] = cwd
        rec["gitBranch"] = sp.get("branch", "main")
        recs.append(rec)

    recs.append({"type": "permission-mode", "permissionMode": "auto", "sessionId": sid})
    recs.append({"type": "ai-title", "aiTitle": sp["title"], "sessionId": sid})
    add({"type": "api-request", "params": {"model": sp["model"], "output_config": {"effort": sp["effort"]}}}, start)

    times, t = [], start
    while t < end:
        times.append(t)
        t += rng.uniform(.6, 1.4) * sp["dt"]
    if history_calls:
        step = (end - start) / history_calls
        times = [start + i * step for i in range(history_calls)]
    if live and not sp.get("agent"):          # this machine is silent while the phone is used (see make_limits)
        times = [x for x in times if not (NOW - 2.2 * H - 240 < x < NOW - 1.8 * H + 240)] or times
    times[-1] = end
    n = len(times)
    win, bounds = sp["win"], [0] + sp.get("compact", []) + [1]
    seg_prev = 0
    done_bg = sp.get("bg_done")
    for i, ts in enumerate(times):
        frac = (ts - start) / max(1, end - start)
        seg = max(k for k in range(len(bounds) - 1) if frac >= bounds[k])
        if seg != seg_prev:
            add({"type": "system", "subtype": "compact_boundary"}, ts - 1)
            seg_prev = seg
        lo = .05 * win if seg == 0 else .12 * win
        hi = sp["ctx"] * win if seg == len(bounds) - 2 else .93 * win
        local = (frac - bounds[seg]) / (bounds[seg + 1] - bounds[seg])
        prompt = int(lo + (hi - lo) * local ** .9)
        inp = rng.randint(2, 40)
        miss = rng.random() < .03 or (i and times[i] - times[i - 1] > 3000)
        cr = 0 if miss else int((prompt - inp) * rng.uniform(.93, .985))
        cw = max(0, prompt - inp - cr)
        burst = .5 + .5 * math.sin(frac * sp["wave"] * 2 * math.pi + len(sp["name"]))
        out = max(20, int(sp["out"] * rng.uniform(.3, 1.6) * (.4 + 1.2 * burst)))
        think = int(out * rng.uniform(.2, .6)) if sp.get("think", True) else 0
        last = i == n - 1
        pending_live = last and live and sp.get("state") != "idle"
        tool = ["Read", "Edit", "Bash", "Read", "Edit", "Grep", "Bash", "Read", "Write"][i % 9]
        file = FILES[(i - (1 if tool == "Edit" else 0)) % len(FILES)]   # every read is followed by an edit: no loops
        args = None
        if sp.get("loop") and live and n - 6 <= i < n - 1:
            tool, args = "Read", tool_input("Read", cwd, rng, sp["loop"])
        if pending_live:
            tool = "Edit" if sp["pending"] == "Edit" else "Bash"
            args = tool_input("Edit", cwd, rng, "tests/test_cart.py") if tool == "Edit" else {"command": sp["pending"]}
        bg_id = None
        if live and sp.get("bg") and i == n - 8:
            tool, bg_id = "Bash", "br" + rng.randbytes(4).hex()
            args = {"command": sp["bg"][0], "run_in_background": True}
        if live and done_bg and i == n - 14:
            tool, bg_id = "Bash", "bd" + rng.randbytes(4).hex()
            args = {"command": done_bg[0], "run_in_background": True}
        args = args or tool_input(tool, cwd, rng, file)
        tid = "toolu_%s_%d" % (sid[:6], i)
        block = [{"type": "tool_use", "id": tid, "name": tool, "input": args}]
        if live and sp.get("state") == "idle" and last:
            block = [{"type": "text", "text": "Done. The draft is ready for review."}]
        usage = {"input_tokens": inp, "cache_creation_input_tokens": cw, "cache_read_input_tokens": cr,
                 "output_tokens": out, "output_tokens_details": {"thinking_tokens": think},
                 "cache_creation": {"ephemeral_1h_input_tokens": cw, "ephemeral_5m_input_tokens": 0}}
        add({"type": "assistant", "message": {"id": "msg_%s_%d" % (sid[:6], i), "model": sp["model"],
                                              "role": "assistant", "usage": usage, "content": block}}, ts)
        if block[0]["type"] == "text" or pending_live:
            continue
        result_text, extra = "ok", {}
        if bg_id:
            out_file = os.path.join(home, "tmp", "tasks", bg_id + ".output")
            bg_files.append(out_file)
            result_text = ("Command running in background with ID: %s. Output is being written to: %s. "
                           "You will be notified when it completes." % (bg_id, out_file))
            extra = {"toolUseResult": {"backgroundTaskId": bg_id}}
            if bg_id.startswith("bd"):
                body = ("<task-notification>\n<task-id>%s</task-id>\n<tool-use-id>%s</tool-use-id>\n"
                        "<output-file>%s</output-file>\n<status>completed</status>\n<summary>Background command "
                        "\"%s\" completed (exit code 0)</summary>\n</task-notification>" % (bg_id, tid, out_file, done_bg[0]))
                add({"type": "queue-operation", "operation": "enqueue", "content": body}, ts + 120)
        add(dict({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tid, "content": result_text}]}}, **extra), ts + rng.uniform(2, 12))
    if sp.get("queued") and live:
        add({"type": "queue-operation", "operation": "enqueue", "content": sp["queued"]}, end - 40)
    return recs, bg_files


def write_jsonl(path, recs):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        for r in recs:
            fh.write(json.dumps(r) + "\n")


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh)


def make_limits(sids):
    """Rows for the status-line tap log: a 5 h window at ~80% with a phone-usage
    blind spot, and a 7-day window at ~66%."""
    rng = random.Random(7)
    r5, r7 = NOW + 1.4 * H, NOW + 1.7 * 86400
    day_target = {0: 26, 1: 10, 2: 8, 3: 9, 4: 7, 5: 4}
    gap = (NOW - 2.2 * H, NOW - 1.8 * H)
    steps = []
    for k in range(5, -1, -1):
        end = NOW - 24 * H * k - (60 if k == 0 else 0)
        t = end - 8 * H
        while t <= end:
            if not (k == 0 and gap[0] < t < gap[1]):
                steps.append((t, k, .3 + rng.random() * 1.4 + (1.5 if rng.random() < .06 else 0)))
            t += 120
    sum_day, sum_win = {}, {}
    for t, k, b in steps:
        sum_day[k] = sum_day.get(k, 0) + b
        w = int((r5 - t) // (5 * H))
        sum_win[w] = sum_win.get(w, 0) + b
    win_target = lambda w: 74 if w == 0 else 55 if w == 1 else 50
    rows, c7, c5 = [], 0.0, {}
    jumped = False
    for t, k, b in steps:
        w = int((r5 - t) // (5 * H))
        if not jumped and k == 0 and t >= gap[1]:
            jumped = True
            c5[0] = c5.get(0, 0) + 6
            c7 += 2.4
        c5[w] = c5.get(w, 0) + b * win_target(w) / sum_win[w]
        c7 += b * day_target[k] / sum_day[k]
        rows.append({"ts": round(t, 1), "sid": sids[0],
                     "five_hour": {"pct": round(min(c5[w], 100), 1), "resets": int(r5 - 5 * H * w)},
                     "seven_day": {"pct": round(min(c7, 100), 1), "resets": int(r7)}})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--no-tap", action="store_true", help="leave out limits, status files and the hook")
    ap.add_argument("--pid", type=int, default=os.getpid(), help="a live pid to register the demo sessions under")
    args = ap.parse_args()
    home = os.path.abspath(args.out)
    shutil.rmtree(home, ignore_errors=True)
    os.makedirs(home)
    rng = random.Random(1)
    sids = []

    for i, sp in enumerate(SESSIONS):
        sid = "%08x-demo-%04d-0000-000000000000" % (rng.getrandbits(32), i)
        sids.append(sid)
        cwd = "/Users/demo/work/" + sp["proj"]
        idle = sp.get("idle_min", 0) * 60
        end = NOW - (idle if idle else rng.uniform(8, 24))
        start = end - sp["mins"] * 60
        recs, bg_files = gen_transcript(sp, sid, start, end, cwd, home)
        proj_dir = os.path.join(home, "projects", slug(cwd))
        write_jsonl(os.path.join(proj_dir, sid + ".jsonl"), recs)
        for f in bg_files:
            os.makedirs(os.path.dirname(f), exist_ok=True)
            with open(f, "w") as fh:
                fh.write("\n".join("collected %d items" % n if n % 3 else "tests/test_%d.py ........ [%d%%]" % (n, n * 4)
                                   for n in range(1, 18)) + "\n")
        for j, (desc, kind, model, effort, finished) in enumerate(sp.get("agents", [])):
            asp = dict(name=desc, model=model, effort=effort, ctx=.3, win=200_000, out=300, dt=26, wave=4,
                       title=desc, branch=sp["branch"], state="working", pending="grep -rn cart src", agent=True)
            a_end = NOW - (900 if finished else rng.uniform(10, 20))
            a_recs, _ = gen_transcript(asp, sid + "a%d" % j, a_end - 600, a_end, cwd, home)
            aid = "a%016x" % rng.getrandbits(64)
            write_jsonl(os.path.join(proj_dir, sid, "subagents", "agent-%s.jsonl" % aid), a_recs)
            write_json(os.path.join(proj_dir, sid, "subagents", "agent-%s.meta.json" % aid),
                       {"agentType": kind, "description": desc, "finished": finished})
        write_json(os.path.join(home, "sessions", "%d_%d.json" % (args.pid, i)),
                   {"pid": args.pid, "sessionId": sid, "cwd": cwd, "startedAt": int(start * 1000), "name": sp["name"],
                    "kind": "interactive", "status": "idle" if sp["state"] == "idle" else "busy",
                    "updatedAt": int(end * 1000)})

    # five days of history across projects (finished sessions)
    for day in range(1, 6):
        for p, (proj, model, effort, weight) in enumerate(HISTORY_PROJECTS):
            if rng.random() > .5 + weight / 2:
                continue
            sp = dict(name="%s-%d" % (proj, day), proj=proj, model=model, effort=effort, ctx=rng.uniform(.3, .7),
                      win=1_000_000 if "opus" in model else 200_000, out=int(500 + 700 * weight), dt=20, wave=3,
                      title="History %s" % proj, branch="main", state="done")
            end = NOW - day * 24 * H + rng.uniform(-6, -2) * H
            n = int(40 + 120 * weight)
            sid = "%08x-hist-%04d-0000-000000000000" % (rng.getrandbits(32), day * 10 + p)
            recs, _ = gen_transcript(sp, sid, end - 2 * H, end, "/Users/demo/work/" + proj, home, live=False, history_calls=n)
            write_jsonl(os.path.join(home, "projects", slug("/Users/demo/work/" + proj), sid + ".jsonl"), recs)

    # background job and scheduled tasks
    write_json(os.path.join(home, "jobs", "8c81ddc2", "state.json"),
               {"state": "blocked", "tempo": "blocked", "tokens": 9687, "name": "Reconcile photo manifest",
                "cwd": "/Users/demo/work/photos", "intent": "Investigate why 377 of 430 portraits were detected",
                "detail": "Found 2 bugs in manifest merging. Fixes applied. The 377 vs 430 gap is still open.",
                "needs": "Re-run extraction, or investigate the detection gap first?",
                "suggestedReply": "Investigate the gap first, then re-run extraction"})
    for name, desc in [("weekly-report", "Every Friday at 4pm: summarize the week's merged PRs and email the team"),
                       ("dependency-check", "Hourly on weekdays: check for outdated packages and open an issue"),
                       ("backup-notes", "Sunday evening: archive notes and push to the backup repo")]:
        os.makedirs(os.path.join(home, "scheduled-tasks", name), exist_ok=True)
        with open(os.path.join(home, "scheduled-tasks", name, "SKILL.md"), "w") as fh:
            fh.write("---\nname: %s\ndescription: %s\n---\n\nSteps...\n" % (name, desc))

    os.makedirs(os.path.join(home, "claudemon", "status"), exist_ok=True)
    write_json(os.path.join(home, "claudemon", "config.json"), {"tap_prompt_seen": True})
    if not args.no_tap:
        rows = make_limits(sids)
        with open(os.path.join(home, "claudemon", "limits.jsonl"), "w") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        for sp, sid in zip(SESSIONS, sids):
            write_json(os.path.join(home, "claudemon", "status", sid + ".json"),
                       {"session_id": sid, "_seen": NOW, "model": {"id": sp["model"]}, "effort": {"level": sp["effort"]},
                        "context_window": {"context_window_size": sp["win"]},
                        "cost": {"total_cost_usd": round(sp["mins"] * (.35 if "opus" in sp["model"] else .12), 2)},
                        "rate_limits": {"five_hour": rows[-1]["five_hour"], "seven_day": rows[-1]["seven_day"]}})
            if sp["state"] == "needs":
                write_json(os.path.join(home, "claudemon", "status", sid + ".hook.json"),
                           {"event": "Notification", "ts": time.time() + 30, "type": "permission_prompt",
                            "message": "Claude needs your permission to use Edit", "tool": "Edit"})
    print("demo data in", home)


if __name__ == "__main__":
    main()
