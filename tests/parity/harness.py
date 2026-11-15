#!/usr/bin/env python3
"""Parity harness: run the same scenarios against a pinned baseline commit and the
tree under test, with the same inputs and interpreter, and show every difference.

    python3 tests/parity/harness.py                       # BASELINE pin vs the working tree
    python3 tests/parity/harness.py --candidate baseline  # the pin against itself (stability)
    python3 tests/parity/harness.py --baseline HEAD~1     # a commit against its parent
    python3 tests/parity/harness.py --python /usr/bin/python3 --python python3.13 --repeat 20

Each run checks the baseline out into a fresh `git worktree add --detach` under a
mktemp directory (never a fixed path, so several runs can share a repository) and
removes it in a finally. Every Python it starts goes through frozen.py; every
scenario gets fresh copies of its fixture homes, and CLAUDE_CONFIG_DIR and HOME
always point into the run's temp directory. The harness refuses to run otherwise.

Every source of drift it handles is listed in MASKS below; nothing else is hidden.
Exit status: 0 parity, 1 differences, 2 the harness itself failed.
"""

import argparse
import concurrent.futures
import difflib
import fcntl
import hashlib
import json
import os
import pwd
import re
import select
import shutil
import signal
import stat
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
FROZEN = HERE / "frozen.py"
DRIVER = HERE / "driver.py"
PIN_FILE = HERE / "BASELINE"
ADAPTERS = {"baseline": HERE / "adapter_baseline.py", "tree": HERE / "adapter_tree.py"}

FROZEN_TIME = 1794225600          # 2026-11-09 12:00:00 UTC
LOCALE = "C.UTF-8"

# ── every mask and pin, in one place ─────────────────────────────────────────
MASKS = [
    ("clock", "time.time() and datetime.now()/today()/utcnow() are frozen at FROZEN_TIME by frozen.py, "
              "which starts every Python the harness runs (CLI, driver, pty, demo generator)"),
    ("fixture mtimes", "every file and folder of a fixture home is set to FROZEN_TIME"),
    ("tap _seen", "claudemon/status/<sid>.json: the value of \"_seen\" becomes <T> (the tap runs under /bin/sh, unfrozen)"),
    ("tap ts", "claudemon/limits.jsonl, claudemon/tap_last.json and claudemon/status/<sid>.hook.json: "
               "the value of \"ts\" becomes <T>"),
    ("index thread", "the driver waits for Store indexing and fails (exit 3) after 60 s; it never draws early"),
    ("process table", "CLAUDEMON_DEMO=1, except the fake-ps scenarios, which put a fixed ps first on PATH"),
    ("live pids", "demo sessions register under a live `sleep` helper, one per side; its pid becomes <PID>"),
    ("temp names", ".<digits>.tmp becomes .<PID>.tmp and settings.<digits>.bak.json becomes settings.<NS>.bak.json"),
    ("hash, tz, locale", "PYTHONHASHSEED=0, TZ=UTC, LC_ALL=LANG=%s, COLUMNS=100 and LINES=40 (outside a pty), TERM=xterm-256color" % LOCALE),
    ("interpreter", "the interpreter's paths (as given, sys.executable, realpath, /usr/bin/python3) become <PY>"),
    ("paths", "the tree root becomes <ROOT>, CLAUDE_CONFIG_DIR <HOME>, HOME <USER>, the scenario folder <SCN>, "
              "the run folder <TMP>"),
    ("shared state", "a fresh copy of each fixture home per side and scenario"),
]

# Declared deltas: output keys (scenario/key, fnmatch-style) allowed to differ, with the reason.
# Empty until a phase lands one of the plan's declared deltas.
DELTAS = {}


class HarnessError(Exception):
    pass


# ── safety ───────────────────────────────────────────────────────────────────
REAL_HOME = os.path.realpath(pwd.getpwuid(os.getuid()).pw_dir)
REAL_CLAUDE = os.path.join(REAL_HOME, ".claude")


