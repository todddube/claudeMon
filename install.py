"""Install or remove the status-line tap and Notification hook in settings.json.

The original status-line command is kept inside the new one
(`tap.py statusline -- '<original>'`) and in a backup file, so uninstall
restores it exactly. Hook entries are tagged with MARK so only ours are removed.
"""

import json
import re
import shlex
import os
import shutil
import time
from pathlib import Path

from paths import SETTINGS_FILE, STATE_DIR, TAP_BACKUP, stable_python

TAP = Path(__file__).resolve().parent / "tap.py"
MARK = "# claudemon"


def _load():
    try:
        with open(SETTINGS_FILE) as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}


def _save(settings):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if SETTINGS_FILE.exists():
        shutil.copy2(SETTINGS_FILE, STATE_DIR / ("settings.%d.bak.json" % time.time()))
    tmp = SETTINGS_FILE.with_suffix(".claudemon.tmp")
    with open(tmp, "w") as fh:
        json.dump(settings, fh, indent=2)
        fh.write("\n")
    tmp.replace(SETTINGS_FILE)


def _python():
    return shlex.quote(stable_python())


def _hook_command():
    return "%s %s hook Notification %s" % (_python(), shlex.quote(str(TAP)), MARK)


def status(settings=None):
    s = settings if settings is not None else _load()
    cmd = (s.get("statusLine") or {}).get("command", "")
    hooks = (s.get("hooks") or {}).get("Notification") or []
    has_hook = any(MARK in h.get("command", "") for entry in hooks for h in entry.get("hooks", []))
    return {"statusline": "tap.py statusline" in cmd, "hook": has_hook}


def installed():
    try:
        st = status()
    except (OSError, ValueError):
        return False
    return st["statusline"] and st["hook"]


def _gone(cmd):
    """True when the interpreter at the start of an installed tap command no longer exists."""
    try:
        exe = shlex.split(cmd)[0]
    except (ValueError, IndexError):
        return False
    return os.path.isabs(exe) and not os.path.exists(exe)


def _repoint(cmd, verb):
    """Swap in this checkout's tap.py and (if the old one vanished) a working interpreter."""
    cmd = re.sub(r"\S*tap\.py(?= %s)" % verb, lambda m: shlex.quote(str(TAP)), cmd, count=1)
    if _gone(cmd):
        cmd = re.sub(r"^\S+", lambda m: _python(), cmd, count=1)
    return cmd


def repair():
    """Re-point an installed tap at this checkout's tap.py (the repo may have moved)."""
    try:
        s = _load()
    except ValueError:
        return ""
    changed = False
    sl = s.get("statusLine") or {}
    cmd = sl.get("command", "")
    if "tap.py statusline" in cmd and (str(TAP) not in cmd or _gone(cmd)):
        sl["command"] = _repoint(cmd, "statusline")
        changed = True
    for entry in (s.get("hooks") or {}).get("Notification") or []:
        for h in entry.get("hooks", []):
            c = h.get("command", "")
            if MARK in c and "tap.py hook" in c and (str(TAP) not in c or _gone(c)):
                h["command"] = _repoint(c, "hook")
                changed = True
    if not changed:
        return ""
    _save(s)
    return "tap re-pointed at " + str(TAP)


def install():
    try:
        s = _load()
    except ValueError:
        return "settings.json is not valid JSON; not touching it"
    st = status(s)
    if st["statusline"] and st["hook"]:
        return "tap already installed"
    if not st["statusline"]:
        old = s.get("statusLine")
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(TAP_BACKUP, "w") as fh:
            json.dump({"statusLine": old}, fh, indent=2)
        orig = (old or {}).get("command", "")
        cmd = "%s %s statusline" % (_python(), shlex.quote(str(TAP)))
        if orig:
            cmd += " -- " + shlex.quote(orig)
        new = dict(old or {}, type="command", command=cmd)
        s["statusLine"] = new
    if not st["hook"]:
        hooks = s.setdefault("hooks", {})
        hooks.setdefault("Notification", []).append({"hooks": [{"type": "command", "command": _hook_command()}]})
    _save(s)
    return "tap installed: limits and 'needs you' are live from the next status-line refresh"


def uninstall():
    try:
        s = _load()
    except ValueError:
        return "settings.json is not valid JSON; not touching it"
    changed = False
    cmd = (s.get("statusLine") or {}).get("command", "")
    if "tap.py statusline" in cmd:
        restored = None
        try:
            with open(TAP_BACKUP) as fh:
                restored = json.load(fh).get("statusLine")
        except (OSError, ValueError):
            parts = cmd.split(" -- ", 1)
            if len(parts) == 2:
                restored = dict(s["statusLine"], command=shlex.split(parts[1])[0])
        if restored:
            s["statusLine"] = restored
        else:
            s.pop("statusLine", None)
        changed = True
    notif = (s.get("hooks") or {}).get("Notification")
    if notif:
        kept = []
        for entry in notif:
            entry["hooks"] = [h for h in entry.get("hooks", []) if MARK not in h.get("command", "")]
            if entry["hooks"]:
                kept.append(entry)
        if len(kept) != len(notif):
            changed = True
            if kept:
                s["hooks"]["Notification"] = kept
            else:
                del s["hooks"]["Notification"]
            if not s["hooks"]:
                del s["hooks"]
    if not changed:
        return "tap was not installed"
    _save(s)
    return "tap removed; original status line restored"
