"""Open claudeMon in its own terminal window titled "claudeMon"."""

import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from paths import stable_python

ROOT = Path(__file__).resolve().parent


def _command(extra, env=None):
    args = " ".join(shlex.quote(a) for a in extra)
    prefix = ("env " + "".join("%s=%s " % (k, shlex.quote(v)) for k, v in env.items())) if env else ""
    return "printf '\\033]0;claudeMon\\007'; cd %s && exec %s%s %s %s" % (
        shlex.quote(str(ROOT)), prefix, shlex.quote(stable_python()), shlex.quote(str(ROOT / "claudemon.py")), args)


def _osa(script):
    run = subprocess.run(["osascript", "-e", script], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if run.returncode:
        err = run.stderr.strip()
        hint = ""
        if "-1743" in err or "not allowed" in err.lower():
            hint = " (allow your terminal to control Terminal/iTerm in System Settings > Privacy & Security > Automation, or just run claudemon directly)"
        sys.exit("could not open a window: %s%s" % (err.splitlines()[-1] if err else "osascript failed", hint))


def _as_str(s):
    return '"%s"' % s.replace("\\", "\\\\").replace('"', '\\"')


def parse_size(size):
    """'COLSxROWS' -> (cols, rows) as digit strings, or None (the values reach AppleScript)."""
    m = re.fullmatch(r"(\d{2,4})x(\d{1,4})", size or "")
    return (m.group(1), m.group(2)) if m else None


def open_window(terminal=None, extra=(), size="160x50", env=None):
    cmd = _command(list(extra), env)
    cols, rows = parse_size(size) or ("160", "50")
    term = (terminal or os.environ.get("CLAUDEMON_TERMINAL") or os.environ.get("TERM_PROGRAM") or "").lower()
    if sys.platform != "darwin":
        for exe, argv in (("gnome-terminal", ["--title=claudeMon", "--", "sh", "-c", cmd]),
                          ("konsole", ["-p", "tabtitle=claudeMon", "-e", "sh", "-c", cmd]),
                          ("xterm", ["-T", "claudeMon", "-e", "sh", "-c", cmd])):
            if shutil.which(exe):
                subprocess.Popen([exe] + argv)
                return "opened in " + exe
        return "no supported terminal found; run `claudemon` in a terminal instead"

    if "ghostty" in term and shutil.which("open"):
        subprocess.run(["open", "-na", "Ghostty", "--args", "--title=claudeMon", "-e", "sh", "-c", cmd], check=True)
        return "opened in Ghostty"
    if "iterm" in term:
        _osa('tell application "iTerm"\n'
             '  set w to (create window with default profile command %s)\n'
             '  tell current session of w to set name to "claudeMon"\n'
             '  activate\n'
             'end tell' % _as_str("sh -c " + shlex.quote(cmd)))
        return "opened in iTerm"
    _osa('tell application "Terminal"\n'
         '  set t to do script %s\n'
         '  set custom title of t to "claudeMon"\n'
         '  set title displays custom title of t to true\n'
         '  try\n'
         '    set number of columns of t to %s\n'
         '    set number of rows of t to %s\n'
         '  end try\n'
         '  activate\n'
         'end tell' % (_as_str(cmd), cols, rows))
    return "opened in Terminal"