def check_safe(env):
    for k in ("CLAUDE_CONFIG_DIR", "HOME"):
        v = env.get(k)
        if not v:
            raise HarnessError("refusing to run: %s is not set" % k)
        r = os.path.realpath(v)
        if r == REAL_HOME or r == REAL_CLAUDE or r.startswith(REAL_CLAUDE + os.sep) or \
                r == os.path.join(REAL_HOME, ".claude.json"):
            raise HarnessError("refusing to run: %s resolves to the real %s" % (k, r))


# ── git ──────────────────────────────────────────────────────────────────────
def git(*args, cwd=REPO, check=True):
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    if check and r.returncode:
        raise HarnessError("git %s: %s" % (" ".join(args), r.stderr.strip()))
    return r.stdout.strip()


def resolve(rev):
    def verify():
        r = subprocess.run(["git", "rev-parse", "--verify", "--quiet", rev + "^{commit}"], cwd=str(REPO),
                           capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None
    sha = verify()
    if sha is None:
        git("fetch", "--quiet", "origin", rev, check=False)  # CI checkouts are shallow
        sha = verify()
    if sha is None:
        raise HarnessError("unknown commit %s" % rev)
    return sha


def pinned():
    try:
        text = PIN_FILE.read_text().split("#", 1)[0].strip()
    except OSError:
        raise HarnessError("no pinned baseline: %s is missing" % PIN_FILE)
    if not text:
        raise HarnessError("no pinned baseline in %s" % PIN_FILE)
    return text.split()[0]


def add_worktree(rev, parent):
    path = os.path.join(parent, "baseline")
    for attempt in range(5):
        r = subprocess.run(["git", "worktree", "add", "--detach", "--quiet", path, rev], cwd=str(REPO),
                           capture_output=True, text=True)
        if r.returncode == 0:
            return path
        time.sleep(0.2 * (attempt + 1))                      # another run was adding one at the same moment
    raise HarnessError("git worktree add %s: %s" % (rev, r.stderr.strip()))


def remove_worktree(path):
    subprocess.run(["git", "worktree", "remove", "--force", path], cwd=str(REPO), capture_output=True)
    shutil.rmtree(path, ignore_errors=True)
    subprocess.run(["git", "worktree", "prune"], cwd=str(REPO), capture_output=True)


# ── output helpers ───────────────────────────────────────────────────────────
ESC_KEEP = re.compile(rb"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-9;]*t")
ESC_ANY = re.compile(rb"\x1b\[[0-9;?>=]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()*+][0-9A-Za-z]|\x1b[=>78DEHMc]")
TS_KEYS = {"_seen": re.compile(r'("_seen"\s*:\s*)-?[0-9][0-9.eE+-]*'),
           "ts": re.compile(r'("ts"\s*:\s*)-?[0-9][0-9.eE+-]*')}


CUF = re.compile(rb"\x1b\[([0-9]*)C")
MOVE = re.compile(rb"\x1b\[[0-9;]*[HfdG]|\r|\n")


def screen_text(raw):
    """The text a pty stream drew, roughly: cursor-forward becomes spaces (curses skips blank
    cells that way), other cursor moves become line breaks, other escapes are dropped."""
    raw = CUF.sub(lambda m: b" " * int(m.group(1) or 1), raw)
    raw = MOVE.sub(b"\n", raw)
    return ESC_ANY.sub(b"", raw).decode("utf-8", "replace").replace("\x0e", "").replace("\x0f", "")


def mask_json_times(rel, text):
    name = os.path.basename(rel)
    if rel.startswith("status/") and name.endswith(".hook.json"):
        return TS_KEYS["ts"].sub(r"\1<T>", text)
    if rel.startswith("status/") and name.endswith(".json"):
        return TS_KEYS["_seen"].sub(r"\1<T>", text)
    if rel in ("limits.jsonl", "tap_last.json"):
        return TS_KEYS["ts"].sub(r"\1<T>", text)
    return text


def describe_file(path, rel=""):
    st = os.lstat(path)
    mode = "%o" % stat.S_IMODE(st.st_mode)
    if stat.S_ISLNK(st.st_mode):
        return "link -> %s" % os.readlink(path)
    if stat.S_ISDIR(st.st_mode):
        return "dir %s" % mode
    data = open(path, "rb").read()
    if rel.endswith(".py"):
        return "file %s sha256:%s" % (mode, hashlib.sha256(data).hexdigest())
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return "file %s sha256:%s" % (mode, hashlib.sha256(data).hexdigest())
    return "file %s\n%s" % (mode, mask_json_times(rel, text))


def tree_of(base):
    out = []
    if not os.path.lexists(base):
        return ["(absent)"]
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames.sort()
        for name in sorted(dirnames) + sorted(filenames):
            p = os.path.join(dirpath, name)
            rel = os.path.relpath(p, base)
            out.append("%s: %s" % (rel, describe_file(p, rel)))
    return out


# ── one side of the comparison ───────────────────────────────────────────────
def load_constants(adapter):
    ns = {}
    exec(compile(open(adapter).read(), str(adapter), "exec"), ns)
    return ns


class Side:
    def __init__(self, name, root, adapter, run_dir, python):
        self.name = name
        self.root = os.path.realpath(root)
        self.adapter = str(adapter)
        self.const = load_constants(adapter)
        self.dir = os.path.join(run_dir, name)
        self.run_dir = run_dir
        self.python = python
        os.makedirs(self.dir)
        self.helper = subprocess.Popen(["sleep", "3600"])
        self.templates = {}
        self.lock = threading.Lock()
        exe = subprocess.run([python, "-c", "import sys; print(sys.executable)"], capture_output=True, text=True)
        names = {python, exe.stdout.strip(), os.path.realpath(python), os.path.realpath(exe.stdout.strip()),
                 "/usr/bin/python3"}
        if "/Cellar/" in exe.stdout:
            names.add(exe.stdout.split("/Cellar/")[0] + "/bin/python3")
        self.pythons = sorted((n for n in names if n and os.sep in n), key=len, reverse=True)

    def close(self):
        self.helper.kill()
        self.helper.wait()

    def path(self, rel):
        return os.path.join(self.root, rel)

    def base_env(self, ctx, demo=True, path=None, extra=None):
        env = {"PATH": path or "/usr/bin:/bin", "HOME": ctx.user, "CLAUDE_CONFIG_DIR": ctx.home,
               "TZ": "UTC", "LC_ALL": LOCALE, "LANG": LOCALE, "PYTHONHASHSEED": "0",
               "PYTHONDONTWRITEBYTECODE": "1", "PARITY_FROZEN_TIME": str(FROZEN_TIME),
               "COLUMNS": "100", "LINES": "40", "TERM": "xterm-256color", "PYTHON_COLORS": "0", "NO_COLOR": "1"}
        if demo:
            env["CLAUDEMON_DEMO"] = "1"
        env.update(extra or {})
        check_safe(env)
        return env

    def template(self, kind):
        """A fixture home generated once per side: 'demo' or 'notap' (make_demo), or 'empty'."""
        with self.lock:
            return self._template(kind)

    def _template(self, kind):
        if kind not in self.templates:
            dest = os.path.join(self.dir, "_templates", kind)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            if kind == "empty":
                os.makedirs(dest)
            else:
                args = [dest, "--pid", str(self.helper.pid)] + (["--no-tap"] if kind == "notap" else [])
                env = {"PATH": "/usr/bin:/bin", "HOME": dest, "CLAUDE_CONFIG_DIR": dest, "TZ": "UTC",
                       "LC_ALL": LOCALE, "LANG": LOCALE, "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1",
                       "PARITY_FROZEN_TIME": str(FROZEN_TIME)}
                check_safe(env)
                r = subprocess.run([self.python, str(FROZEN), self.path(self.const["DEMO"])] + args, env=env,
                                   capture_output=True, text=True, timeout=120)
                if r.returncode:
                    raise HarnessError("%s: make_demo failed: %s" % (self.name, r.stderr[-800:]))
            touch_all(dest)
            self.templates[kind] = dest
        return self.templates[kind]


def touch_all(top):
    for dirpath, dirnames, filenames in os.walk(top):
        for n in filenames + dirnames:
            p = os.path.join(dirpath, n)
            if not os.path.islink(p):
                os.utime(p, (FROZEN_TIME, FROZEN_TIME))
    os.utime(top, (FROZEN_TIME, FROZEN_TIME))


# ── the scenario context: what a scenario can do on one side ─────────────────
class Ctx:
    def __init__(self, side, name):
        self.side = side
        self.dir = os.path.join(side.dir, re.sub(r"[^A-Za-z0-9_.-]", "_", name))
        os.makedirs(self.dir)
        self.user = os.path.join(self.dir, "user")
        os.makedirs(self.user)
        self.home = os.path.join(self.user, ".claude")
        self.root = side.root
        self.pid = side.helper.pid

    # fixtures
    def fixture(self, template="empty", home_name=".claude"):
        self.home = os.path.join(self.user, home_name)
        shutil.copytree(self.side.template(template), self.home, symlinks=True)
        return self.home

    def write(self, rel, text, mode=None):
        p = os.path.join(self.home, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
        if mode is not None:
            os.chmod(p, mode)
        touch_all(self.home)
        return p

    def read(self, rel):
        try:
            with open(os.path.join(self.home, rel), encoding="utf-8") as fh:
                return fh.read()
        except OSError as e:
            return "(%s)" % type(e).__name__

    def env(self, **kw):
        return self.side.base_env(self, **kw)

    # running things
    def py(self, argv, stdin=None, timeout=120, **envkw):
        env = self.env(**envkw)
        r = subprocess.run([self.side.python, str(FROZEN)] + argv, env=env, cwd=self.dir, input=stdin,
                           capture_output=True, timeout=timeout)
        return {"code": r.returncode, "stdout": r.stdout.decode("utf-8", "replace"),
                "stderr": r.stderr.decode("utf-8", "replace")}

    def cli(self, *args, stdin=None, **envkw):
        return self.py([self.side.path(self.side.const["CLI"])] + list(args), stdin=stdin, **envkw)

    def driver(self, jobs, **envkw):
        jobs_path = os.path.join(self.dir, "jobs.%d.json" % len(os.listdir(self.dir)))
        with open(jobs_path, "w", encoding="utf-8") as fh:
            json.dump(jobs, fh)
        r = self.py([str(DRIVER), self.side.adapter, self.side.root, jobs_path], timeout=600, **envkw)
        if r["code"] != 0:
            raise HarnessError("%s: driver failed (exit %d): %s" % (self.side.name, r["code"], r["stderr"][-1500:]))
        return json.loads(r["stdout"])["results"]

    def sh(self, command, stdin="", timeout=30, **envkw):
        """Run a command the way Claude Code runs the status line: /bin/sh -c, real clock."""
        env = self.env(**envkw)
        env.pop("PARITY_FROZEN_TIME")
        r = subprocess.run(["/bin/sh", "-c", command], env=env, cwd=self.dir, input=stdin.encode(),
                           capture_output=True, timeout=timeout)
        return {"code": r.returncode, "stdout": r.stdout.decode("utf-8", "replace"),
                "stderr": r.stderr.decode("utf-8", "replace")}

    def statusline(self):
        try:
            return json.loads(self.read("settings.json"))["statusLine"]["command"]
        except (ValueError, KeyError, TypeError):
            return None

    def hook(self):
        try:
            for e in json.loads(self.read("settings.json"))["hooks"]["Notification"]:
                for h in e["hooks"]:
                    if h["command"].endswith("# claudemon"):
                        return h["command"]
        except (ValueError, KeyError, TypeError):
            pass
        return None

    def state(self):
        """settings.json (following a symlink) plus the tree of claudemon/ in the home."""
        p = os.path.join(self.home, "settings.json")
        out = {"settings.json": describe_file(p) if os.path.lexists(p) else "(absent)"}
        if os.path.islink(p):
            out["settings.json target"] = describe_file(os.path.realpath(p)) if os.path.exists(p) else "(dangling)"
        out["claudemon/"] = tree_of(os.path.join(self.home, "claudemon"))
        return out

    def sha(self, rel):
        try:
            return hashlib.sha256(open(rel if os.path.isabs(rel) else self.side.path(rel), "rb").read()).hexdigest()
        except OSError as e:
            return "(%s)" % type(e).__name__

    def stubs(self, names, exit_code=0, err=""):
        """A PATH folder of recording stubs (for --window); returns (PATH, log path, env)."""
        d = tempfile.mkdtemp(prefix="stubs-", dir=self.dir)     # a fresh folder per call: only these stubs
        log = os.path.join(d, "stub.log")
        for n in names:
            p = os.path.join(d, n)
            with open(p, "w") as fh:
                fh.write("#!/bin/sh\n"
                         "{ printf '%s' \"${0##*/}\"; for a in \"$@\"; do printf ' <%s>' \"$a\"; done; printf '\\n'; }"
                         " >> \"$PARITY_STUB_LOG\"\n"
                         "if [ -n \"$PARITY_STUB_ERR\" ]; then printf '%s\\n' \"$PARITY_STUB_ERR\" >&2; fi\n"
                         "exit \"${PARITY_STUB_EXIT:-0}\"\n")
            os.chmod(p, 0o755)
        return d, log, {"PARITY_STUB_LOG": log, "PARITY_STUB_EXIT": str(exit_code), "PARITY_STUB_ERR": err}

    def wait_log(self, log, timeout=10):
        """The stub log once a stub has written it (a Popen'd terminal can outlive the CLI)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if os.path.exists(log) and open(log, "rb").read().endswith(b"\n"):
                time.sleep(0.05)
                return open(log, encoding="utf-8", errors="replace").read()
            time.sleep(0.05)
        return "(no stub ran)"

    def fake_ps(self, lines):
        d = os.path.join(self.dir, "fakeps")
        os.makedirs(d, exist_ok=True)
        table = os.path.join(d, "table.txt")
        with open(table, "w") as fh:
            fh.write("".join(line + "\n" for line in lines))
        p = os.path.join(d, "ps")
        with open(p, "w") as fh:
            fh.write("#!/bin/sh\nexec /bin/cat %s\n" % table)
        os.chmod(p, 0o755)
        return d + ":/usr/bin:/bin"

    def pty(self, args, steps, size=(36, 120), **envkw):
        """Start the TUI in a pseudo-terminal and drive it. Returns what a user could observe:
        exit status, title/resize escapes, and which awaited phrases appeared."""
        env = self.env(**envkw)
        env.pop("COLUMNS")              # ncurses would take these over the pty's real size
        env.pop("LINES")
        master, slave = os.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", size[0], size[1], 0, 0))
        proc = subprocess.Popen([self.side.python, str(FROZEN), self.side.path(self.side.const["CLI"])] + list(args),
                                stdin=slave, stdout=slave, stderr=slave, env=env, cwd=self.dir,
                                start_new_session=True)
        os.close(slave)
        buf = bytearray()
        seen = []

        def pump(until=None, timeout=0.0):
            deadline = time.monotonic() + timeout
            while True:
                if until is not None and until in screen_text(bytes(buf)):
                    return True
                left = deadline - time.monotonic()
                if left <= 0:
                    return until is None
                r, _, _ = select.select([master], [], [], min(left, 0.1))
                if r:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        chunk = b""
                    if not chunk:
                        return until is None or until in screen_text(bytes(buf))
                    buf.extend(chunk)

        try:
            for step in steps:
                op = step[0]
                if op == "wait":
                    seen.append([step[1], pump(step[1], step[2] if len(step) > 2 else 30)])
                elif op == "key":
                    os.write(master, step[1].encode())
                    pump(timeout=0.4)
                elif op == "size":
                    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", step[1], step[2], 0, 0))
                    proc.send_signal(signal.SIGWINCH)
                    pump(timeout=0.4)
                elif op == "signal":
                    proc.send_signal(getattr(signal, step[1]))
                elif op == "sleep":
                    pump(timeout=step[1])
            deadline = time.monotonic() + 20
            while proc.poll() is None and time.monotonic() < deadline:
                pump(timeout=0.1)
            code = proc.poll()
            if code is None:
                proc.kill()
                proc.wait()
                code = "killed: still running 20 s after the last step"
            pump(timeout=0.2)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            os.close(master)
        escapes = [m.group(0).decode("utf-8", "replace") for m in ESC_KEEP.finditer(bytes(buf))]
        return {"code": code, "escapes": escapes, "waits": seen}

    # masking
    def mask(self, text):
        pairs = [(self.home, "<HOME>"), (os.path.realpath(self.home), "<HOME>"), (self.user, "<USER>"),
                 (self.dir, "<SCN>"), (self.side.root, "<ROOT>"), (self.side.run_dir, "<TMP>")]
        pairs += [(p, "<PY>") for p in self.side.pythons]
        for old, new in sorted(pairs, key=lambda p: len(p[0]), reverse=True):
            text = text.replace(old, new)
        text = re.sub(r"(?<![0-9])%d(?![0-9])" % self.pid, "<PID>", text)
        text = re.sub(r"\.[0-9]+\.tmp\b", ".<PID>.tmp", text)
        text = re.sub(r"settings\.[0-9]+\.bak\.json", "settings.<NS>.bak.json", text)
        return text


# ── running and comparing ────────────────────────────────────────────────────
def run_scenario(side, scen):
    ctx = Ctx(side, scen.name)
    try:
        outputs = scen.fn(ctx)
    except HarnessError:
        raise
    except Exception:
        raise HarnessError("%s/%s raised:\n%s" % (side.name, scen.name, traceback.format_exc()))
    return {k: ctx.mask(json.dumps(v, indent=1, ensure_ascii=False)) for k, v in outputs.items()}


def declared(key):
    import fnmatch
    for pat, why in DELTAS.items():
        if fnmatch.fnmatchcase(key, pat):
            return why
    return None


def compare(a, b, names, max_lines):
    diffs, allowed = [], []
    for scen in names:
        ka, kb = a[scen], b[scen]
        for k in sorted(set(ka) | set(kb)):
            va, vb = ka.get(k, "(missing)"), kb.get(k, "(missing)")
            if va == vb:
                continue
            key = "%s/%s" % (scen, k)
            why = declared(key)
            if why:
                allowed.append((key, why))
                continue
            d = list(difflib.unified_diff(va.splitlines(), vb.splitlines(), "baseline/" + key, "candidate/" + key,
                                          lineterm="", n=2))
            diffs.append((key, d[:max_lines] + (["... %d more lines" % (len(d) - max_lines)] if len(d) > max_lines else [])))
    return diffs, allowed


def one_run(args, python, base_rev, cand):
    import scenarios
    run_dir = os.path.realpath(tempfile.mkdtemp(prefix="claudemon-parity-"))
    worktrees, sides = [], []
    t0 = time.monotonic()
    try:
        base_root = add_worktree(base_rev, tempfile.mkdtemp(prefix="wt-", dir=run_dir))
        worktrees.append(base_root)
        if cand == "tree":
            cand_root, cand_adapter = str(REPO), ADAPTERS["tree"]
        else:
            cand_root = add_worktree(cand, tempfile.mkdtemp(prefix="wt-", dir=run_dir))
            worktrees.append(cand_root)
            cand_adapter = ADAPTERS[args.candidate_adapter]
        sides = [Side("baseline", base_root, ADAPTERS["baseline"], run_dir, python),
                 Side("candidate", cand_root, cand_adapter, run_dir, python)]
        scens = [s for s in scenarios.ALL if not args.only or any(o in s.name for o in args.only)]
        results = {s.name: {} for s in sides}
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futs = {pool.submit(run_scenario, side, scen): (side, scen) for scen in scens for side in sides}
            for f in concurrent.futures.as_completed(futs):
                side, scen = futs[f]
                results[side.name][scen.name] = f.result()
        names = [s.name for s in scens]
        diffs, allowed = compare(results["baseline"], results["candidate"], names, args.max_lines)
        if args.keep:
            os.makedirs(args.keep, exist_ok=True)
            for side in sides:
                with open(os.path.join(args.keep, "%s.json" % side.name), "w", encoding="utf-8") as fh:
                    json.dump(results[side.name], fh, indent=1, ensure_ascii=False)
        n_keys = sum(len(v) for v in results["baseline"].values())
        return diffs, allowed, len(names), n_keys, time.monotonic() - t0
    finally:
        for side in sides:
            side.close()
        for wt in worktrees:
            remove_worktree(wt)
        shutil.rmtree(run_dir, ignore_errors=True)


def main(argv=None):
    p = argparse.ArgumentParser(description="claudeMon parity harness")
    p.add_argument("--baseline", help="baseline commit (default: the pin in tests/parity/BASELINE)")
    p.add_argument("--candidate", default="tree",
                   help="'tree' (the working tree, default), 'baseline' (the baseline again), or a commit")
    p.add_argument("--candidate-adapter", choices=sorted(ADAPTERS), default="baseline",
                   help="adapter for a candidate commit (default: baseline)")
    p.add_argument("--python", action="append", help="interpreter for both sides (repeatable; default: this one)")
    p.add_argument("--repeat", type=int, default=1, help="run N times, stopping at the first failure")
    p.add_argument("--only", action="append", help="only scenarios whose name contains this (repeatable)")
    p.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 2), help="scenarios run at once")
    p.add_argument("--max-lines", type=int, default=60, help="diff lines shown per difference")
    p.add_argument("--keep", help="write both sides' masked outputs to this folder")
    p.add_argument("--list-masks", action="store_true", help="print every mask and pin, then exit")
    args = p.parse_args(argv)
    if args.list_masks:
        for name, what in MASKS:
            print("%-16s %s" % (name, what))
        print("%-16s %s" % ("declared deltas", ", ".join(sorted(DELTAS)) or "none"))
        return 0
    sys.dont_write_bytecode = True     # keep the tree under test free of __pycache__
    sys.path.insert(0, str(HERE))
    try:
        base = resolve(args.baseline or pinned())
        cand = "tree" if args.candidate == "tree" else resolve(base if args.candidate == "baseline" else args.candidate)
        pythons = args.python or [sys.executable]
        print("parity: baseline %s vs %s" % (base[:12], "working tree" if cand == "tree" else cand[:12]), flush=True)
        for i in range(args.repeat):
            for py in pythons:
                diffs, allowed, n_scen, n_keys, dt = one_run(args, py, base, cand)
                tag = "run %d/%d %s" % (i + 1, args.repeat, py)
                for key, why in allowed:
                    print("  declared delta %s: %s" % (key, why))
                if diffs:
                    print("%s: FAIL, %d of %d outputs differ (%d scenarios, %.1f s)" % (tag, len(diffs), n_keys, n_scen, dt))
                    for key, lines in diffs[:args.max_lines]:
                        print("--- %s" % key)
                        print("\n".join(lines))
                    return 1
                print("%s: ok, %d outputs in %d scenarios identical (%.1f s)" % (tag, n_keys, n_scen, dt), flush=True)
    except HarnessError as e:
        print("parity harness error: %s" % e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
