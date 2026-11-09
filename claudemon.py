#!/usr/bin/env python3
"""claudemon command line.

  claudemon                 run the TUI in this terminal
  claudemon --window        open it in a new terminal window titled claudeMon
  claudemon --mini          start in the mini view (z switches between mini and full)
  claudemon install         add the status-line tap + Notification hook
  claudemon uninstall       remove them and restore your status line
  claudemon loops           print files re-read 3+ times with no edit between
  claudemon snapshot        print a one-shot text summary of live sessions
"""

import argparse
import os
import sys
import time

import install
from version import __version__
from themes import ORDER


def cmd_loops(args):
    from store import Store
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
    from store import Store, short_model
    from tui import fpct, ftok
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
        f = store.limits.forecast(key, store.tokens_between)
        if f.pct is not None:
            print("%s limit %.0f%%  %s" % (label, f.pct, f.note))
    if not store.limits.forecast("five_hour", store.tokens_between).pct and not install.installed():
        print("Limits are empty: run `claudemon install` to add the tap.")


def main(argv=None):
    p = argparse.ArgumentParser(prog="claudemon", description="A task manager for Claude Code.")
    p.add_argument("command", nargs="?", default="run", choices=["run", "install", "uninstall", "loops", "snapshot"])
    p.add_argument("-w", "--window", action="store_true", help="open in a new terminal window titled claudeMon")
    p.add_argument("--terminal", help="terminal for --window: terminal, iterm or ghostty")
    p.add_argument("-t", "--theme", choices=ORDER)
    p.add_argument("-i", "--interval", type=int, choices=[1, 2, 5, 10])
    p.add_argument("-p", "--page", help="start on a page (number or name), or manual[:topic] / prompt")
    p.add_argument("-z", "--mini", action="store_true", help="start in the small mini view (z toggles it)")
    p.add_argument("--ascii", action="store_true", help="draw with plain ASCII (automatic when the locale is not UTF-8)")
    p.add_argument("--size", help="window size for --window, e.g. 150x46 (default 160x50, or 74x12 with --mini)")
    p.add_argument("--hours", type=int, default=24, help="look-back for `loops`")
    p.add_argument("-V", "--version", action="version", version="claudemon " + __version__)
    args = p.parse_args(argv)
    if args.size:
        from launch import parse_size
        if not parse_size(args.size):
            p.error("--size must look like 150x46")

    if args.command == "install":
        print(install.install())
    elif args.command == "uninstall":
        print(install.uninstall())
    elif args.command == "loops":
        cmd_loops(args)
    elif args.command == "snapshot":
        cmd_snapshot(args)
    elif args.window:
        from launch import open_window
        extra = []
        if args.theme:
            extra += ["--theme", args.theme]
        if args.interval:
            extra += ["--interval", str(args.interval)]
        if args.page:
            extra += ["--page", args.page]
        if args.ascii:
            extra += ["--ascii"]
        if args.mini:
            extra += ["--mini"]
        print(open_window(args.terminal, extra, args.size or ("74x12" if args.mini else "160x50")))
    else:
        if not sys.stdout.isatty():
            sys.exit("claudemon needs a terminal; try `claudemon --window` or `claudemon snapshot`")
        if args.ascii:
            os.environ["CLAUDEMON_ASCII"] = "1"
        from tui import run
        run(args.theme, args.interval, args.page, args.mini)


if __name__ == "__main__":
    main()
