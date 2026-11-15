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

from claudemon import commands
from claudemon import __version__
from claudemon.ui.themes import ORDER


def main(argv=None):
    p = argparse.ArgumentParser(prog="claudemon", description="A task manager for Claude Code.")
    p.add_argument("command", nargs="?", default="run", choices=["run"] + list(commands.COMMANDS))
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
        from claudemon.window import parse_size
        if not parse_size(args.size):
            p.error("--size must look like 150x46")

    if args.command in commands.COMMANDS:
        commands.COMMANDS[args.command](args)
    elif args.window:
        from claudemon.window import open_window
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
        from claudemon.ui.app import run
        run(args.theme, args.interval, args.page, args.mini)


if __name__ == "__main__":
    main()
