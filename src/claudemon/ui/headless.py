"""A fake curses window and an explicit curses stub, for running the TUI headless.

Nothing here touches curses on import. Call install() once, before drawing, to give the curses
module just enough colour support for draw.Screen: color pairs are recorded in PAIRS instead of
being drawn, so FakeWin.dump() can report each cell's colours.
"""

import curses

PAIRS = {}


def install():
    """Patch curses with the colour stub. Safe to call more than once."""
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
        if not (0 <= y < self.rows and 0 <= x < self.cols) or "\n" in text:
            raise curses.error("addstr() returned ERR")     # as real curses does for these
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
