"""Unit tests for the data layer and the TUI's input handling, using small fixtures."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from claudemon.sources import limits  # noqa: E402
from claudemon.sources import procs  # noqa: E402
from claudemon.sources import transcript  # noqa: E402
from claudemon.sources.transcript import Transcript  # noqa: E402


def jl(*recs):
    return "".join((r if isinstance(r, str) else json.dumps(r)) + "\n" for r in recs)


def asst(mid, ts="2026-11-09T10:00:00Z", tools=(), usage=None, model="claude-opus-5-5"):
    content = [{"type": "tool_use", "id": tid, "name": name, "input": inp} for tid, name, inp in tools]
    return {"type": "assistant", "timestamp": ts, "message": {
        "id": mid, "model": model, "usage": usage or {"input_tokens": 10, "output_tokens": 5}, "content": content}}


def result(tid, text="ok", extra=None, ts="2026-11-09T10:00:01Z"):
    rec = {"type": "user", "timestamp": ts,
           "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "content": text}]}}
    if extra is not None:
        rec["toolUseResult"] = extra
    return rec


class TempFiles(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def transcript(self, text, name="t.jsonl"):
        p = self.dir / name
        p.write_text(text)
        t = Transcript(str(p))
        t.refresh()
        return t


class TranscriptParsing(TempFiles):
    def test_wrong_shapes_do_not_raise_or_stop_later_lines(self):
        bad = [42, "str", None, [1], {"type": "assistant", "message": "str"},
               {"type": "assistant", "message": {"content": "x", "usage": {"input_tokens": "9"}}},
               {"type": "assistant", "message": {"id": "m0", "content": [{"type": "tool_use", "id": ["x"]}]}},
               {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "a",
                                                          "content": [{"text": None}]}]}},
               {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": {}, "content": 5}]}},
               {"type": "queue-operation", "operation": "enqueue", "content": 7},
               {"type": "attachment", "attachment": "x"}, {"type": "api-request", "params": "x"},
               {"cwd": 5, "gitBranch": [], "timestamp": 12},
               {"type": "assistant", "message": {"id": "m1", "content": [{"type": "tool_use", "id": "r1", "name": "Read",
                                                                            "input": {"file_path": ["x"]}}]}}]
        t = self.transcript(jl(*bad) + jl(asst("good", usage={"input_tokens": 100, "output_tokens": 7})))
        self.assertIn("good", t.calls)
        self.assertEqual(t.totals().output, 7 + 5 * 0)
        self.assertIsInstance(t.cwd, str)
        t.totals(), t.stuck_tool()              # derived numbers still work

    def test_task_stop_marks_the_task_stopped(self):
        start = "Command running in background with ID: b6zp. Output is being written to: /tmp/x.output"
        t = self.transcript(jl(
            asst("m1", tools=[("tu1", "Bash", {"command": "sleep 999", "run_in_background": True})]),
            result("tu1", start, {"backgroundTaskId": "b6zp"}),
            asst("m2", tools=[("tu2", "TaskStop", {"task_id": "b6zp"})]),
            result("tu2", '{"message":"Successfully stopped task: b6zp"}', {"task_id": "b6zp"})))
        task = t.bg_tasks["b6zp"]
        self.assertEqual(task.status, "stopped")
        self.assertFalse(task.running)
        self.assertIsNotNone(task.ended)

    def test_a_failed_task_stop_leaves_it_running(self):
        start = "Command running in background with ID: b1. Output is being written to: /tmp/x.output"
        stop = result("tu2", "no such task")
        stop["message"]["content"][0]["is_error"] = True
        t = self.transcript(jl(asst("m1", tools=[("tu1", "Bash", {"command": "x"})]), result("tu1", start),
                               asst("m2", tools=[("tu2", "TaskStop", {"task_id": "b1"})]), stop))
        self.assertTrue(t.bg_tasks["b1"].running)

    def test_blocks_and_partial_tail(self):
        keep = transcript.READ_BLOCK
        transcript.READ_BLOCK = 7               # split records across many reads
        try:
            p = self.dir / "t.jsonl"
            text = jl(*(asst("m%d" % i) for i in range(20)))
            p.write_text(text[:-30])
            t = Transcript(str(p))
            t.refresh()
            self.assertEqual(len(t.calls), 19)
            p.write_text(text)
            t.refresh()
            self.assertEqual(len(t.calls), 20)
        finally:
            transcript.READ_BLOCK = keep

    def test_a_replaced_file_is_read_again(self):
        p = self.dir / "t.jsonl"
        p.write_text(jl(asst("old1"), asst("old2")))
        t = Transcript(str(p))
        t.refresh()
        tmp = self.dir / "new.jsonl"
        tmp.write_text(jl(asst("new1"), asst("new2"), asst("new3")))
        os.replace(tmp, p)
        t.refresh()
        self.assertEqual(sorted(t.calls), ["new1", "new2", "new3"])

    def test_vanished_file(self):
        t = Transcript(str(self.dir / "missing.jsonl"))
        self.assertFalse(t.refresh())


class Limits(TempFiles):
    def log(self, rows):
        p = self.dir / "limits.jsonl"
        p.write_text(jl(*rows))
        lg = limits.LimitLog(p)
        lg.refresh()
        return lg

    def test_malformed_rows_are_skipped(self):
        now = time.time()
        lg = self.log([42, [], {"seven_day": {"pct": 5}}, {"ts": "x", "seven_day": {"pct": 5}},
                       {"ts": now, "seven_day": {"pct": "abc"}}, {"ts": now, "seven_day": "x"},
                       {"ts": now, "seven_day": {"pct": None}}, {"ts": True, "five_hour": {"pct": 1}},
                       {"ts": now, "seven_day": {"pct": 12, "resets": "garbage"}}])
        self.assertEqual([o.pct for o in lg.obs["seven_day"]], [12])
        f = lg.forecast("seven_day")
        self.assertEqual(f.pct, 12)

    def test_stale_sessions_do_not_inflate_the_rate(self):
        """One session rises 1 point an hour; an idle one keeps re-rendering 28%."""
        t0, resets = time.time() - 6 * 3600, time.time() + 5 * 86400
        rows = []
        for i in range(0, 6 * 60, 5):           # every 5 minutes for 6 hours
            ts = t0 + i * 60
            rows.append({"ts": ts, "sid": "fresh", "seven_day": {"pct": 30 + i / 60, "resets": resets}})
            rows.append({"ts": ts + 30, "sid": "stale", "seven_day": {"pct": 28, "resets": resets}})
        f = self.log(rows).forecast("seven_day")
        per_day = f.rate * 86400
        self.assertGreater(f.pct, 35)
        self.assertLess(abs(per_day - 24), 3, per_day)

    def test_window_is_the_newest_one_reported(self):
        now = time.time()
        old, new = now - 3600, now + 5 * 3600 - 600
        lg = self.log([{"ts": now - 300, "sid": "a", "five_hour": {"pct": 4, "resets": new}},
                       {"ts": now - 60, "sid": "b", "five_hour": {"pct": 97, "resets": old}}])
        f = lg.forecast("five_hour")
        self.assertEqual((f.pct, round(f.resets)), (4, round(new)))

    def test_no_reset_time_means_no_stale_filter(self):
        now = time.time()
        lg = self.log([{"ts": now - 600, "five_hour": {"pct": 90}}, {"ts": now - 300, "five_hour": {"pct": 3}},
                       {"ts": now, "five_hour": {"pct": 4}}])
        self.assertEqual(lg.forecast("five_hour").pct, 4)

    def test_compact_leaves_a_file_with_nothing_to_drop(self):
        p = self.dir / "limits.jsonl"
        p.write_text(jl({"ts": time.time(), "seven_day": {"pct": 2}}))
        before = p.stat().st_mtime_ns
        self.assertFalse(limits.compact(p, min_bytes=1))
        self.assertEqual(p.stat().st_mtime_ns, before)

    def test_compact(self):
        p = self.dir / "limits.jsonl"
        now = time.time()
        p.write_text(jl({"ts": now - 10 * 86400, "seven_day": {"pct": 1}}, "junk",
                        {"ts": now - 60, "seven_day": {"pct": 2}}))
        self.assertFalse(limits.compact(p, min_bytes=1 << 20))
        self.assertTrue(limits.compact(p, min_bytes=1))
        self.assertEqual([json.loads(ln)["seven_day"]["pct"] for ln in p.read_text().splitlines()], [2])

    def test_old_observations_are_dropped_from_memory(self):
        now = time.time()
        lg = self.log([{"ts": now - 9 * 86400, "seven_day": {"pct": 1}}, {"ts": now, "seven_day": {"pct": 2}}])
        self.assertEqual([o.pct for o in lg.obs["seven_day"]], [2])


class Procs(unittest.TestCase):
    def test_mcp_classification(self):
        yes = ["npm exec @scope/mcp", "node /Users/x/.npm/_npx/1/node_modules/.bin/mcp", "uvx mcp-server-fetch",
               "python3 -m mcp_server_git", "/usr/local/bin/github-mcp-server stdio", "node /x/mcp/index.js",
               "npx -y @modelcontextprotocol/server-filesystem /tmp", "python3.12 /srv/mcp/run.py"]
        yes.append("claude mcp serve")
        no = ["claude --resume", "grep -r mcp .", "git commit -m 'fix mcp'", "tmcp-run", "vim mcp.md", "rg mcp", "node server.js"]
        for a in yes:
            self.assertTrue(procs.mcp_argv(a.split()), a)
        for a in no:
            self.assertFalse(procs.mcp_argv(a.split()), a)

    def proc(self, comm, args):
        return procs.Proc(1, 0, 10, 0.0, 1000, comm, args)

    def test_shell_wrappers(self):
        self.assertEqual(self.proc("/bin/zsh", "/bin/zsh -c source /x.sh && eval 'grep mcp .'").kind, "shell")
        self.assertEqual(self.proc("/bin/sh", "sh -c npx -y mcp-server-x").kind, "mcp")
        self.assertEqual(self.proc("caffeinate", "caffeinate -i").kind, "keep-awake")

    def test_truncated_comm(self):
        args = ("/Users/me/Library/Application Support/Claude/claude-code/2.1/x/claude.app/Contents/MacOS/claude "
                "--output-format stream-json")
        p = self.proc("/Users/me/Librar", args)
        self.assertTrue(p.exe.endswith("/MacOS/claude"))
        self.assertTrue(procs.is_claude_cli(p))
        wrapper = self.proc("/Applications/Cl", "/Applications/Claude.app/Contents/Helpers/disclaimer --pgroup -- " + args)
        self.assertFalse(procs.is_claude_cli(wrapper))
        self.assertEqual(self.proc("/opt/homebrew/bi", "/opt/homebrew/bin/zsh -l").kind, "shell")

    def test_linux_comm_with_spaces(self):
        lines = ["  67336   67140       00:00  0.0  2060 Web Content     sh -c printf x; sleep 30",
                 "    123       1    01:02:03  0.0  2452 tmux: server    tmux new -s work",
                 "      2       1  4-14:22:19  0.0  2528 init-systemd(Ub /init",
                 "      1       0  4-14:22:20  0.0  6528 systemd         /usr/lib/systemd/systemd --system",
                 "    317     294  4-14:22:18  0.0  5784 uv              /home/joe/.local/bin/uv run -q site/app.py"]
        got = [procs.split_line(line, linux=True)[5:] for line in lines]
        self.assertEqual(got, [["Web Content", "sh -c printf x; sleep 30"], ["tmux: server", "tmux new -s work"],
                               ["init-systemd(Ub", "/init"], ["systemd", "/usr/lib/systemd/systemd --system"],
                               ["uv", "/home/joe/.local/bin/uv run -q site/app.py"]])
        # a line without the padded column (no args, or an overlong name) splits as before
        for line in ("   10     2  00:01  0.0  0 kthreadd", "   11 2 00:01 0.0 0 kworker/u16:2-events_unbound [kworker]"):
            self.assertEqual(procs.split_line(line, linux=True), line.split(None, 6))

    def test_macos_lines_split_as_before(self):
        for line in ("  807     1 87-16:03:14   0.0   1888 /bin/bash        /bin/bash /Library/Application Support/x.sh",
                  "13936 82678    01:51:08   0.0  34464 /Applications/Cl /Applications/Claude.app/Contents/MacOS/Claude",
                  "    1     0 87-16:04:20   0.3  24080 /sbin/launchd    /sbin/launchd"):
            self.assertEqual(procs.split_line(line), line.split(None, 6))

    def test_parse_etime(self):
        self.assertEqual(procs.parse_etime("1-02:03:04"), 86400 + 7384)
        self.assertEqual(procs.parse_etime("05:06"), 306)
        self.assertEqual(procs.parse_etime("12"), 12)


class StoreTests(unittest.TestCase):
    """Store reads paths at import, so these run in a subprocess with their own CLAUDE_CONFIG_DIR."""

    def run_py(self, home, code):
        r = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), capture_output=True, text=True,
                           env=dict(os.environ, CLAUDE_CONFIG_DIR=str(home)), timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        return r.stdout.strip()

    def test_bad_registry_and_transcripts_do_not_crash(self):
        with tempfile.TemporaryDirectory() as home:
            home = Path(home)
            (home / "sessions").mkdir()
            (home / "sessions" / "1.json").write_text("[1, 2]")
            (home / "sessions" / "2.json").write_text('{"sessionId": ["x"], "pid": %d}' % os.getpid())
            proj = home / "projects" / "p"
            proj.mkdir(parents=True)
            (proj / "s1.jsonl").write_text(jl(42, {"type": "assistant", "message": "x"}, asst("ok")))
            (proj / "s2.jsonl").mkdir()          # a directory where a file is expected
            (home / "claudemon").mkdir()
            (home / "claudemon" / "limits.jsonl").write_text(jl({"ts": "bad"}, {"seven_day": 5}, 7))
            out = self.run_py(home, "from claudemon.sources import store\ns = store.Store()\ns.index()\ns.refresh()\n"
                                    "print(s.indexed, len(s.sessions), 'ok' in s.sessions['s1'].t.calls)")
            self.assertEqual(out, "True 2 True")

    def test_pid_reuse_is_not_a_live_session(self):
        with tempfile.TemporaryDirectory() as home:
            home = Path(home)
            (home / "sessions").mkdir()
            month_ago = time.strftime("%a %b %d %H:%M:%S %Y", time.gmtime(time.time() - 30 * 86400))
            (home / "sessions" / "a.json").write_text(json.dumps({"sessionId": "a", "pid": os.getpid(), "procStart": month_ago}))
            code = ("import os, time\nfrom claudemon.sources import store\nfrom claudemon.sources import procs\ns = store.Store()\ns.refresh()\n"
                    "me = s.procs.get(os.getpid())\n"
                    "real = time.strftime('%a %b %d %H:%M:%S %Y', time.gmtime(time.time() - me.elapsed))\n"
                    "print(sorted(x for x in s.sessions if s.sessions[x].live), s.is_live({'pid': os.getpid()}),\n"
                    "      s.is_live({'pid': os.getpid(), 'procStart': real, 'startedAt': 1}))")
            out = self.run_py(home, code)
            # a stale startedAt (a session started later in the same process, e.g. after /clear) does not matter
            self.assertEqual(out, "[] True True")

    def test_agent_finished(self):
        with tempfile.TemporaryDirectory() as home:
            p = Path(home) / "agent-x.jsonl"
            old = "2026-01-01T00:00:00Z"
            p.write_text(jl(asst("m", ts=old, tools=[("t1", "Bash", {"command": "sleep 9999"})])))
            os.utime(p, (time.time() - 1200, time.time() - 1200))
            code = ("import json, time\nfrom claudemon.sources import store\n"
                    "a = store.Agent(%r)\na.refresh()\na.t.last_ts = time.time() - 1200\n"
                    "busy = a.finished\na.t.pending_tools.clear()\nidle = a.finished\n"
                    "a.t.pending_tools['t1'] = ('Bash', 0, '')\na.meta = {'stoppedByUser': True}\n"
                    "print(busy, idle, a.finished)" % str(p))
            self.assertEqual(self.run_py(home, code), "False True True")

    def test_readers_survive_concurrent_inserts(self):
        with tempfile.TemporaryDirectory() as home:
            code = (
                "import threading\nfrom claudemon.sources import store\nfrom claudemon.sources import transcript\n"
                "s = store.Session('x', '/nonexistent')\n"
                "stop = False\n"
                "def writer():\n"
                "    i = 0\n"
                "    while not stop:\n"
                "        i += 1\n"
                "        s.t.calls['m%d' % i] = transcript.Call(1e12, transcript.Usage(), 'm', '')\n"
                "        s.t.calls.pop('m%d' % (i - 300), None)\n"
                "        s.agents['a%d' % i] = store.Agent('/nonexistent/agent-a.jsonl')\n"
                "        s.agents.pop('a%d' % (i - 50), None)\n"
                "th = threading.Thread(target=writer); th.start()\n"
                "import time\nend = time.time() + 2\n"
                "while time.time() < end:\n"
                "    list(s.all_calls()); s.loops(); s.t.totals()\n"
                "stop = True; th.join(); print('ok')\n")
            self.assertEqual(self.run_py(home, code), "ok")


class TuiInput(unittest.TestCase):
    """Drives tui.App with the fake curses window from headless.py."""

    def run_py(self, code, home):
        r = subprocess.run([sys.executable, "-c", "import sys; sys.argv=['grid']\nfrom claudemon.ui import headless as g\ng.install()\n" + code],
                           cwd=str(ROOT), capture_output=True, text=True, timeout=60,
                           env=dict(os.environ, CLAUDE_CONFIG_DIR=home, CLAUDEMON_DEMO="1", TERM_PROGRAM="none"))
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        return r.stdout.strip()

    def test_bad_config_values_and_keys(self):
        with tempfile.TemporaryDirectory() as home:
            code = (
                "from claudemon.ui import app as tui\nfrom claudemon.sources import store\n"
                "st = store.Store(); st.indexed = True\n"
                "for cfg in ({'page': 99, 'interval': 7, 'span': -1, 'theme': ['x'], 'graph': 5, 'full_size': 'x'},\n"
                "            {'page': 'x', 'page_name': 'Tasks'}, {'page': True}):\n"
                "    app = tui.App(g.FakeWin(40, 120), st, dict(cfg, tap_prompt_seen=True))\n"
                "    app.tick(force=True); app.draw()\n"
                "    print(app.pages[app.page][0], app.interval, app.span)\n"
                "for k in ('²', '٣', '0', '9', '1'):\n"
                "    app.on_key(k)\n"
                "    print(repr(k), app.page)\n"
                "app.mini = True\n"
                "for k in ('²', '5'):\n"
                "    app.on_key(k)\n"
                "print(app.page, app.mini)\n")
            out = self.run_py(code, home).splitlines()
            self.assertEqual(out[:3], ["Token burn 2 900", "Tasks 2 900", "Token burn 2 900"])
            self.assertEqual(out[3:8], ["'²' 0", "'٣' 0", "'0' 9", "'9' 8", "'1' 0"])
            self.assertEqual(out[8], "4 False")

    def test_manual_and_help_leave_mini(self):
        with tempfile.TemporaryDirectory() as home:
            code = (
                "from claudemon.ui import app as tui\nfrom claudemon.sources import store\n"
                "st = store.Store(); st.indexed = True\n"
                "for k in ('m', '?'):\n"
                "    app = tui.App(g.FakeWin(12, 74), st, {'mini': True, 'tap_prompt_seen': True})\n"
                "    app.tick(force=True); app.on_key(k); app.draw()\n"
                "    print(app.mini, app.modal)\n")
            self.assertEqual(self.run_py(code, home).splitlines(), ["False manual", "False help"])

    def test_install_prompt_ignores_keys_while_the_window_is_too_small(self):
        with tempfile.TemporaryDirectory() as home:
            code = (
                "from claudemon.ui import app as tui\nfrom claudemon.sources import store\nfrom claudemon.tap import installer as install\n"
                "st = store.Store(); st.indexed = True\n"
                "app = tui.App(g.FakeWin(12, 60), st, {'tap_prompt_seen': True})\n"
                "app.tick(force=True); app.modal = 'prompt'; app.draw()\n"
                "print(app.on_key('\\n'), app.modal, install.installed())\n"
                "print(app.on_key('q'))\n")
            self.assertEqual(self.run_py(code, home).splitlines(), ["True prompt False", "False"])

    def test_alt_key_is_not_a_quit_and_esc_is(self):
        with tempfile.TemporaryDirectory() as home:
            code = (
                "import curses\nfrom claudemon.ui import app as tui\nfrom claudemon.sources import store\n"
                "class W(g.FakeWin):\n"
                "    keys = []\n"
                "    def nodelay(self, f): pass\n"
                "    def timeout(self, t): pass\n"
                "    def get_wch(self):\n"
                "        if not self.keys: raise curses.error()\n"
                "        return self.keys.pop(0)\n"
                "curses.napms = lambda ms: None\n"
                "app = tui.App(W(40, 120), store.Store(), {'tap_prompt_seen': True})\n"
                "app.win.keys = ['x']\nprint(app.escape_sequence(), app.win.keys)\n"
                "app.win.keys = []\nprint(app.escape_sequence())\n")
            self.assertEqual(self.run_py(code, home).splitlines(), ["True []", "False"])

    def test_first_launch_in_mini_does_not_raise_the_install_prompt(self):
        with tempfile.TemporaryDirectory() as home:
            code = (
                "import curses\nfrom claudemon.ui import app as tui\nfrom claudemon.sources import store\n"
                "class W(g.FakeWin):\n"
                "    keys = ['\\n', 'q']\n"
                "    def nodelay(self, f): pass\n"
                "    def timeout(self, t): pass\n"
                "    def get_wch(self):\n"
                "        if not self.keys: raise curses.error()\n"
                "        return self.keys.pop(0)\n"
                "curses.curs_set = lambda n: None\n"
                "st = store.Store(); st.indexed = True\n"
                "app = tui.App(W(12, 74), st, {'mini': True})\n"
                "app.run()\n"
                "import os\nfrom claudemon.core import paths\n"
                "print(app.modal, os.path.exists(paths.SETTINGS_FILE))\n")
            self.assertEqual(self.run_py(code, home), "None False")

    def test_keyboard_interrupt_saves_and_exits_cleanly(self):
        with tempfile.TemporaryDirectory() as home:
            code = (
                "import curses, json\nfrom claudemon.ui import app as tui\nfrom claudemon.sources import store\nfrom claudemon.core import config\n"
                "class W(g.FakeWin):\n"
                "    def nodelay(self, f): pass\n"
                "    def timeout(self, t): pass\n"
                "    def get_wch(self): raise KeyboardInterrupt\n"
                "curses.curs_set = lambda n: None\n"
                "st = store.Store(); st.indexed = True\n"
                "app = tui.App(W(40, 120), st, {'tap_prompt_seen': True, 'theme': 'dracula'})\n"
                "app.run()\n"
                "print(json.load(open(config.CONFIG_FILE))['theme'])\n")
            self.assertEqual(self.run_py(code, home), "dracula")


class ModelNames(unittest.TestCase):
    def test_short_model(self):
        from claudemon.sources import store
        for raw, want in (("claude-opus-5-5", "Opus 5.5"), ("claude-opus-4-7[1m]", "Opus 4.7"),
                          ("claude-sonnet-4-5@20250929", "Sonnet 4.5"), ("us.anthropic.claude-haiku-4-5-20251001-v1:0", "Haiku 4.5"),
                          ("claude-3-5-sonnet-20241022", "Sonnet 3.5"), ("claude-opus-4-20250514", "Opus 4"),
                          ("claude-fable-5-2", "Fable 5.2"), ("", "?"), (None, "?"), ("gpt-x", "gpt-x")):
            self.assertEqual(store.short_model(raw), want, raw)


class SettingsPage(unittest.TestCase):
    def test_a_malformed_settings_json_is_explained_not_a_page_error(self):
        with tempfile.TemporaryDirectory() as home:
            Path(home, "settings.json").write_text('{"hooks": {"Notification": {}}}')
            r = subprocess.run([sys.executable, "tools/grid.py", "150x46", "claude", "settings"], cwd=str(ROOT),
                               capture_output=True, text=True, timeout=60,
                               env=dict(os.environ, CLAUDE_CONFIG_DIR=home, CLAUDEMON_DEMO="1"))
            self.assertEqual(r.returncode, 0, r.stderr[-500:])
            text = "".join(c[0] for row in json.loads(r.stdout)["cells"] for c in row)
            self.assertNotIn("page error", text)
            self.assertIn("unexpected shape", text)


class LaunchSize(unittest.TestCase):
    def test_size_is_validated(self):
        from claudemon import window as launch
        self.assertEqual(launch.parse_size("150x46"), ("150", "46"))
        for bad in ('1" & (do shell script "x") & "x5', "150", "x46", "150x46 ", ""):
            self.assertIsNone(launch.parse_size(bad), bad)


class Headless(unittest.TestCase):
    def test_importing_headless_leaves_curses_alone_until_install(self):
        code = ("import curses\nfrom claudemon.ui import headless\n"
                "assert not hasattr(curses, 'COLORS') or curses.COLORS != 256\n"
                "headless.install()\n"
                "assert curses.COLORS == 256 and curses.color_pair(3) == 3 << 24\n"
                "print('ok')\n")
        r = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), capture_output=True, text=True, timeout=30)
        self.assertEqual(r.stdout.strip(), "ok", r.stderr[-500:])


class Fmt(unittest.TestCase):
    def test_formatters_and_the_command_modules_do_not_import_the_tui(self):
        from claudemon.core import fmt
        self.assertEqual(fmt.ftok(1234), "1.23k")
        self.assertEqual(fmt.fdur(3700), "1h01m")
        self.assertEqual(fmt.fpct(.5), "50%")
        self.assertEqual(fmt.fpct(None), "—")
        r = subprocess.run([sys.executable, "-c", "import sys; from claudemon import commands; from claudemon.core import fmt; from claudemon.sources import store; assert 'claudemon.ui.app' not in sys.modules"],
                           cwd=str(ROOT), capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr[-500:])


if __name__ == "__main__":
    unittest.main()
