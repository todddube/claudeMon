"""Install or remove the status-line tap and Notification hook in settings.json.

install copies tap.py to ~/.claude/claudemon/tap.py and points settings.json at
that copy, so moving or deleting this checkout never breaks the status line.
The original status-line command is kept inside the new one
(`tap.py statusline -- '<original>' # claudemon`) and in a backup file, so
uninstall restores it. Every command we write ends with MARK; commands are
recognised by parsing them, never by substring, and only ours are touched.
"""

import json
import os
import re
import shlex
import stat
import time
from pathlib import Path

from paths import SETTINGS_FILE, STATE_DIR, TAP_BACKUP, stable_python

TAP_SRC = Path(__file__).resolve().parent / "tap.py"   # the copy in this checkout
TAP = STATE_DIR / "tap.py"                              # the copy settings.json runs
MARK = "# claudemon"
KEEP_BACKUPS = 10
BACKUP_RE = re.compile(r"^settings\.(\d+)\.bak\.json$")


class ShapeError(ValueError):
    """settings.json is valid JSON but not shaped the way Claude Code writes it."""


class Conflict(Exception):
    """settings.json changed between our read and our write."""


# ── reading and writing settings.json ────────────────────────────────────────
def _check_shape(s):
    if not isinstance(s, dict):
        raise ShapeError("top level is not an object")
    sl = s.get("statusLine")
    if sl is not None and not isinstance(sl, dict):
        raise ShapeError("statusLine is not an object")
    if isinstance(sl, dict) and not isinstance(sl.get("command", ""), str):
        raise ShapeError("statusLine.command is not a string")
    hooks = s.get("hooks")
    if hooks is None:
        return
    if not isinstance(hooks, dict):
        raise ShapeError("hooks is not an object")
    notif = hooks.get("Notification")
    if notif is None:
        return
    if not isinstance(notif, list):
        raise ShapeError("hooks.Notification is not a list")
    for entry in notif:
        if not isinstance(entry, dict) or not isinstance(entry.get("hooks", []), list):
            raise ShapeError("a Notification hook entry is not an object with a hooks list")
        for h in entry.get("hooks", []):
            if not isinstance(h, dict) or not isinstance(h.get("command", ""), str):
                raise ShapeError("a Notification hook is not an object with a command string")


def _read():
    """(settings, raw bytes or None when the file does not exist).

    Raises ValueError for invalid JSON (ShapeError for a wrong shape) and OSError when unreadable."""
    try:
        with open(SETTINGS_FILE, "rb") as fh:
            raw = fh.read()
    except FileNotFoundError:
        return {}, None
    s = json.loads(raw.decode("utf-8"))
    _check_shape(s)
    return s, raw


def _indent(raw):
    """Keep the file's own indentation (tabs or n spaces) when we rewrite it."""
    m = re.search(rb"\n([ \t]+)\S", raw or b"")
    if not m:
        return 2
    lead = m.group(1).decode()
    return "\t" if lead.startswith("\t") else len(lead)


def _state_dir():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(STATE_DIR, 0o700)       # backups of settings.json can hold env secrets
    except OSError:
        pass


def _write_private(path, data, mode=0o600):
    """Atomically write bytes to path with the given mode."""
    path = Path(path)
    tmp = path.with_name(".%s.claudemon.%d.tmp" % (path.name, os.getpid()))
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(str(tmp), mode)          # os.open's mode is filtered by the umask
        os.replace(str(tmp), str(path))
    except BaseException:
        try:
            os.unlink(str(tmp))
        except OSError:
            pass
        raise


def _prune_backups():
    found = []
    for p in STATE_DIR.glob("settings.*.bak.json"):
        m = BACKUP_RE.match(p.name)
        if m:
            found.append((int(m.group(1)), p))
    found.sort()
    for _, p in found[:-KEEP_BACKUPS]:
        try:
            p.unlink()
        except OSError:
            pass


def _save(settings, raw):
    """Write settings.json, following a symlink and keeping the file's mode.

    `raw` is what _read() saw; if the file changed since, nothing is written (Conflict)."""
    target = Path(os.path.realpath(str(SETTINGS_FILE)))
    try:
        current = target.read_bytes()
    except FileNotFoundError:
        current = None
    if current != raw:
        raise Conflict()
    _state_dir()
    mode = 0o600
    if current is not None:
        mode = stat.S_IMODE(os.stat(str(target)).st_mode)
        _write_private(STATE_DIR / ("settings.%d.bak.json" % time.time_ns()), current)
        _prune_backups()
    text = json.dumps(settings, indent=_indent(current), ensure_ascii=False) + "\n"
    _write_private(target, text.encode("utf-8"), mode)


# ── recognising and building our commands ────────────────────────────────────
def _python():
    return stable_python()


