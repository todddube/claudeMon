"""The parity scenarios. Each takes a Ctx (one side, one fresh scenario folder) and returns
{output name: JSON-able value}; the harness masks and compares them key by key.

Grouped as the plan's table: CLI, TUI headless, TUI pty, installer, --window, tap, state.
Theme names, page names and manual topic ids are frozen strings, so they are listed here.
"""

import collections
import json
import shlex
import sys

Scenario = collections.namedtuple("Scenario", "name fn")
ALL = []


def scenario(name):
    def add(fn):
        ALL.append(Scenario(name, fn))
        return fn
    return add


THEMES = ["claude", "btop", "dracula", "nord", "gruvbox", "matrix", "amber", "c64", "synthwave", "mono"]
STYLES = ["blocks", "braille", "dots", "line", "ascii"]
PAGES = ["token", "tasks", "context", "prompt cache", "traffic", "models", "session", "weekly", "projects",
         "inspect", "inspect:web shop", "settings", "mini", "manual", "manual:tap", "manual:s", "prompt"]
GO_ODD = ["0", "5", "11", "99", "s", "w", "nope", "manual:zzz", "tasks:shop", "inspect:nobody"]
CHART_PAGES = ["token", "tasks", "context", "prompt cache", "traffic", "models", "session", "weekly", "projects",
               "inspect:web shop", "mini"]
SIZES = ["160x50", "70x16", "69x16", "70x15", "60x20", "200x60"]
MINI_SIZES = ["74x14", "74x6", "50x8", "40x6", "39x5", "120x36"]

STATUS_IN = json.dumps({"session_id": "parity-sid-1", "model": {"id": "claude-opus-5-5", "display_name": "Opus"},
                        "context_window": {"context_window_size": 1000000},
                        "rate_limits": {"five_hour": {"used_percentage": 42.5, "resets_at": 1794240000},
                                        "seven_day": {"used_percentage": 12, "resets_at": "2026-11-12T00:00:00Z"}}})
HOOK_IN = json.dumps({"session_id": "parity-sid-1", "hook_event_name": "Notification",
                      "message": "Claude needs your permission to use Bash", "notification_type": "permission_prompt"})


def grids(ctx, specs, **envkw):
    jobs = [dict(kind="grid", **s) for s in specs]
    res = ctx.driver(jobs, **envkw)
    return {"%s %s %s %s%s" % (s["page"], s.get("size", "120x36"), s.get("theme", "-"), s.get("style", "-"),
                               " ascii" if s.get("ascii") else ""): r for s, r in zip(specs, res)}


# ── CLI ──────────────────────────────────────────────────────────────────────
CLI_CASES = {
    "help": ["--help"], "h": ["-h"], "version": ["--version"], "V": ["-V"],
    "bad command": ["bogus"], "bad theme": ["--theme", "nope"], "bad interval": ["--interval", "3"],
    "bad size": ["--size", "150"], "bad size quote": ["--size", '1" & x'], "two commands": ["install", "snapshot"],
    "no tty": [], "no tty page": ["-p", "tasks"], "no tty mini": ["--mini"], "no tty ascii": ["--ascii", "-t", "nord"],
    "run no tty": ["run"], "bad hours": ["loops", "--hours", "x"],
}


@scenario("cli-flags")
def cli_flags(ctx):
    ctx.fixture("empty")
    return {name: ctx.cli(*argv) for name, argv in CLI_CASES.items()}


def snapshot_and_loops(ctx, **envkw):
    return {"snapshot": ctx.cli("snapshot", **envkw), "loops": ctx.cli("loops", **envkw),
            "loops 1h": ctx.cli("loops", "--hours", "1", **envkw),
            "loops 200h": ctx.cli("loops", "--hours", "200", **envkw), "state": ctx.state()}


@scenario("cli-demo")
def cli_demo(ctx):
    ctx.fixture("demo")
    return snapshot_and_loops(ctx)


