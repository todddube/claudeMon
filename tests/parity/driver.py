"""Headless driver for the parity harness: page grids, key scripts and installer calls.

    python frozen.py driver.py <adapter.py> <tree root> <jobs.json>

Prints one JSON object: {"results": [...]} with one entry per job. It knows nothing
about the tree except through the adapter. Run only by the harness, which sets
CLAUDE_CONFIG_DIR, HOME, the clock and the rest of the environment.

Unlike tools' grid.py, it fails (exit 3) if the store does not finish indexing in
time instead of drawing a half-indexed frame.
"""

import curses
import importlib.util
import json
import os
import sys
import time

INDEX_TIMEOUT_S = float(os.environ.get("PARITY_INDEX_TIMEOUT", 60))

# A fake curses: just enough for the drawing layer, recording colours instead of drawing.
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

    def nodelay(self, flag):
        pass

    def timeout(self, ms):
        pass

    def text(self):
        return ["".join(ch for ch, _ in row).rstrip() for row in self.g]

    def attrs(self):
        """Per row, run-length encoded "count:fg,bg,bold,underline" cells."""
        out = []
        for row in self.g:
            runs, last, n = [], None, 0
            for _, attr in row:
                fg, bg = PAIRS.get(attr >> 24, (-1, -1))
                cell = "%d,%d,%d,%d" % (fg, bg, bool(attr & curses.A_BOLD), bool(attr & curses.A_UNDERLINE))
                if cell == last:
                    n += 1
                else:
                    if last is not None:
                        runs.append("%d:%s" % (n, last))
                    last, n = cell, 1
            runs.append("%d:%s" % (n, last))
            out.append(" ".join(runs))
        return out


def load_adapter(path, root):
    spec = importlib.util.spec_from_file_location("parity_adapter", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.Adapter(root)


def size_of(text):
    cols, _, rows = text.partition("x")
    return int(rows), int(cols)


def key_of(k):
    return getattr(curses, k) if k.startswith("KEY_") else k


def config_text():
    path = os.path.join(os.environ["CLAUDE_CONFIG_DIR"], "claudemon", "config.json")
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


class Driver:
    def __init__(self, ad):
        self.ad = ad
        self._store = None

    def store(self):
        if self._store is None:
            st = self.ad.new_store()
            deadline = time.monotonic() + INDEX_TIMEOUT_S
            while not self.ad.indexed(st):
                if time.monotonic() > deadline:
                    sys.stderr.write("parity driver: the store did not finish indexing in %d s\n" % INDEX_TIMEOUT_S)
                    sys.exit(3)
                time.sleep(0.02)
            self._store = st
        return self._store

    def app(self, job):
        os.environ["CLAUDEMON_ASCII"] = "1" if job.get("ascii") else "0"
        self.ad.set_ascii()
        rows, cols = size_of(job.get("size", "120x36"))
        win = FakeWin(rows, cols)
        cfg = dict(job.get("cfg", {"tap_prompt_seen": True}))
        if "theme" in job:
            cfg["theme"] = job["theme"]
        if "style" in job:
            cfg["graph"] = job["style"]
        app = self.ad.new_app(win, self.store(), cfg)
        return app, win

    def grid(self, job):
        app, win = self.app(job)
        self.ad.tick(app)
        self.ad.go(app, job["page"])
        self.ad.tick(app)
        self.ad.draw(app)
        return {"text": win.text(), "attrs": win.attrs()}

    def keys(self, job):
        app, win = self.app(job)
        self.ad.tick(app)
        if job.get("go"):
            self.ad.go(app, job["go"])
        self.ad.draw(app)
        steps = [{"key": None, "state": self.ad.state(app), "screen": win.text(), "config": config_text()}]
        for k in job["keys"]:
            ret = self.ad.on_key(app, key_of(k))
            self.ad.draw(app)
            steps.append({"key": k, "ret": ret, "state": self.ad.state(app), "screen": win.text(),
                          "config": config_text()})
            if ret is False:
                break
        if job.get("save", True):
            self.ad.save(app)
            steps.append({"key": "<save>", "config": config_text()})
        return steps

    def repair(self, job):
        return {"message": self.ad.repair(), "installed": self.ad.installed()}

    def run(self, job):
        return getattr(self, job["kind"])(job)


def main():
    adapter_path, root, jobs_path = sys.argv[1:4]
    with open(jobs_path, encoding="utf-8") as fh:
        jobs = json.load(fh)
    d = Driver(load_adapter(adapter_path, root))
    results = [d.run(job) for job in jobs]
    json.dump({"results": results}, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
