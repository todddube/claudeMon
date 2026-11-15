"""Which interpreter runs the tap, and how claudeMon starts itself again."""

import os
import shutil
import subprocess
import sys

from claudemon.core.paths import stable_python

SYSTEM_PYTHON = "/usr/bin/python3"
PROBE_TIMEOUT_S = 5
_CLT_PYTHONS = ("/Library/Developer/CommandLineTools/usr/bin/python3",
                "/Applications/Xcode.app/Contents/Developer/usr/bin/python3")


def _probe(path):
    """True when `path` starts Python and runs a statement within a few seconds."""
    try:
        r = subprocess.run([path, "-c", "pass"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=PROBE_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def _in_venv():
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def _base_python():
    """A non-venv interpreter for the platform-less fallback."""
    if _in_venv():
        base = getattr(sys, "_base_executable", None)
        if base and os.path.exists(base) and not base.startswith(sys.prefix):
            return stable_python(base)
        cand = os.path.join(sys.base_prefix, "bin", "python3")
        return cand if os.path.exists(cand) else None
    return stable_python()


def tap_choice(platform=None):
    """(interpreter, warning) for a fresh tap install, or for one whose baked interpreter vanished.

    The status line runs on every refresh and goes blank if its interpreter disappears, so the
    choice is the system Python (managed by the OS or the package manager), never a venv or a
    versioned brew/uv path. `warning` is None unless only a less stable interpreter was found."""
    platform = platform or sys.platform
    if platform == "darwin":
        if any(os.path.exists(p) for p in _CLT_PYTHONS) and _probe(SYSTEM_PYTHON):
            return SYSTEM_PYTHON, None
    elif platform.startswith("linux"):
        if _probe(SYSTEM_PYTHON):
            return SYSTEM_PYTHON, None
    base = _base_python()
    if base:
        return base, ("the status-line tap will run on %s, which can move or vanish when it is upgraded; "
                      "install the system Python and run `claudemon install` again" % base)
    exe = sys.executable or "python3"
    return exe, "no base Python found; the status-line tap will run on %s, which may vanish" % exe


def tap_python(platform=None):
    return tap_choice(platform)[0]


def _argv0_path():
    argv0 = sys.argv[0] if sys.argv and sys.argv[0] else ""
    if not argv0:
        return None
    if os.sep in argv0:
        return os.path.abspath(argv0)
    found = shutil.which(argv0)
    return os.path.abspath(found) if found else None


def self_command():
    """The argv that starts claudeMon again (for --window)."""
    main = sys.modules.get("__main__")
    spec = getattr(main, "__spec__", None)
    if spec is not None and getattr(spec, "name", None):
        name = spec.name[:-len(".__main__")] if spec.name.endswith(".__main__") else spec.name
        return [sys.executable, "-m", name]
    path = _argv0_path()
    if path and os.path.realpath(path).endswith(".py"):
        return [sys.executable, os.path.realpath(path)]
    if path:
        return [path]          # an installed entry point: the path as invoked, not its realpath
    return [sys.executable, os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "claudemon.py"))]