@scenario("cli-notap")
def cli_notap(ctx):
    ctx.fixture("notap")
    return snapshot_and_loops(ctx)


@scenario("cli-empty")
def cli_empty(ctx):
    ctx.fixture("empty")
    return snapshot_and_loops(ctx)


@scenario("cli-missing-home")
def cli_missing_home(ctx):
    ctx.home = ctx.home + "-missing"
    return snapshot_and_loops(ctx)


@scenario("cli-spaces")
def cli_spaces(ctx):
    ctx.fixture("demo", home_name="claude home with spaces")
    return snapshot_and_loops(ctx)


@scenario("cli-malformed-config")
def cli_malformed(ctx):
    ctx.fixture("demo")
    ctx.write("claudemon/config.json", "{bad")
    out = snapshot_and_loops(ctx)
    ctx.write("claudemon/config.json", "[1, 2]")
    out["snapshot list config"] = ctx.cli("snapshot")
    return out


# a process table in this platform's ps format, for the non-demo home
def ps_lines(pid):
    rows = [  # pid, ppid, etime, cpu, rss, exe path, args
        (pid, 1, "01:02:03", 12.5, 412345, "/Users/demo/.local/bin/claude", "/Users/demo/.local/bin/claude --resume"),
        (70001, pid, "01:01:00", 0.3, 81234, "/usr/local/bin/node",
         "node /Users/demo/.npm/_npx/9f/node_modules/.bin/mcp-server-github --stdio"),
        (70002, pid, "00:42", 0.0, 2345, "/bin/zsh",
         "/bin/zsh -c source /Users/demo/.claude/shell-snapshots/snapshot-zsh-1.sh && eval 'npm test' < /dev/null"),
        (70003, 70002, "00:41", 87.0, 123456, "/usr/local/bin/node", "node /Users/demo/work/shop/node_modules/.bin/jest"),
        (70004, pid, "1-02:03:04", 0.0, 900, "/usr/bin/caffeinate", "/usr/bin/caffeinate -i -w %d" % pid),
        (70005, 70001, "01:00:59", 0.1, 5000, "/opt/homebrew/bin/uvx", "uvx mcp-server-fetch"),
        (70100, 1, "10:00", 1.0, 200000, "/Users/demo/.local/bin/claude", "claude --print hello"),
        (70200, 1, "3-00:00:00", 2.0, 300000, "/Applications/Claude.app/Contents/MacOS/Claude",
         "/Applications/Claude.app/Contents/MacOS/Claude"),
        (70201, 70200, "3-00:00:00", 4.5, 150000, "/Applications/Claude.app/Contents/Frameworks/Claude Helper.app/"
         "Contents/MacOS/Claude Helper", "/Applications/Claude.app/Contents/Frameworks/Claude Helper.app/Contents/"
         "MacOS/Claude Helper --type=renderer"),
        (70300, 1, "00:01", 0.0, 100, "/bin/sleep", "sleep 5"),
    ]
    out = []
    for p, pp, et, cpu, rss, exe, args in rows:
        if sys.platform.startswith("linux"):
            comm = exe.rsplit("/", 1)[-1][:15]          # procps: the bare name, cut at 15, padded
            out.append("%7d %7d %11s %4.1f %6d %-15s %s" % (p, pp, et, cpu, rss, comm, args))
        else:
            comm = exe[:16]                             # BSD ps: the path, cut at 16 when not last
            out.append("%5d %5d %11s %5.1f %6d %-16s %s" % (p, pp, et, cpu, rss, comm, args))
    return out


@scenario("cli-fakeps")
def cli_fakeps(ctx):
    ctx.fixture("demo")
    return snapshot_and_loops(ctx, demo=False, path=ctx.fake_ps(ps_lines(ctx.pid)))


# ── TUI headless: page grids ─────────────────────────────────────────────────
@scenario("grid-pages")
def grid_pages(ctx):
    ctx.fixture("demo")
    specs = [dict(page=p) for p in PAGES + GO_ODD] + [dict(page=p, ascii=True) for p in PAGES]
    return grids(ctx, specs)


