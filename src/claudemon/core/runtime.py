"""Which interpreter runs the tap, and how claudeMon starts itself again."""

import os
import shutil
import subprocess
import sys

from claudemon.core.paths import stable_python

SYSTEM_PYTHON = "/usr/bin/python3"
PROBE_TIMEOUT_S = 5
WRAPPER = None          # the root claudemon.py's realpath, set by that file when it is run
_CLT_PYTHONS = ("/Library/Developer/CommandLineTools/usr/bin/python3",
                "/Applications/Xcode.app/Contents/Developer/usr/bin/python3")


def _check(path):
    """None when `path` starts a Python new enough for tap.py (3.9+) within a few seconds,
    else why not: "missing", "slow", "old" or "broken"."""
    try:
        r = subprocess.run([path, "-c", "import sys; sys.exit(3 if sys.version_info < (3, 9) else 0)"],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=PROBE_TIMEOUT_S)
    except FileNotFoundError:
        return "missing"
    except subprocess.TimeoutExpired:
        return "slow"
    except (OSError, subprocess.SubprocessError):
        return "broken"
    # 3, not 1: a Python that dies at startup (a bad PYTHONHOME, say) exits 1, and is not "old"
    return None if r.returncode == 0 else "old" if r.returncode == 3 else "broken"


# what to do about the system Python, by why _check() turned it down
# (install keeps a baked interpreter that still exists, so moving off it takes an uninstall first)
_AGAIN = "`claudemon uninstall` then `claudemon install`"
_FIX = {
    "missing": "install the system Python, then run " + _AGAIN,
    "slow": "%(py)s did not answer within %(s)d s (a first run can be slow); run " + _AGAIN,
    "old": "%(py)s is older than 3.9; upgrade it, then run " + _AGAIN,
    "broken": "%(py)s did not run; fix it, then run " + _AGAIN,
}


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
    why = "missing"
    if platform == "darwin":
        if any(os.path.exists(p) for p in _CLT_PYTHONS):
            why = _check(SYSTEM_PYTHON)
    elif platform.startswith("linux"):
        why = _check(SYSTEM_PYTHON)
    if why is None:
        return SYSTEM_PYTHON, None
    base = _base_python()
    if base:
        fix = _FIX[why] % {"py": SYSTEM_PYTHON, "s": PROBE_TIMEOUT_S}
        return base, ("the status-line tap will run on %s, which can move or vanish when it is upgraded; %s"
                      % (base, fix))
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
    if WRAPPER:
        return [sys.executable, WRAPPER]
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
    return [sys.executable, "-m", "claudemon"]
