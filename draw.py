"""Drawing primitives on top of curses: themed colour pairs, rounded panels,
multi-colour gauges and a braille canvas for area charts and projections."""

import curses
import unicodedata

from themes import THEMES

BRAILLE = 0x2800
# dot bits by [column][row-from-top]
DOTS = ((0x01, 0x02, 0x04, 0x40), (0x08, 0x10, 0x20, 0x80))
EIGHTHS = " ▏▎▍▌▋▊▉█"
SPARK = " ▁▂▃▄▅▆▇█"


def width(text):
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def clip(text, n):
    if n <= 0:
        return ""
    if len(text) <= n:
        return text
    return text[: max(0, n - 1)] + "…"


class Screen:
    """Owns colour pairs for the active theme and clips every write to the window."""

    def __init__(self, win, theme="claude"):
        self.win = win
        self.pairs = {}
        self.many_colors = curses.COLORS >= 256
        self.set_theme(theme)

    def set_theme(self, name):
        self.theme_name = name if name in THEMES else "claude"
        self.t = THEMES[self.theme_name]
        self.pairs.clear()
        try:
            self.win.bkgd(" ", self.attr(self.t["fg"], self.t["bg"]))
        except curses.error:
            pass

    def _color(self, c):
        if c is None or c < 0 or self.many_colors:
            return -1 if c is None else c
        return c % 8

    def attr(self, fg, bg=None, extra=0):
        bg = self.t["bg"] if bg is None else bg
        key = (fg, bg)
        pair = self.pairs.get(key)
        if pair is None:
            pair = len(self.pairs) + 1
            if pair >= curses.COLOR_PAIRS:
                pair = 0
            else:
                curses.init_pair(pair, self._color(fg), self._color(bg))
            self.pairs[key] = pair
        return curses.color_pair(pair) | extra

    def c(self, role):
        return self.t[role]

    @property
    def size(self):
        return self.win.getmaxyx()

    def put(self, y, x, text, fg=None, bg=None, extra=0, maxw=None):
        h, w = self.size
        if y < 0 or y >= h or x >= w or not text:
            return 0
        room = w - x - (1 if y == h - 1 else 0)    # never write the bottom-right cell
        if maxw is not None:
            room = min(room, maxw)
        text = text[: max(0, room)]
        if not text:
            return 0
        try:
            self.win.addstr(y, x, text, self.attr(self.t["fg"] if fg is None else fg, bg, extra))
        except curses.error:
            pass
        return len(text)

    def fill(self, y, x, h, w, bg):
        for row in range(y, y + h):
            self.put(row, x, " " * w, bg=bg)

    def box(self, y, x, h, w, title="", right="", focus=False, title_fg=None):
        if h < 2 or w < 4:
            return
        b = self.t["accent"] if focus else self.t["border"]
        self.put(y, x, "╭" + "─" * (w - 2) + "╮", b)
        for row in range(y + 1, y + h - 1):
            self.put(row, x, "│", b)
            self.put(row, x + w - 1, "│", b)
        self.put(y + h - 1, x, "╰" + "─" * (w - 2) + "╯", b)
        if title:
            t = clip(title, w - 8)
            self.put(y, x + 2, "┤", b)
            self.put(y, x + 3, t, title_fg or self.t["title"], extra=curses.A_BOLD)
            self.put(y, x + 3 + len(t), "├", b)
        if right:
            r = clip(right, w // 2)
            self.put(y, x + w - 3 - len(r), "┤", b)
            self.put(y, x + w - 2 - len(r), r, self.t["dim"])
            self.put(y, x + w - 2, "├", b)

    def grad_color(self, frac):
        g = self.t["grad"]
        i = min(len(g) - 1, max(0, int(frac * len(g))))
        return g[i]

    def level_color(self, frac):
        if frac >= 0.9:
            return self.t["crit"]
        if frac >= 0.7:
            return self.t["warn"]
        return self.t["ok"]

    def gauge(self, y, x, w, frac, color=None, empty="·"):
        """A horizontal bar; each cell takes its gradient colour unless one is given."""
        if w <= 0:
            return
        frac = max(0.0, min(1.0, frac or 0.0))
        cells = frac * w
        full = int(cells)
        for i in range(w):
            col = color if color is not None else self.grad_color(i / max(1, w - 1))
            if i < full:
                self.put(y, x + i, "█", col)
            elif i == full and cells - full > 0.0625:
                self.put(y, x + i, EIGHTHS[int((cells - full) * 8)], col)
            else:
                self.put(y, x + i, empty, self.t["border"])

    def spark(self, y, x, values, w, color=None, vmax=None):
        """A one-line ▁▂▃ sparkline; longer inputs are squeezed to `w` cells by max."""
        vals = list(values)
        if not vals:
            return
        if len(vals) > w:
            vals = [max(vals[i * len(vals) // w:(i + 1) * len(vals) // w] or [0]) for i in range(w)]
        top = vmax or max(vals) or 1
        for i, v in enumerate(vals):
            frac = min(1.0, v / top)
            ch = SPARK[int(round(frac * 8))] if v > 0 else SPARK[0]
            if v > 0 and ch == " ":
                ch = SPARK[1]
            self.put(y, x + w - len(vals) + i, ch, color if color is not None else self.grad_color(frac))


def blocks(scr, y, x, rows, cols, values, vmax, color_fn, grid=None):
    """Solid area chart from ▁▂▃▄▅▆▇█, one value per cell column (btop's block style)."""
    if not values or rows < 1 or cols < 1:
        return
    n = len(values)
    top = vmax or max(values) or 1
    for c in range(cols):
        lo, hi = c * n // cols, max(c * n // cols + 1, (c + 1) * n // cols)
        v = max(values[lo:hi])
        eighths = int(round(max(0.0, min(1.0, v / top)) * rows * 8))
        if v > 0 and eighths == 0:
            eighths = 1
        for r in range(rows):
            level = rows - 1 - r                 # 0 = bottom row
            fill = eighths - level * 8
            if fill >= 8:
                ch = "█"
            elif fill > 0:
                ch = SPARK[fill]
            else:
                if grid is not None and r % grid[1] == grid[1] - 1:
                    scr.put(y + r, x + c, grid[0], grid[2])
                continue
            scr.put(y + r, x + c, ch, color_fn(level / rows) if color_fn else None)


class Canvas:
    """A braille canvas: each terminal cell holds a 2×4 grid of dots.

    Coordinates are in dots with y = 0 at the bottom. Colours are per cell and
    the last write wins, so draw backgrounds first and highlights last.
    """

    def __init__(self, cols, rows):
        self.cols, self.rows = max(1, cols), max(1, rows)
        self.w, self.h = self.cols * 2, self.rows * 4
        self.bits = [[0] * self.cols for _ in range(self.rows)]
        self.color = [[None] * self.cols for _ in range(self.rows)]
        self.text = {}

    def dot(self, x, y, color=None):
        x, y = int(x), int(y)
        if not (0 <= x < self.w and 0 <= y < self.h):
            return
        row = self.rows - 1 - y // 4
        col = x // 2
        self.bits[row][col] |= DOTS[x % 2][3 - y % 4]
        if color is not None:
            self.color[row][col] = color

    def column(self, x, height, color_fn=None):
        """Fill dot column `x` from the bottom up to `height` dots."""
        for y in range(int(round(height))):
            self.dot(x, y, color_fn(y / self.h) if color_fn else None)

    def line(self, x0, y0, x1, y1, color=None, dash=0):
        x0, y0, x1, y1 = int(x0), int(y0), int(x1), int(y1)
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err, n = dx + dy, 0
        while True:
            if not dash or (n // dash) % 2 == 0:
                self.dot(x0, y0, color)
            n += 1
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def area(self, values, vmax, color_fn=None, line_color=None):
        """Area chart over the full width; `values` are resampled to dot columns."""
        if not values:
            return
        top = vmax or max(values) or 1
        n = len(values)
        prev = None
        for x in range(self.w):
            v = values[min(n - 1, int(x * n / self.w))]
            hgt = max(0.0, min(1.0, v / top)) * self.h
            if v > 0 and hgt < 1:
                hgt = 1
            self.column(x, hgt, color_fn)
            if line_color is not None:
                y = max(0, int(hgt) - 1)
                if prev is not None:
                    self.line(x - 1, prev, x, y, line_color)
                prev = y

    def label(self, col, row, text, color):
        for i, ch in enumerate(text):
            self.text[(row, col + i)] = (ch, color)

    def vline_cells(self, col, ch, color):
        for row in range(self.rows):
            if (row, col) not in self.text and not self.bits[row][col]:
                self.text[(row, col)] = (ch, color)

    def render(self, scr, y, x, default=None, grid=None):
        for r in range(self.rows):
            for c in range(self.cols):
                if (r, c) in self.text:
                    ch, col = self.text[(r, c)]
                    scr.put(y + r, x + c, ch, col)
                    continue
                b = self.bits[r][c]
                if b:
                    scr.put(y + r, x + c, chr(BRAILLE + b), self.color[r][c] or default)
                elif grid is not None:
                    scr.put(y + r, x + c, grid[0] if (r % grid[1] == grid[1] - 1) else " ", grid[2])