@scenario("grid-sizes")
def grid_sizes(ctx):
    ctx.fixture("demo")
    specs = [dict(page=p, size=s) for s in SIZES for p in PAGES]
    specs += [dict(page="mini", size=s) for s in MINI_SIZES] + [dict(page="mini", size=s, ascii=True) for s in MINI_SIZES]
    return grids(ctx, specs)


@scenario("grid-themes")
def grid_themes(ctx):
    ctx.fixture("demo")
    specs = [dict(page=p, theme=t) for t in THEMES + ["nope"] for p in ("token", "settings", "mini", "session", "prompt")]
    return grids(ctx, specs)


@scenario("grid-styles")
def grid_styles(ctx):
    ctx.fixture("demo")
    specs = [dict(page=p, style=s) for s in STYLES + ["nope"] for p in CHART_PAGES]
    specs += [dict(page=p, style="braille", ascii=True) for p in ("token", "traffic")]
    return grids(ctx, specs)


@scenario("grid-prefs")
def grid_prefs(ctx):
    ctx.fixture("demo")
    specs = [dict(page=p, cfg=dict(tap_prompt_seen=True, span=i, interval=i)) for i in range(-1, 6)
             for p in ("token", "prompt cache", "projects")]
    specs += [dict(page="token", cfg=c) for c in (
        {"page": 99, "interval": 7, "span": -1, "theme": ["x"], "graph": 5, "full_size": "x", "tap_prompt_seen": True},
        {"page": "x", "page_name": "Tasks", "tap_prompt_seen": True}, {"page": True, "tap_prompt_seen": True},
        {"braille": True, "tap_prompt_seen": True}, {}, {"mini": True}, {"flash": "hello flash", "tap_prompt_seen": True})]
    return grids(ctx, specs)


@scenario("grid-notap")
def grid_notap(ctx):
    ctx.fixture("notap")
    return grids(ctx, [dict(page=p) for p in PAGES] + [dict(page="mini", size="74x14")])


@scenario("grid-empty")
def grid_empty(ctx):
    ctx.fixture("empty")
    return grids(ctx, [dict(page=p) for p in PAGES] + [dict(page=p, ascii=True) for p in ("token", "mini")])


@scenario("grid-spaces")
def grid_spaces(ctx):
    ctx.fixture("demo", home_name="claude home with spaces")
    return grids(ctx, [dict(page=p) for p in ("token", "tasks", "inspect:web shop", "settings", "manual:tap", "prompt")])


@scenario("grid-fakeps")
def grid_fakeps(ctx):
    ctx.fixture("demo")
    path = ctx.fake_ps(ps_lines(ctx.pid))
    specs = [dict(page=p, size=s) for p in ("tasks", "token", "inspect", "mini", "settings") for s in ("120x36", "160x50")]
    return grids(ctx, specs, demo=False, path=path)


@scenario("grid-settings-shapes")
def grid_settings_shapes(ctx):
    ctx.fixture("demo")
    out = {}
    for i, text in enumerate(['{"hooks": {"Notification": {}}}', "{bad", "[]", '{"statusLine": "x"}',
                              '{"statusLine": {"type": "command", "command": "echo hi"}}']):
        ctx.write("settings.json", text)
        out["shape %d" % i] = grids(ctx, [dict(page="settings", size="150x46"), dict(page="token")])
    return out


# ── TUI headless: key scripts ────────────────────────────────────────────────
NAV = ["l", "l", "l", "h", "\t", "KEY_BTAB", "KEY_RIGHT", "KEY_LEFT", "2", "j", "j", "k", "KEY_DOWN", "KEY_UP", "\n",
       "s", "KEY_DOWN", "KEY_DOWN", "KEY_UP", "\n", "j", "1", "j", "k", "\n", "3", "KEY_ENTER", "4", "\r",
       "g", "g", "G", "u", "u", "t", "t", "b", "b", "b", "b", "b", "o", "o", "e", "a", "a", "r", "?", "x",
       "m", "j", "l", "KEY_NPAGE", " ", "KEY_PPAGE", "g", "k", "h", "\t", "KEY_BTAB", "x", "q", "6", "M", "?", "\x1b",
       "0", "9", "8", "7", "6", "5", "²", "٣", "KEY_F1", "\x00", "w", "s", "U", "x", "I", "\x1b"]
