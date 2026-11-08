#!/usr/bin/env python3
"""Run claudeMon headless and print its screen as JSON (used by shots.py).

    CLAUDE_CONFIG_DIR=<home> CLAUDEMON_DEMO=1 tools/grid.py COLSxROWS THEME PAGE

Output: {"cols", "rows", "cells": [[[ch, fg, bg, bold, underline], ...] per row]}
where fg/bg are xterm-256 indices (-1 = terminal default).
"""

import curses
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# A fake curses: just enough for draw.Screen, recording colours instead of drawing.
PAIRS = {}
curses.COLORS = 256
curses.COLOR_PAIRS = 1 << 16
curses.init_pair = lambda n, fg, bg: PAIRS.__setitem__(n, (fg, bg))
curses.color_pair = lambda n: n << 24


class FakeWin:
    def __init__(self, rows, cols):
        self.rows, self.cols = rows, cols
        self.bg = 0
        self.erase()

    def getmaxyx(self):
        return self.rows, self.cols

    def bkgd(self, ch, attr=0):
        self.bg = attr

    def erase(self):
        self.g = [[(" ", self.bg)] * self.cols for _ in range(self.rows)]

    def addstr(self, y, x, text, attr=0):
        for i, ch in enumerate(text):
            if 0 <= y < self.rows and 0 <= x + i < self.cols:
                self.g[y][x + i] = (ch, attr)

    def refresh(self):
        pass

    def dump(self):
        out = []
        for row in self.g:
            cells = []
            for ch, attr in row:
                fg, bg = PAIRS.get(attr >> 24, (-1, -1))
                cells.append([ch, fg, bg, bool(attr & curses.A_BOLD), bool(attr & curses.A_UNDERLINE)])
            out.append(cells)
        return out


def main():
    size, theme, page = sys.argv[1], sys.argv[2], sys.argv[3]
    cols, _, rows = size.partition("x")
    cols, rows = int(cols), int(rows)
    import draw
    import tui
    from store import Store

    store = Store()
    store.start()
    for _ in range(100):
        if store.indexed:
            break
        time.sleep(.1)
    draw.set_ascii(draw.detect_ascii())
    win = FakeWin(rows, cols)
    app = tui.App(win, store, {"theme": theme, "tap_prompt_seen": True})
    app.tick(force=True)
    app.go(page)
    app.tick(force=True)
    app.draw()
    json.dump({"cols": cols, "rows": rows, "cells": win.dump()}, sys.stdout)


if __name__ == "__main__":
    main()