def _ours(tap_path, known=()):
    """An unmarked (pre-marker) command counts as ours only if its tap.py is claudeMon's:
    one of our copies, the tap a marked hook in the same settings runs (old installs
    always added one), or a file or folder that says so."""
    if tap_path in (str(TAP), str(TAP_SRC)) or tap_path in known:
        return True
    p = Path(tap_path)
    if (p.parent / "claudemon.py").exists() or "claudemon" in tap_path.lower():
        return True
    try:
        with open(tap_path, "rb") as fh:
            return b"tap for claudeMon" in fh.read(400)
    except OSError:
        return False


def _split(cmd):
    """(argv without the trailing marker, marked) or (None, False) when it does not parse."""
    if not isinstance(cmd, str) or not cmd:
        return None, False
    try:
        argv = shlex.split(cmd)
    except ValueError:
        return None, False
    marked = argv[-2:] == ["#", "claudemon"]
    return (argv[:-2] if marked else argv), marked


def parse(cmd, known=()):
    """dict(python, tap, verb, args, orig) when `cmd` is a claudeMon tap command, else None.

    `orig` is the wrapped original status-line command (or "" when there is none).
    `known` are tap paths already known to be ours (from marked hooks)."""
    argv, marked = _split(cmd)
    if argv is None or len(argv) < 3 or os.path.basename(argv[1]) != "tap.py" or argv[2] not in ("statusline", "hook"):
        return None
    if not (marked or _ours(argv[1], known)):
        return None
    rest = argv[3:]
    orig = ""
    if argv[2] == "statusline":
        if rest[:1] == ["--"]:
            rest = rest[1:]
        orig = rest[0] if len(rest) == 1 else " ".join(shlex.quote(a) for a in rest)
    return dict(python=argv[0], tap=argv[1], verb=argv[2], args=rest, orig=orig)


def unwrap(cmd, known=()):
    """The user's own status-line command inside one or more layers of our tap."""
    for _ in range(20):
        p = parse(cmd, known)
        if not p or p["verb"] != "statusline":
            return cmd
        cmd = p["orig"]
    return cmd


def _statusline_command(orig, python=None):
    cmd = "%s %s statusline" % (shlex.quote(python or _python()), shlex.quote(str(TAP)))
    if orig:
        cmd += " -- " + shlex.quote(orig)
    return cmd + " " + MARK


def _hook_command(python=None):
    return "%s %s hook Notification %s" % (shlex.quote(python or _python()), shlex.quote(str(TAP)), MARK)


def _is_our_hook(h):
    """Ours = a marked `… tap.py hook <Event> # claudemon` command (parsed, not a substring match)."""
    if not isinstance(h, dict):
        return False
    argv, marked = _split(h.get("command"))
    return bool(marked and argv and len(argv) >= 3 and os.path.basename(argv[1]) == "tap.py" and argv[2] == "hook")


def _gone(python):
    return os.path.isabs(python) and not os.path.exists(python)


def _statusline_cmd(s):
    sl = s.get("statusLine")
    return sl.get("command", "") if isinstance(sl, dict) else ""


def _our_hooks(s):
    for entry in (s.get("hooks") or {}).get("Notification") or []:
        for h in entry.get("hooks", []):
            if _is_our_hook(h):
                yield h


def _known_taps(s):
    return {_split(h["command"])[0][1] for h in _our_hooks(s)}


def status(settings=None):
    s = settings if settings is not None else _read()[0]
    p = parse(_statusline_cmd(s), _known_taps(s))
    return {"statusline": bool(p and p["verb"] == "statusline"), "hook": any(True for _ in _our_hooks(s))}


def safe_status():
    """status() plus an "error" message instead of raising (for display)."""
    try:
        return dict(status(), error="")
    except ShapeError as e:
        return {"statusline": False, "hook": False, "error": "settings.json has an unexpected shape: %s" % e}
    except ValueError:
        return {"statusline": False, "hook": False, "error": "settings.json is not valid JSON"}
    except OSError as e:
        return {"statusline": False, "hook": False, "error": "cannot read settings.json: %s" % (e.strerror or e)}


def installed():
    """True when both parts are in settings.json. Never raises: it runs on every UI tick."""
    try:
        st = status()
    except Exception:
        return False
    return st["statusline"] and st["hook"]


def install_tap_copy():
    """Copy this checkout's tap.py to ~/.claude/claudemon/tap.py if it differs. True when written."""
    src = TAP_SRC.read_bytes()
    try:
        if TAP.read_bytes() == src:
            return False
    except OSError:
        pass
    _state_dir()
    _write_private(TAP, src, 0o644)
    return True