MINI = ["j", "j", "k", "KEY_DOWN", "KEY_UP", "t", "b", "a", "a", "r", "x", "z", "z", "3", "z", "s", "z", "\n", "z",
        "m", "q", "z", "?", "x", "z", "²", "٣", "0", "z", "o", "e", "g", "u", "\x1b"]


def keys(ctx, specs, **envkw):
    jobs = [dict(kind="keys", **s) for s in specs]
    return dict(zip([s.get("name") or "keys" for s in specs], ctx.driver(jobs, **envkw)))


@scenario("keys-full")
def keys_full(ctx):
    ctx.fixture("demo")
    specs = [dict(name="nav", keys=NAV), dict(name="nav ascii small", keys=NAV[:40], size="70x16", ascii=True)]
    specs += [dict(name="quit %r" % k, keys=[k]) for k in ("q", "Q", "\x1b")]
    specs += [dict(name="go %s" % p, go=p, keys=["j", "\n", "j", "KEY_DOWN", "\n", "m", "m", "\x1b"])
              for p in ("tasks", "settings", "inspect", "projects", "manual:tap", "prompt")]
    specs += [dict(name="bad cfg %d" % i, cfg=c, keys=["²", "٣", "0", "9", "1"]) for i, c in enumerate((
        {"page": 99, "interval": 7, "span": -1, "theme": ["x"], "graph": 5, "full_size": "x", "tap_prompt_seen": True},
        {"page": "x", "page_name": "Tasks", "tap_prompt_seen": True}, {"page": True, "tap_prompt_seen": True}))]
    return keys(ctx, specs)


@scenario("keys-mini")
def keys_mini(ctx):
    ctx.fixture("demo")
    cfg = {"mini": True, "tap_prompt_seen": True}
    specs = [dict(name="mini", cfg=cfg, size="74x14", keys=MINI)]
    specs += [dict(name="mini %r" % k, cfg=cfg, size="74x12", keys=[k, "x", "z"]) for k in ("m", "M", "?", "\n", "s", "7")]
    specs += [dict(name="mini small", cfg=cfg, size="50x8", keys=["j", "z", "z"])]
    return keys(ctx, specs)


@scenario("keys-install")
def keys_install(ctx):
    ctx.fixture("notap")
    out = keys(ctx, [dict(name="install", keys=["I", "x", "I", "I", "I", "s", "U", "x", "U", "U", "U", "m", "I", "I",
                                                "q", "z", "I", "I", "z", "s", "U", "U"])])
    out["state"] = ctx.state()
    return out


@scenario("keys-mini-install")
def keys_mini_install(ctx):
    ctx.fixture("notap")
    out = keys(ctx, [dict(name="mini install", cfg={"mini": True, "tap_prompt_seen": True}, size="74x14",
                          keys=["I", "I", "I", "x"])])
    out["state"] = ctx.state()
    return out


@scenario("keys-prompt")
def keys_prompt(ctx):
    ctx.fixture("notap")
    specs = [dict(name="too small", size="60x12", go="prompt", keys=["\n", "i", "I", "x", "q"]),
             dict(name="too small esc", size="69x40", go="prompt", keys=["\x1b"]),
             dict(name="skip", go="prompt", keys=["x", "q"]),
             dict(name="later", go="prompt", keys=["L", "?", "x"])]
    out = keys(ctx, specs)
    out["state after skip"] = ctx.state()
    out.update(keys(ctx, [dict(name="install", go="prompt", keys=["i"])]))
    out["state after install"] = ctx.state()
    return out


