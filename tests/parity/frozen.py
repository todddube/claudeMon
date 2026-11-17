"""Run a Python script or module with a frozen clock (the parity harness's launcher).

    PARITY_FROZEN_TIME=<epoch> python frozen.py <script.py> [args...]
    PARITY_FROZEN_TIME=<epoch> python frozen.py -m <module> [args...]

Before anything else is imported, time.time() and datetime.datetime.now()/today()/
utcnow() are pinned to PARITY_FROZEN_TIME. Then the target runs the way the
interpreter would run it: as a script, sys.argv is [script, *args] and sys.path[0]
is the script's real folder; with -m, sys.path[0] is the working directory.

PARITY_PLATFORM, when set, replaces sys.platform (the harness uses it to reach
both terminal branches of --window on one machine).

Nothing here is a sitecustomize: the target sees exactly the sys.path it would
have had, minus this file's own folder.
"""

import datetime as _dt
import os
import runpy
import sys
import time

FROZEN = float(os.environ["PARITY_FROZEN_TIME"])


def _time():
    return FROZEN


class FrozenDatetime(_dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls.fromtimestamp(FROZEN, tz)

    @classmethod
    def today(cls):
        return cls.fromtimestamp(FROZEN)

    @classmethod
    def utcnow(cls):
        return cls.utcfromtimestamp(FROZEN)


time.time = _time
_dt.datetime = FrozenDatetime
if os.environ.get("PARITY_PLATFORM"):
    sys.platform = os.environ["PARITY_PLATFORM"]


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit("usage: frozen.py <script.py> [args...] | -m <module> [args...]")
    if args[0] == "-m":
        mod, rest = args[1], args[2:]
        sys.argv = [mod] + rest
        sys.path[0] = os.getcwd()
        runpy.run_module(mod, run_name="__main__", alter_sys=True)
    else:
        script, rest = args[0], args[1:]
        sys.argv = [script] + rest
        sys.path[0] = os.path.dirname(os.path.realpath(script))
        runpy.run_path(script, run_name="__main__")


if __name__ == "__main__":
    main()
