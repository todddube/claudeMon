#!/usr/bin/env python3
"""Status-line and hook tap for claudeMon: the legacy path, kept for old installs.

Installs from before the tap was copied to ~/.claude/claudemon/ run <clone>/tap.py directly. The
tap now lives in src/claudemon/tap/tap.py; this runs it on the same interpreter with the same
arguments and stdin, until the next `claudemon` start or `claudemon install` re-points the
settings at the copy. Removed in a later release.
"""

import os
import sys

TAP = os.path.join(os.path.dirname(os.path.realpath(__file__)), "src", "claudemon", "tap", "tap.py")

if __name__ == "__main__":
    try:
        os.execv(sys.executable, [sys.executable, TAP] + sys.argv[1:])
    except OSError:                       # no usable sys.executable: run it in this process
        import runpy
        sys.argv[0] = TAP
        runpy.run_path(TAP, run_name="__main__")