@scenario("keys-prompt-enter")
def keys_prompt_enter(ctx):
    ctx.fixture("notap")
    out = keys(ctx, [dict(name="enter", go="prompt", keys=["\n", "I"])])
    out["state"] = ctx.state()
    return out


# ── installer ────────────────────────────────────────────────────────────────
def steps(ctx, ops):
    out = []
    for op in ops:
        if op == "repair":
            r = ctx.driver([dict(kind="repair")])[0]
        else:
            r = ctx.cli(op)
        out.append({"op": op, "result": r, "state": ctx.state()})
    return out


@scenario("install-fresh")
def install_fresh(ctx):
    ctx.fixture("empty")
    return {"steps": steps(ctx, ["uninstall", "install", "install", "repair", "uninstall", "uninstall", "repair"])}


@scenario("install-existing")
def install_existing(ctx):
    ctx.fixture("empty")
    ctx.write("settings.json", json.dumps({
        "model": "opus", "env": {"SECRET": "x"},
        "statusLine": {"type": "command", "command": "printf '%s' \"a b\"; cat >/dev/null", "padding": 1},
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "true"}]}],
                  "Notification": [{"matcher": "", "hooks": [{"type": "command", "command": "echo theirs"}]}]}},
        indent="\t", ensure_ascii=False) + "\n", mode=0o640)
    out = {"steps": steps(ctx, ["install"])}
    out["statusline run"] = ctx.sh(ctx.statusline(), STATUS_IN)
    out["hook run"] = ctx.sh(ctx.hook(), HOOK_IN)
    out["after tap"] = ctx.state()
    out["more"] = steps(ctx, ["install", "uninstall"])
    return out


@scenario("install-shapes")
def install_shapes(ctx):
    ctx.fixture("empty")
    out = {}
    for i, text in enumerate(["{bad", "[]", '{"statusLine": "x"}', '{"statusLine": {"command": 5}}',
                              '{"hooks": []}', '{"hooks": {"Notification": {}}}', '{"hooks": {"Notification": [1]}}',
                              '{"hooks": {"Notification": [{"hooks": [{"command": 1}]}]}}', "", "null",
                              '{"statusLine": {"type": "command", "command": "echo \\u00e9t\\u00e9"}}']):
        ctx.write("settings.json", text)
        out["shape %d" % i] = steps(ctx, ["install", "uninstall", "repair"])
    return out


@scenario("install-symlink")
def install_symlink(ctx):
    import os
    ctx.fixture("empty")
    real = ctx.write("dotfiles/settings.json", json.dumps({"statusLine": {"type": "command", "command": "echo hi"}},
                                                          indent=4))
    os.symlink(real, os.path.join(ctx.home, "settings.json"))
    out = {"steps": steps(ctx, ["install", "uninstall"])}
    out["is link"] = os.path.islink(os.path.join(ctx.home, "settings.json"))
    return out


@scenario("install-backups")
def install_backups(ctx):
    ctx.fixture("empty")
    ctx.write("settings.json", "{}")
    for _ in range(7):
        ctx.cli("install")
        ctx.cli("uninstall")
    return {"state": ctx.state()}


@scenario("install-vanished-python")
def install_vanished(ctx):
    ctx.fixture("empty")
    ctx.write("settings.json", json.dumps({"statusLine": {"type": "command", "command": "echo hi"}}))
    out = {"install": steps(ctx, ["install"])}
    text = ctx.read("settings.json")
    for py in ctx.side.pythons:
        text = text.replace(shlex.quote(py), "/gone/python3")
    ctx.write("settings.json", text)
    out["vanished"] = steps(ctx, ["repair", "repair"])
    ctx.write("settings.json", text)
    out["vanished install"] = steps(ctx, ["install"])
    return out


