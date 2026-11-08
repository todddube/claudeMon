#!/usr/bin/env python3
"""Render README screenshots of every page from synthetic demo data.

    utils/shots.py                    # every shot into ./screenshots
    utils/shots.py token-burn tasks   # only these

No display is needed. For each shot it regenerates the demo data (fresh
timestamps), runs claudeMon headless to capture its screen buffer, draws that
buffer as an HTML terminal window and screenshots it with headless Chrome.
Needs Google Chrome, Chromium or Edge (set CHROME to override) and macOS `sips`
for the final resize; Pillow (optional) shrinks the PNGs.
"""

import html
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "screenshots"
DEMO = Path(tempfile.gettempdir()) / "claudemon-demo"
FONT_PX = 17.2                    # Menlo: glyph height 1.164em = 20 px, so box-drawing lines join between rows
CELL_W, CELL_H = FONT_PX * 0.602, 20
DEFAULT_BG, DEFAULT_FG = (22, 22, 24), (214, 214, 214)

# name, page (see App.go), theme, tap installed, graph style, grid size, final width, ascii fallback
FULL, SMALL = ("150x46", 1900), ("110x32", 1300)
SHOTS = [(n, p, "claude", tap, "blocks") + FULL + (False,) for n, p, tap in (
    ("token-burn", "token", True), ("tasks", "tasks", True), ("context", "context", True),
    ("prompt-cache", "prompt cache", True), ("traffic", "traffic", True), ("models", "models", True),
    ("session-limit", "session", True), ("weekly-limit", "weekly", True), ("projects", "projects", True),
    ("inspect", "inspect:web shop", True), ("settings", "settings", True), ("manual", "manual", True),
    ("manual-tap", "manual:tap", False), ("first-run-prompt", "prompt", False), ("tap-needed", "session", False))]
SHOTS += [("graph-" + st, "traffic", "claude", True, st) + SMALL + (False,)
          for st in ("blocks", "braille", "dots", "line", "ascii")]
SHOTS += [("theme-" + th, "token", th, True, "blocks") + SMALL + (False,)
          for th in ("claude", "btop", "dracula", "nord", "gruvbox", "matrix", "amber", "c64", "synthwave", "mono")]
SHOTS += [("mini", "mini", "claude", True, "blocks", "74x14", 1000, False)]
SHOTS += [("ascii-fallback", "token", "claude", True, "blocks") + SMALL + (True,)]

ANSI16 = [(0, 0, 0), (205, 0, 0), (0, 205, 0), (205, 205, 0), (0, 0, 238), (205, 0, 205), (0, 205, 205), (229, 229, 229),
          (127, 127, 127), (255, 0, 0), (0, 255, 0), (255, 255, 0), (92, 92, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255)]
LEVELS = [0, 95, 135, 175, 215, 255]
BLOCKS_V = {"▁": 1, "▂": 2, "▃": 3, "▄": 4, "▅": 5, "▆": 6, "▇": 7, "█": 8}        # filled from the bottom
BLOCKS_H = {"▏": 1, "▎": 2, "▍": 3, "▌": 4, "▋": 5, "▊": 6, "▉": 7}               # filled from the left


