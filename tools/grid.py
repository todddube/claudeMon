#!/usr/bin/env python3
"""Run claudeMon headless and print its screen as JSON (used by shots.py).

    CLAUDE_CONFIG_DIR=<home> CLAUDEMON_DEMO=1 tools/grid.py COLSxROWS THEME PAGE [STYLE]

Output: {"cols", "rows", "cells": [[[ch, fg, bg, bold, underline], ...] per row]}
where fg/bg are xterm-256 indices (-1 = terminal default).
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def main():
    size, theme, page = sys.argv[1], sys.argv[2], sys.argv[3]
    style = sys.argv[4] if len(sys.argv) > 4 else "blocks"
    cols, _, rows = size.partition("x")
    cols, rows = int(cols), int(rows)
    from claudemon.ui import draw
    from claudemon.ui import headless
    from claudemon.ui import app as tui
    from claudemon.sources.store import Store

    headless.install()

    store = Store()
    store.start()
    for _ in range(100):
        if store.index_status()[0]:
            break
        time.sleep(.1)
    draw.set_ascii(draw.detect_ascii())
    win = headless.FakeWin(rows, cols)
    app = tui.App(win, store, {"theme": theme, "graph": style, "tap_prompt_seen": True})
    app.tick(force=True)
    app.go(page)
    app.tick(force=True)
    app.draw()
    json.dump({"cols": cols, "rows": rows, "cells": win.dump()}, sys.stdout)


if __name__ == "__main__":
    main()
