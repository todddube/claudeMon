"""The subcommands that run once and print: one function and one COMMANDS entry each.

A command takes the parsed argparse namespace. claudemon.py builds the command-line choices from
COMMANDS, so adding a subcommand is one function here and one line in the registry.
"""

import time

from claudemon.tap import installer as install


def cmd_install(args):
    print(install.install())


def cmd_uninstall(args):
    print(install.uninstall())


def cmd_loops(args):
    from claudemon.sources.store import Store
    store = Store()
    store.index()
    store.refresh()
    since = time.time() - args.hours * 3600
    found = False
    for s in store.recent_sessions(since):
        loops = s.loops()
        if not loops:
            continue
        found = True
        print("%s  (%s)" % (s.name, s.project))
        for path, worst, current, a in loops:
            who = "subagent %s" % a.label if a else "main"
            print("  %3d× read, no edit between   %s   [%s, %d since last edit]" % (worst, path, who, current))
    if not found:
        print("No re-read loops in the last %d h." % args.hours)


def cmd_snapshot(args):
    from claudemon.sources.store import Store, short_model
    from claudemon.core.fmt import fpct, ftok
    store = Store()
    store.index()
    store.refresh()
    live = store.live_sessions()
    if not live:
        print("No live Claude Code sessions.")
    for s in live:
        used, size = s.context()
        t = s.t.totals()
        print("%-24s %-10s %-10s %-7s ctx %-5s out %-7s agents %d  loops %d" % (
            s.name[:24], s.state(), short_model(s.model), s.effort or "-", fpct(used / size),
            ftok(t.output), len(s.agents), len(s.loops())))
    for key, label in (("five_hour", "5h"), ("seven_day", "7d")):
        f = store.forecast(key)
        if f.pct is not None:
            print("%s limit %.0f%%  %s" % (label, f.pct, f.note))
    if not store.forecast("five_hour").pct and not install.installed():
        print("Limits are empty: run `claudemon install` to add the tap.")


# Ordered: this is the order the command-line help lists them in.
COMMANDS = {
    "install": cmd_install,
    "uninstall": cmd_uninstall,
    "loops": cmd_loops,
    "snapshot": cmd_snapshot,
}