def rgb(c, default):
    if c is None or c < 0:
        return default
    if c < 16:
        return ANSI16[c]
    if c < 232:
        c -= 16
        return LEVELS[c // 36], LEVELS[c // 6 % 6], LEVELS[c % 6]
    g = 8 + 10 * (c - 232)
    return g, g, g


def hexc(t):
    return "#%02x%02x%02x" % t


def find_chrome():
    for cand in (os.environ.get("CHROME"),
                 "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                 "/Applications/Chromium.app/Contents/MacOS/Chromium",
                 "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                 shutil.which("google-chrome"), shutil.which("chromium"), shutil.which("chromium-browser")):
        if cand and os.path.exists(cand):
            return cand
    sys.exit("No Chrome/Chromium/Edge found; set CHROME=/path/to/browser")


def cell_html(cell):
    ch, fg, bg, bold, ul = cell
    f, b = rgb(fg, DEFAULT_FG), rgb(bg, DEFAULT_BG)
    style = "color:%s;background-color:%s" % (hexc(f), hexc(b))
    if ch in BLOCKS_V:
        n = BLOCKS_V[ch]
        style = "background-color:%s" % hexc(b)
        style += ";background-image:linear-gradient(to top,%s %d%%,transparent %d%%)" % (hexc(f), n * 12.5, n * 12.5)
        ch = " "
    elif ch in BLOCKS_H:
        n = BLOCKS_H[ch]
        style = "background-color:%s" % hexc(b)
        style += ";background-image:linear-gradient(to right,%s %d%%,transparent %d%%)" % (hexc(f), n * 12.5, n * 12.5)
        ch = " "
    cls = "c" + (" b" if bold else "") + (" u" if ul else "")
    return '<i class="%s" style="%s">%s</i>' % (cls, style, html.escape(ch))


def build_html(grid, title):
    cols, rows = grid["cols"], grid["rows"]
    body = "".join('<div class="r">%s</div>' % "".join(cell_html(c) for c in row) for row in grid["cells"])
    margin, pad, bar = 30, 10, 32
    width = int(cols * CELL_W + 2 * pad)
    height = rows * CELL_H + bar + 2 * 6
    page_w, page_h = int(width + 2 * margin), int(height + 2 * margin)
    doc = """<!doctype html><meta charset="utf-8"><style>
html,body{margin:0;background:linear-gradient(135deg,#34495e,#1b1d2b 60%%,#3b2a4a)}
body{width:%dpx;height:%dpx;overflow:hidden}
.win{position:absolute;left:%dpx;top:%dpx;width:%dpx;border-radius:11px;overflow:hidden;background:rgb%s;
 box-shadow:0 22px 60px rgba(0,0,0,.55),0 0 0 1px rgba(255,255,255,.12)}
.bar{height:%dpx;background:linear-gradient(#3a3a3c,#2c2c2e);position:relative;color:#b9b9bd;
 font:13px -apple-system,Helvetica,sans-serif;line-height:%dpx;text-align:center}
.bar b{position:absolute;top:10px;width:12px;height:12px;border-radius:6px}
.term{padding:6px %dpx;font:%spx/%dpx Menlo,Monaco,'DejaVu Sans Mono',monospace;white-space:pre}
.r{height:%dpx;white-space:nowrap}
.c{display:inline-block;width:%.3fpx;height:%dpx;overflow:visible;vertical-align:top;font-style:normal}
.b{font-weight:700}.u{text-decoration:underline}
</style><div class="win"><div class="bar"><b style="left:14px;background:#ff5f57"></b><b style="left:34px;background:#febc2e"></b><b style="left:54px;background:#28c840"></b>%s</div>
<div class="term">%s</div></div>""" % (page_w, page_h, margin, margin, width, DEFAULT_BG, bar, bar, pad, FONT_PX, CELL_H, CELL_H,
                                        CELL_W, CELL_H, html.escape(title), body)
    return doc, page_w, page_h


def shot(chrome, name, page, theme, tap, style, size, final_width, ascii_mode, pid):
    env = dict(os.environ, CLAUDE_CONFIG_DIR=str(DEMO), CLAUDEMON_DEMO="1", CLAUDEMON_ASCII="1" if ascii_mode else "0")
    py = sys.executable
    subprocess.run([py, str(ROOT / "utils/make_demo.py"), str(DEMO), "--pid", str(pid)] + ([] if tap else ["--no-tap"]),
                   check=True, capture_output=True)
    if tap:
        subprocess.run([py, str(ROOT / "claudemon.py"), "install"], env=env, check=True, capture_output=True)
    run = subprocess.run([py, str(ROOT / "utils/grid.py"), size, theme, page, style], env=env, capture_output=True, text=True)
    if run.returncode:
        sys.exit("grid failed for %s:\n%s" % (name, run.stderr[-1500:]))
    doc, w, h = build_html(json.loads(run.stdout), "claudeMon  —  %s" % size.replace("x", "×"))
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "page.html"
        src.write_text(doc)
        png = OUT / (name + ".png")
        png.unlink(missing_ok=True)
        proc = subprocess.Popen([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                                 "--user-data-dir=" + str(Path(tmp) / "profile"), "--force-device-scale-factor=2",
                                 "--window-size=%d,%d" % (w, h), "--screenshot=" + str(png), src.as_uri()],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        last, deadline = -1, time.time() + 45
        while time.time() < deadline:             # headless Chrome can linger after writing the file
            time.sleep(.5)
            size = png.stat().st_size if png.exists() else 0
            if size and size == last:
                break
            last = size
        proc.terminate()
        subprocess.run(["pkill", "-f", str(Path(tmp) / "profile")], capture_output=True)   # our helpers only
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
        if not png.exists():
            sys.exit("Chrome produced no screenshot for " + name)
    if shutil.which("sips"):
        subprocess.run(["sips", "--resampleWidth", str(final_width), str(png)], check=True, capture_output=True)
    shrink(png)
    print("saved", png.relative_to(ROOT))


def shrink(png):
    """Quantize to 256 colours (terminal shots lose nothing visible): ~3x smaller."""
    try:
        from PIL import Image
    except ImportError:
        return
    Image.open(png).convert("RGB").quantize(256, dither=Image.Dither.FLOYDSTEINBERG).save(png, optimize=True)


def main():
    OUT.mkdir(exist_ok=True)
    want = set(sys.argv[1:])
    chrome = find_chrome()
    sleeper = subprocess.Popen(["sleep", "1800"])      # a live pid to register the demo sessions under
    try:
        for name, *spec in SHOTS:
            if not want or name in want:
                shot(chrome, name, *spec, sleeper.pid)
    finally:
        sleeper.kill()
        shutil.rmtree(DEMO, ignore_errors=True)


if __name__ == "__main__":
    main()