def legacy(ctx, marked):
    """settings.json from before PR #1: commands run <checkout>/tap.py directly."""
    import os
    ctx.fixture("empty")
    py, tap = shlex.quote(ctx.side.python), shlex.quote(os.path.join(ctx.root, "tap.py"))
    mark = " # claudemon" if marked else ""
    ctx.write("settings.json", json.dumps({
        "statusLine": {"type": "command", "command": "%s %s statusline -- 'echo legacy'%s" % (py, tap, mark)},
        "hooks": {"Notification": [{"hooks": [{"type": "command", "command": "%s %s hook Notification%s" % (
            py, tap, mark)}]}]}}, indent=2))
    out = {"before": ctx.state(), "legacy statusline run": ctx.sh(ctx.statusline(), STATUS_IN),
           "after legacy run": ctx.state()}
    out["repair"] = steps(ctx, ["repair"])
    out["statusline run"] = ctx.sh(ctx.statusline(), STATUS_IN)
    out["install"] = steps(ctx, ["install", "uninstall"])
    return out


@scenario("install-legacy-marked")
def install_legacy_marked(ctx):
    return legacy(ctx, True)


@scenario("install-legacy-unmarked")
def install_legacy_unmarked(ctx):
    return legacy(ctx, False)


@scenario("install-spaces")
def install_spaces(ctx):
    ctx.fixture("empty", home_name="claude home with spaces")
    ctx.write("settings.json", json.dumps({"statusLine": {"type": "command", "command": "echo 'it''s'"}}))
    out = {"steps": steps(ctx, ["install"])}
    out["statusline run"] = ctx.sh(ctx.statusline(), STATUS_IN)
    out["hook run"] = ctx.sh(ctx.hook(), HOOK_IN)
    out["after"] = steps(ctx, ["uninstall"])
    return out


# ── tap ──────────────────────────────────────────────────────────────────────
@scenario("tap")
def tap(ctx):
    import os
    ctx.fixture("empty")
    src = ctx.side.path(ctx.side.const["TAP_SOURCE"])
    py = shlex.quote(ctx.side.python)
    run = "%s %s" % (py, shlex.quote(src))
    out = {"source sha256": ctx.sha(src)}
    out["statusline cat"] = ctx.sh(run + " statusline -- cat", STATUS_IN)
    out["statusline none"] = ctx.sh(run + " statusline", STATUS_IN)
    out["statusline fails"] = ctx.sh(run + " statusline -- 'echo out; exit 3'", STATUS_IN)
    out["statusline bad json"] = ctx.sh(run + " statusline -- cat", "{not json")
    out["statusline bad sid"] = ctx.sh(run + " statusline -- cat", json.dumps({"session_id": "../../x"}))
    out["statusline marked"] = ctx.sh(run + " statusline -- 'echo hi' # claudemon", STATUS_IN)
    out["hook"] = ctx.sh(run + " hook Notification", HOOK_IN)
    out["hook bad"] = ctx.sh(run + " hook Notification", "[]")
    out["unknown verb"] = ctx.sh(run + " what", "")
    out["state"] = ctx.state()
    ctx.cli("install")
    out["installed sha256"] = ctx.sha(os.path.join(ctx.home, "claudemon", "tap.py"))
    return out


@scenario("tap-demo")
def tap_demo(ctx):
    ctx.fixture("demo")
    ctx.cli("install")
    out = {"statusline": ctx.sh(ctx.statusline(), STATUS_IN), "hook": ctx.sh(ctx.hook(), HOOK_IN)}
    out["state"] = ctx.state()
    return out


# ── --window ─────────────────────────────────────────────────────────────────
WINDOW_FLAGS = [["--window"], ["-w", "--mini"], ["--window", "-t", "dracula", "-i", "5", "-p", "inspect:web shop",
                                                  "--ascii", "--size", "150x46"], ["-w", "--size", "80x24", "-z"]]


