"""Shared helpers for the headless UI tests: a demo home, and a subprocess that drives the App.

Not a test module (neither runner collects it). Import it the same way from every test file, so
both `python3 -m unittest` and pytest see one copy:

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import support  # noqa: E402

The App always runs in a subprocess: headless.install() patches the curses module for the whole
process, and paths are read from CLAUDE_CONFIG_DIR at import, so each run gets a fresh interpreter
whose CLAUDE_CONFIG_DIR and HOME point at a temporary folder, never the real ~/.claude.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Run first in every ui() subprocess. Names it defines for the test's code:
#   g      claudemon.ui.headless (g.FakeWin(rows, cols))
#   tui    claudemon.ui.app (tui.App, tui.PAGES)
#   store  claudemon.sources.store
#   make_app(rows=40, cols=120, **cfg)  an App on a FakeWin over a fully indexed Store, ticked once;
#                                       cfg defaults to tap_prompt_seen=True
#   text(app)                           the screen as one string, rows joined by newlines
#   key(app, *keys)                     send keys (str, or curses.KEY_* ints) and redraw after each
PRELUDE = """\
import sys; sys.argv = ['grid']
from claudemon.ui import headless as g
g.install()
from claudemon.ui import app as tui
from claudemon.sources import store

def make_app(rows=40, cols=120, **cfg):
    st = store.Store()
    st.index()
    app = tui.App(g.FakeWin(rows, cols), st, dict({'tap_prompt_seen': True}, **cfg))
    app.tick(force=True)
    app.draw()
    return app

def text(app):
    return "\\n".join("".join(c[0] for c in row) for row in app.win.g)

def key(app, *keys):
    out = None
    for k in keys:
        out = app.on_key(k)
        app.draw()
    return out
"""


def ui(code, home, demo=True, env=None, timeout=60):
    """Run PRELUDE + code in a fresh Python with CLAUDE_CONFIG_DIR and HOME set to home; return stdout.

    Fails the calling test (AssertionError with the stderr tail) when the subprocess exits non-zero.
    demo=True sets CLAUDEMON_DEMO=1, which hides the real process table.
    """
    e = dict(os.environ, CLAUDE_CONFIG_DIR=str(home), HOME=str(home), TERM_PROGRAM="none",
             PYTHONPATH=str(ROOT / "src"), PYTHONDONTWRITEBYTECODE="1")
    if demo:
        e["CLAUDEMON_DEMO"] = "1"
    e.update(env or {})
    r = subprocess.run([sys.executable, "-c", PRELUDE + code], cwd=str(ROOT), env=e,
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise AssertionError("ui() subprocess failed (%d):\n%s" % (r.returncode, r.stderr[-3000:]))
    return r.stdout


class DemoHome:
    """A temporary CLAUDE_CONFIG_DIR filled by tools/make_demo.py, its sessions registered under a
    live `sleep` helper so they count as live. Use as a context manager, or start()/stop() from
    setUpClass/tearDownClass; .path is the folder.

        with support.DemoHome() as home:
            out = support.ui("app = make_app()\\nprint(text(app))", home)
    """

    def __init__(self, no_tap=False):
        self.no_tap = no_tap
        self.path = None
        self._tmp = self._live = None

    def start(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = self._tmp.name
        self._live = subprocess.Popen(["sleep", "600"])
        args = [sys.executable, str(ROOT / "tools" / "make_demo.py"), self.path, "--pid", str(self._live.pid)]
        if self.no_tap:
            args.append("--no-tap")
        r = subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True, timeout=60,
                           env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        if r.returncode != 0:
            self.stop()
            raise RuntimeError("make_demo failed: " + r.stderr[-1000:])
        return self.path

    def stop(self):
        if self._live:
            self._live.kill()
            self._live.wait()
            self._live = None
        if self._tmp:
            self._tmp.cleanup()
            self._tmp = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