def _normalise(s, add):
    """Point every claudeMon command at the installed copy, unwrapping nested taps.

    With add=True, also wrap the status line and add the hook if they are missing.
    Returns True when `s` changed."""
    changed = False
    known = _known_taps(s)
    cmd = _statusline_cmd(s)
    p = parse(cmd, known)
    if p and p["verb"] == "statusline":
        py = p["python"] if not _gone(p["python"]) else None
        new = _statusline_command(unwrap(cmd, known), py)
        if new != cmd:
            s["statusLine"]["command"] = new
            changed = True
    elif add:
        old = s.get("statusLine")
        _state_dir()
        _write_private(TAP_BACKUP, json.dumps({"statusLine": old}, indent=2, ensure_ascii=False).encode("utf-8"))
        new = dict(old or {}, type="command", command=_statusline_command(cmd))
        s["statusLine"] = new
        changed = True

    found = False
    for h in _our_hooks(s):
        found = True
        hp = parse(h["command"], known)
        py = hp["python"] if hp and not _gone(hp["python"]) else None
        new = _hook_command(py)
        if new != h["command"]:
            h["command"] = new
            changed = True
    if add and not found:
        hooks = s.setdefault("hooks", {})
        hooks.setdefault("Notification", []).append({"hooks": [{"type": "command", "command": _hook_command()}]})
        changed = True
    return changed


def _load_or_message():
    try:
        return _read(), None
    except ShapeError as e:
        return None, "settings.json has an unexpected shape (%s); not touching it" % e
    except ValueError:
        return None, "settings.json is not valid JSON; not touching it"
    except OSError as e:
        return None, "cannot read settings.json: %s" % (e.strerror or e)


def _write(s, raw):
    try:
        _save(s, raw)
    except Conflict:
        return "settings.json changed while claudeMon was editing it; nothing written, try again"
    except OSError as e:
        return "cannot write settings.json: %s" % (e.strerror or e)
    return None


# ── the three operations ─────────────────────────────────────────────────────
def repair():
    """Keep an installed tap working: refresh the installed tap.py copy and re-point
    commands that still run another copy (an old checkout) or a vanished interpreter.
    Does nothing when the tap is not installed. Never raises."""
    try:
        loaded, err = _load_or_message()
        if err:
            return ""
        s, raw = loaded
        st = status(s)
        if not (st["statusline"] or st["hook"]):
            return ""
        copied = install_tap_copy()
        if not _normalise(s, add=False):
            return "tap updated" if copied else ""
        err = _write(s, raw)
        return err or "tap re-pointed at " + str(TAP)
    except Exception as e:                # a repair problem must never stop claudeMon starting
        return "tap repair failed: %s" % e


def install():
    (loaded, err) = _load_or_message()
    if err:
        return err
    s, raw = loaded
    try:
        install_tap_copy()
        st = status(s)
        changed = _normalise(s, add=True)
    except OSError as e:
        return "cannot write %s: %s" % (STATE_DIR, e.strerror or e)
    if not changed:
        return "tap already installed"
    err = _write(s, raw)
    if err:
        return err
    if st["statusline"] and st["hook"]:
        return "tap already installed; re-pointed at " + str(TAP)
    return "tap installed: limits and 'needs you' are live from the next status-line refresh"


def _backup_statusline():
    try:
        with open(TAP_BACKUP, encoding="utf-8") as fh:
            b = json.load(fh)
    except (OSError, ValueError):
        return None
    sl = b.get("statusLine") if isinstance(b, dict) else None
    return sl if isinstance(sl, dict) else None


def uninstall():
    (loaded, err) = _load_or_message()
    if err:
        return err
    s, raw = loaded
    changed = False
    restored = False
    known = _known_taps(s)
    cmd = _statusline_cmd(s)
    p = parse(cmd, known)
    if p and p["verb"] == "statusline":
        orig = unwrap(cmd, known)
        if orig:              # the command itself is the freshest record of the original
            s["statusLine"]["command"] = orig
            restored = True
        else:
            old = _backup_statusline()
            if old and unwrap(old.get("command") or ""):
                s["statusLine"] = dict(old, command=unwrap(old["command"]))
                restored = True
            else:
                s.pop("statusLine", None)
        changed = True
    notif = (s.get("hooks") or {}).get("Notification")
    if notif:
        kept = []
        removed = False
        for entry in notif:
            hooks = [h for h in entry.get("hooks", []) if not _is_our_hook(h)]
            if len(hooks) == len(entry.get("hooks", [])):
                kept.append(entry)            # not ours: leave it exactly as it was
                continue
            removed = True
            entry["hooks"] = hooks
            if hooks:
                kept.append(entry)
        if removed:
            changed = True
            if kept:
                s["hooks"]["Notification"] = kept
            else:
                del s["hooks"]["Notification"]
            if not s["hooks"]:
                del s["hooks"]
    if not changed:
        return "tap was not installed"
    err = _write(s, raw)
    if err:
        return err
    try:
        TAP.unlink()
    except OSError:
        pass
    return "tap removed; original status line restored" if restored else "tap removed"