def window(ctx, platform, stubs, flags_list, term_env=None, exit_code=0, err=""):
    path, log, env = ctx.stubs(stubs, exit_code, err)
    env.update(term_env or {})
    env["PARITY_PLATFORM"] = platform
    out = []
    for flags in flags_list:
        import os
        if os.path.exists(log):
            os.unlink(log)
        r = ctx.cli(*flags, path=path, extra=env)
        out.append({"flags": flags, "cli": r, "stub": ctx.wait_log(log) if stubs else "(no stubs)"})
    return out


@scenario("window")
def window_all(ctx):
    ctx.fixture("empty")
    mac = ["osascript", "open"]
    out = {
        "terminal": window(ctx, "darwin", mac, WINDOW_FLAGS, {"TERM_PROGRAM": "Apple_Terminal"}),
        "default": window(ctx, "darwin", mac, [["--window"]]),
        "iterm flag": window(ctx, "darwin", mac, WINDOW_FLAGS[:2] + [["-w", "--terminal", "iterm"]],
                             {"TERM_PROGRAM": "Apple_Terminal"}),
        "iterm env": window(ctx, "darwin", mac, [["-w"]], {"TERM_PROGRAM": "iTerm.app"}),
        "terminal env": window(ctx, "darwin", mac, [["-w"]], {"CLAUDEMON_TERMINAL": "iterm", "TERM_PROGRAM": "x"}),
        "ghostty": window(ctx, "darwin", mac, [["-w", "--terminal", "ghostty"], ["-w", "-z"]],
                          {"TERM_PROGRAM": "ghostty"}),
        "ghostty no open": window(ctx, "darwin", ["osascript"], [["-w"]], {"TERM_PROGRAM": "ghostty"}),
        "osascript denied": window(ctx, "darwin", mac, [["-w"]], exit_code=1,
                                   err="execution error: Not authorized to send Apple events to Terminal. (-1743)"),
        "osascript fails": window(ctx, "darwin", mac, [["-w", "--terminal", "iterm"]], exit_code=1),
        "gnome": window(ctx, "linux", ["gnome-terminal", "konsole", "xterm"], WINDOW_FLAGS),
        "konsole": window(ctx, "linux", ["konsole", "xterm"], [["-w", "-z"]]),
        "xterm": window(ctx, "linux", ["xterm"], [["-w", "-t", "nord"]]),
        "no terminal": window(ctx, "linux", [], [["-w"]]),
    }
    return out


# ── TUI in a pty ─────────────────────────────────────────────────────────────
PROMPT = "What installing does"


def pty_case(ctx, args, script, size=(36, 120), **envkw):
    r = ctx.pty(args, script, size=size, **envkw)
    r["config"] = ctx.read("claudemon/config.json")
    r["state"] = ctx.state()
    return r


@scenario("pty-start")
def pty_start(ctx):
    ctx.fixture("demo")
    return {"page": pty_case(ctx, ["-p", "traffic"], [("wait", "claudeMon"), ("key", "q")]),
            "flags": pty_case(ctx, ["-t", "dracula", "-i", "5", "--ascii", "-p", "settings"],
                              [("wait", "Settings"), ("key", "t"), ("key", "q")]),
            "manual": pty_case(ctx, ["-p", "manual:tap"], [("wait", "claudeMon"), ("key", "q"), ("key", "q")]),
            "esc": pty_case(ctx, [], [("wait", "claudeMon"), ("key", "\x1b")]),
            "explicit run": pty_case(ctx, ["run", "-p", "3"], [("wait", "claudeMon"), ("key", "q")])}


@scenario("pty-first-launch")
def pty_first_launch(ctx):
    ctx.fixture("notap")
    ctx.write("claudemon/config.json", "{}")
    out = {"skip": pty_case(ctx, [], [("wait", PROMPT), ("key", "x"), ("key", "q")])}
    out["second launch"] = pty_case(ctx, [], [("wait", "claudeMon"), ("key", "q")])
    return out


@scenario("pty-first-launch-install")
def pty_first_launch_install(ctx):
    ctx.fixture("empty")
    return {"install": pty_case(ctx, [], [("wait", PROMPT), ("key", "i"), ("sleep", 0.5), ("key", "q")]),
            "relaunch": pty_case(ctx, ["-p", "prompt"], [("wait", PROMPT), ("key", "x"), ("key", "q")])}


