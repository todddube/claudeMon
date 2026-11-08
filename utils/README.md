# utils: demo data and the screenshot pipeline

Everything here is for development. claudeMon itself never imports it.

| File | What it does |
|---|---|
| `make_demo.py` | Writes a fake `~/.claude` tree (sessions, subagents, jobs, limits) with timestamps relative to now |
| `grid.py` | Runs claudeMon headless on a fake curses and prints its screen as JSON |
| `requirements.txt` | Pillow, the one optional Python package (see the file for the non-pip tools) |
| `shots.py` | Renders the README screenshots: demo data, then grid, then HTML, then headless Chrome, then a resize and shrink |

## How a screenshot is made

```
make_demo.py ──► fake ~/.claude ──► grid.py ──► JSON cell grid ──► HTML terminal ──► headless Chrome ──► PNG
 (fresh times)    CLAUDE_CONFIG_DIR   fake curses   char, fg, bg,      Menlo, block glyphs   2x scale      sips resize
                  CLAUDEMON_DEMO=1                  bold, underline    as CSS gradients                    + 256 colours
```

1. **Demo data.** `make_demo.py` writes eight live sessions (one needs you, six working, one idle, one stuck
   in a re-read loop), three subagents, a running and a finished background task, a queued prompt, five
   days of history, daemon jobs, scheduled tasks and a limits log with a blind spot. Every shot regenerates
   it so "2 minutes ago" is true. Nothing real is ever read: `CLAUDE_CONFIG_DIR` redirects every path and
   `CLAUDEMON_DEMO=1` hides the real process list.
2. **Grid.** `grid.py` swaps `curses` for a recorder, builds the app at the requested size, theme, page and
   graph style, draws one frame and prints `{"cols", "rows", "cells": [[char, fg, bg, bold, underline]...]}`
   with xterm-256 colour numbers.
3. **HTML.** `shots.py` draws that grid as a macOS-style window. The block characters `▁▂▃▄▅▆▇█▏▎▍▌▋▊▉` are
   painted as CSS gradients instead of font glyphs so every cell fills its box exactly. The font is 17.2 px
   Menlo on 20 px rows, which makes the box-drawing lines join between rows.
4. **Chrome.** Headless Chrome, Chromium or Edge takes the picture at 2x. It is given a throwaway profile
   and stopped once the file stops growing, because it can linger after writing. Set `CHROME=/path` to pick one.
5. **Finish.** macOS `sips` resizes to the shot's final width, then Pillow (if installed) reduces the PNG to
   256 colours, roughly a third of the size with no visible loss.

No display is needed. It works while the screen is locked or asleep, unlike capturing a real Terminal window.

## Use

```sh
python3 utils/shots.py                    # every shot into ./screenshots (about a minute)
python3 utils/shots.py tasks theme-nord   # only these, by name
```

Requirements: Python 3, Chrome/Chromium/Edge, macOS `sips` (optional, for the resize) and Pillow (optional,
for the shrink). `pip install -r utils/requirements.txt` installs Pillow; the browser and `sips` are noted there.

### Try the demo data yourself

```sh
python3 utils/make_demo.py /tmp/demo --pid $$        # --no-tap leaves the tap uninstalled
CLAUDE_CONFIG_DIR=/tmp/demo CLAUDEMON_DEMO=1 ./claudemon.py
```

`--pid` registers the demo sessions under a process that is alive (here, your shell) so they count as live.
Run `./claudemon.py install` with the same environment first if you want the limit pages populated.

### Run one frame by hand

```sh
CLAUDE_CONFIG_DIR=/tmp/demo CLAUDEMON_DEMO=1 python3 utils/grid.py 120x34 claude traffic braille
# arguments: COLSxROWS THEME PAGE [STYLE]      PAGE is anything `claudemon -p` accepts
```

Set `CLAUDEMON_ASCII=1` to capture the plain-ASCII mode.

## Adding or changing a screenshot

Edit the lists near the top of `shots.py`. Each entry is

```
(name, page, theme, tap installed, graph style, grid size, final width, ascii mode)
```

`FULL` (150x46, 1900 px wide) is for whole-page shots and `SMALL` (110x32, 1300 px) for the galleries.
The name becomes `screenshots/<name>.png`; reference it from the main README. The shots now are:

| Shots | Page | Notes |
|---|---|---|
| `token-burn`, `tasks`, `context`, `prompt-cache`, `traffic`, `models`, `session-limit`, `weekly-limit`, `projects`, `inspect`, `settings`, `manual` | each page | full size |
| `manual-tap`, `first-run-prompt`, `tap-needed` | tap chapter, first-run prompt, a limit page without the tap | tap not installed |
| `graph-blocks`, `-braille`, `-dots`, `-line`, `-ascii` | Traffic | one per graph style |
| `theme-<name>` (10) | Token burn | one per theme |
| `mini` | the mini view (`z`) | 74x14, the size it fits itself to with the demo's eight sessions |
| `ascii-fallback` | Token burn | `CLAUDEMON_ASCII=1` |

## Gotchas

- **Fonts.** Menlo ships with macOS. On Linux Chrome falls back to DejaVu Sans Mono, whose metrics differ,
  so box lines may show hairline gaps. Adjust `FONT_PX` and `CELL_W` in `shots.py`.
- **Real tap.** Shots that need the tap run `claudemon install` against the demo home only. Your real
  `~/.claude/settings.json` is never touched.
- **Size.** About 5 MB for all of them. If a new shot makes the repo heavy, lower its final width.
- **Stale processes.** If a run is interrupted, a `sleep 1800` helper and a headless Chrome may be left
  behind; `pkill -f 'sleep 1800'` clears the first, and Chrome exits on its own.
