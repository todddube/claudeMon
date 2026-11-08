"""Filesystem locations claudeMon reads from and writes to."""

import os
import sys
from pathlib import Path

CLAUDE_HOME = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")).expanduser()
SESSIONS_DIR = CLAUDE_HOME / "sessions"
PROJECTS_DIR = CLAUDE_HOME / "projects"
SETTINGS_FILE = CLAUDE_HOME / "settings.json"
JOBS_DIR = CLAUDE_HOME / "jobs"
SCHEDULED_DIR = CLAUDE_HOME / "scheduled-tasks"

# claudeMon's own state lives beside Claude Code's, never inside its files.
STATE_DIR = CLAUDE_HOME / "claudemon"
STATUS_DIR = STATE_DIR / "status"          # latest status-line JSON per session
LIMITS_LOG = STATE_DIR / "limits.jsonl"    # rate-limit observations over time
TAP_BACKUP = STATE_DIR / "statusline.backup.json"


def stable_python():
    """The interpreter to bake into settings.json and new windows.

    sys.executable can be a versioned path that disappears on upgrade (Xcode's
    python, a Homebrew Cellar directory), which would silently blank the status
    line; prefer the stable name when there is one.
    """
    exe = sys.executable or "python3"
    if "/Xcode.app/" in exe or "/CommandLineTools/" in exe:
        return "/usr/bin/python3"
    if "/Cellar/" in exe:
        cand = exe.split("/Cellar/")[0] + "/bin/python3"
        if os.path.exists(cand):
            return cand
    return exe