@scenario("pty-first-launch-small")
def pty_first_launch_small(ctx):
    ctx.fixture("empty")
    return {"small": pty_case(ctx, [], [("wait", "needs at least"), ("key", "\n"), ("key", "i"),
                                       ("size", 36, 120), ("wait", PROMPT), ("key", "x"), ("key", "q")], size=(12, 60))}


@scenario("pty-mini")
def pty_mini(ctx):
    ctx.fixture("demo")
    fresh = {"mini": pty_case(ctx, ["--mini"], [("wait", "claudeMon"), ("key", "z"), ("wait", "Token burn"),
                                                ("key", "z"), ("key", "q")], extra={"CLAUDEMON_RESIZE": "1"})}
    fresh["mini terminal"] = pty_case(ctx, ["-z"], [("wait", "claudeMon"), ("key", "q")],
                                      extra={"TERM_PROGRAM": "Apple_Terminal"})
    fresh["mini tmux"] = pty_case(ctx, ["-z"], [("wait", "claudeMon"), ("key", "q")],
                                  extra={"TERM_PROGRAM": "iTerm.app", "TMUX": "/tmp/x"})
    fresh["saved mini"] = pty_case(ctx, [], [("wait", "claudeMon"), ("key", "q")], extra={"CLAUDEMON_RESIZE": "1"})
    return fresh


@scenario("pty-mini-first-launch")
def pty_mini_first(ctx):
    ctx.fixture("empty")
    return {"mini": pty_case(ctx, ["--mini"], [("wait", "claudeMon"), ("key", "q")])}


@scenario("pty-resize")
def pty_resize(ctx):
    ctx.fixture("demo")
    return {"resize": pty_case(ctx, [], [("wait", "claudeMon"), ("size", 12, 60), ("wait", "needs at least"),
                                         ("size", 40, 130), ("wait", "Settings"), ("key", "q")])}


@scenario("pty-sigterm")
def pty_sigterm(ctx):
    ctx.fixture("demo")
    return {"term": pty_case(ctx, ["-t", "nord", "-p", "models"], [("wait", "claudeMon"), ("key", "g"),
                                                                    ("signal", "SIGTERM")]),
            "hup": pty_case(ctx, ["-t", "amber"], [("wait", "claudeMon"), ("signal", "SIGHUP")])}


@scenario("pty-edge-homes")
def pty_edge(ctx):
    ctx.fixture("demo")
    ctx.write("claudemon/config.json", "{bad")
    out = {"malformed config": pty_case(ctx, [], [("wait", PROMPT), ("key", "x"), ("key", "q")])}
    ctx.write("claudemon/config.json", '{"theme": 5, "page": "x", "interval": 9, "mini": "yes", "full_size": [1, 2]}')
    out["wrong types"] = pty_case(ctx, [], [("wait", "claudeMon"), ("key", "q")])
    return out


@scenario("pty-spaces")
def pty_spaces(ctx):
    ctx.fixture("notap", home_name="claude home with spaces")
    ctx.write("settings.json", json.dumps({"statusLine": {"type": "command", "command": "echo hi"}}))
    ctx.cli("install")
    return {"start": pty_case(ctx, [], [("wait", "claudeMon"), ("key", "q")])}


@scenario("pty-repair")
def pty_repair(ctx):
    """Every TUI start runs the installer's repair: a legacy checkout is re-pointed."""
    import os
    ctx.fixture("demo")
    py, tap = shlex.quote(ctx.side.python), shlex.quote(os.path.join(ctx.root, "tap.py"))
    ctx.write("settings.json", json.dumps({"statusLine": {"type": "command", "command": "%s %s statusline" % (py, tap)}}))
    return {"start": pty_case(ctx, [], [("wait", "claudeMon"), ("key", "q")])}
