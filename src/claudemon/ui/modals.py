"""The screens that are not pages: the help overlay, the manual, the first-launch tap prompt
and the too-small guard."""

import curses
import textwrap

from claudemon.ui import manual
from claudemon.ui import widgets as W
from claudemon.ui.draw import clip


def too_small(ctx):
    h, w = ctx.scr.size
    return h < 16 or w < 70


def draw_help(ctx, h, w):
    lines = [
        "claudeMon — a task manager for Claude Code",
        "",
        "1-9 0 s    jump to a page          ← → / Tab  previous / next page",
        "↑ ↓  j k   select a session        ⏎          inspect the selected session",
        "g / G      graph range 5m…24h      o          overall vs per-session (burn)",
        "e          model · effort split    a          include finished sessions",
        "t          next theme              u          update interval 1/2/5/10 s",
        "b          graph style: blocks · braille · dots · line · ascii",
        "r          refresh now             q / Esc    quit",
        "z          mini view: a small window with limits and sessions (z again restores the size)",
        "",
        "m          manual                  I I        install the tap (U U on Settings removes it)",
        "",
        "⚡ Limits, cost and alerts need the tap: press I twice, or run `claudemon install`.",
        "Everything else is read from ~/.claude transcripts. No tokens are used.",
    ]
    bw = min(w - 4, max(len(ln) for ln in lines) + 6)
    bh = len(lines) + 4
    y, x = (h - bh) // 2, (w - bw) // 2
    ctx.scr.fill(y, x, bh, bw, ctx.T("hl_bg"))
    ctx.scr.box(y, x, bh, bw, "Help", focus=True)
    for i, ln in enumerate(lines):
        ctx.scr.put(y + 2 + i, x + 3, ln, ctx.T("title") if i == 0 else ctx.T("fg"), ctx.T("hl_bg"))


def key_prompt(ctx, key, k):
    if too_small(ctx):                      # the prompt is not on screen, so no key may answer it
        return k not in ("q", "Q", "\x1b")
    if k in ("i", "I", "\n", "\r") or key == curses.KEY_ENTER:
        ctx.do_install()
    else:
        ctx.flash = "tap skipped: press I any time to install it"
    ctx.modal = None
    return True


def key_manual(ctx, key, k):
    n = len(manual.TOPICS)
    if k in ("q", "Q", "m", "M", "\x1b", "?"):
        ctx.modal = None
    elif key in (curses.KEY_DOWN, curses.KEY_RIGHT) or k in ("j", "l", "\t"):
        ctx.man_i, ctx.man_scroll = (ctx.man_i + 1) % n, 0
    elif key in (curses.KEY_UP, curses.KEY_LEFT, curses.KEY_BTAB) or k in ("k", "h"):
        ctx.man_i, ctx.man_scroll = (ctx.man_i - 1) % n, 0
    elif key == curses.KEY_NPAGE or k == " ":
        ctx.man_scroll += 8
    elif key == curses.KEY_PPAGE:
        ctx.man_scroll = max(0, ctx.man_scroll - 8)
    elif k == "g":
        ctx.man_scroll = 0
    elif k == "I":
        if ctx.confirm("I", "⚡ press I again to install the tap (settings.json is backed up first)"):
            ctx.do_install()
    return True


def manual_lines(ctx, topic, width):
    out = []
    kw = min(28, max([len(e[2:].partition(" | ")[0]) for e in topic["body"] if e.startswith("> ")] + [6]) + 2)
    for e in topic["body"]:
        if e.startswith("# "):
            if out:
                out.append(("blank", "", ""))
            out.append(("h", e[2:], ""))
        elif e.startswith("- "):
            for i, ln in enumerate(textwrap.wrap(e[2:], max(10, width - 2)) or [""]):
                out.append(("b", ("• " if i == 0 else "  ") + ln, ""))
        elif e.startswith("! "):
            out.append(("blank", "", ""))
            for ln in textwrap.wrap(e[2:], max(10, width - 4)):
                out.append(("c", " " + ln.ljust(width - 2), ""))
            out.append(("blank", "", ""))
        elif e.startswith("> "):
            k, _, t = e[2:].partition(" | ")
            for i, ln in enumerate(textwrap.wrap(t, max(10, width - kw - 2)) or [""]):
                out.append(("k", k if i == 0 else "", ln, kw))
        elif e == "":
            out.append(("blank", "", ""))
        else:
            if out and out[-1][0] not in ("blank", "h"):
                out.append(("blank", "", ""))
            for ln in textwrap.wrap(e, max(10, width)):
                out.append(("p", ln, ""))
    return out


def draw_manual(ctx, h, w):
    scr = ctx.scr
    bw, bh = w, h - 2
    x0, y0 = 0, 1
    scr.fill(y0, x0, bh, bw, ctx.T("hl_bg"))
    scr.box(y0, x0, bh, bw, "Manual", "m / Esc close", focus=True)
    lw = 24
    for i, t in enumerate(manual.TOPICS):
        ry = y0 + 2 + i
        if ry >= y0 + bh - 4:
            break
        cur = i == ctx.man_i
        tap = t["id"] == "tap"
        role = "warn" if tap else ("title" if cur else "fg")
        if cur:
            scr.put(ry, x0 + 1, "▌", ctx.T("accent"), ctx.T("hl_bg"))
        scr.put(ry, x0 + 3, clip(t["title"], lw - 4), ctx.T(role), ctx.T("hl_bg"), curses.A_BOLD if cur or tap else 0)
    if not ctx.tap_ok:
        W.chip(ctx, y0 + bh - 3, x0 + 2, " ⚡ I  Install tap ", "warn")
    else:
        scr.put(y0 + bh - 3, x0 + 2, "✓ tap installed", ctx.T("ok"), ctx.T("hl_bg"))
    for row in range(y0 + 1, y0 + bh - 1):
        scr.put(row, x0 + lw, "│", ctx.T("border"), ctx.T("hl_bg"))
    cx, cw = x0 + lw + 2, bw - lw - 4
    lines = manual_lines(ctx, manual.TOPICS[ctx.man_i], cw)
    inner = bh - 4
    ctx.man_scroll = max(0, min(ctx.man_scroll, max(0, len(lines) - inner)))
    for i, line in enumerate(lines[ctx.man_scroll:ctx.man_scroll + inner]):
        style, a, b = line[:3]
        ry = y0 + 2 + i
        bg = ctx.T("hl_bg")
        if style == "h":
            scr.put(ry, cx, a, ctx.T("title"), bg, curses.A_BOLD)
        elif style == "c":
            ctx.scr.put(ry, cx, a, ctx.T("bg") if ctx.T("bg") >= 0 else 16, ctx.T("warn"), curses.A_BOLD)
        elif style == "k":
            scr.put(ry, cx, a, ctx.T("accent"), bg, curses.A_BOLD)
            scr.put(ry, cx + (line[3] if len(line) > 3 else 18), b, ctx.T("fg"), bg)
        elif style == "b":
            scr.put(ry, cx, a, ctx.T("fg"), bg)
        elif style == "p":
            scr.put(ry, cx, a, ctx.T("fg"), bg)
    if len(lines) > inner:
        pct = int(100 * (ctx.man_scroll + inner) / len(lines))
        scr.put(y0 + bh - 2, x0 + bw - 12, "more %3d%%" % min(100, pct), ctx.T("dim"), ctx.T("hl_bg"))
    scr.put(y0 + bh - 2, cx, "↑↓ topic   PgUp/PgDn scroll   I install tap   Esc close", ctx.T("dim"), ctx.T("hl_bg"))


def draw_prompt(ctx, h, w):
    scr = ctx.scr
    bw = min(w - 6, 78)
    text = [
        ("p", "Limits, session cost and exact context size come from Claude Code’s status line, and "
              "permission prompts from its Notification hook. The claudeMon tap listens there. Without it "
              "those panels stay empty and ‘Needs you’ is a best guess; everything else works already."),
        ("p", ""),
        ("h", "What installing does"),
        ("b", "• wraps your status line: it still prints exactly as before"),
        ("b", "• adds a Notification hook that records permission prompts"),
        ("b", "• copies tap.py to ~/.claude/claudemon/, so moving this folder is safe"),
        ("b", "• backs up settings.json first; `claudemon uninstall` reverses everything"),
        ("p", ""),
    ]
    lines = []
    for style, t in text:
        for ln in (textwrap.wrap(t, bw - 8) or [""]):
            lines.append((style, ln))
    bh = len(lines) + 7
    y, x = max(1, (h - bh) // 2), (w - bw) // 2
    scr.fill(y, x, bh, bw, ctx.T("hl_bg"))
    scr.box(y, x, bh, bw, "⚡ Welcome to claudeMon: install the tap?", focus=True, title_fg=ctx.T("warn"))
    for i, (style, ln) in enumerate(lines):
        scr.put(y + 2 + i, x + 3, ln, ctx.T("title") if style == "h" else ctx.T("fg"), ctx.T("hl_bg"),
                curses.A_BOLD if style == "h" else 0)
    by = y + bh - 3
    cx = x + 3
    cx += W.chip(ctx, by, cx, "  I / ⏎  Install now  ", "ok") + 3
    cx += W.chip(ctx, by, cx, "  L  Later  ", "dim") + 3
    scr.put(by + 1, x + 3, "Later is fine: the ⚡ chip in the header stays until you install (I).", ctx.T("dim"), ctx.T("hl_bg"))


def draw_too_small(ctx, h, w):
    ctx.scr.put(0, 0, "claudeMon needs at least 70×16 (now %d×%d)" % (w, h), ctx.T("warn"))
    if ctx.modal == "prompt":
        ctx.scr.put(1, 0, "⚡ enlarge the window to answer the tap prompt (q quits)", ctx.T("dim"))


def draw(ctx, h, w):
    """Draw the open modal, if any, over the full view."""
    if ctx.modal == "help":
        draw_help(ctx, h, w)
    elif ctx.modal == "manual":
        draw_manual(ctx, h, w)
    elif ctx.modal == "prompt":
        draw_prompt(ctx, h, w)


def on_key(ctx, key, k):
    """Keys while a modal is open: the modal takes every key. None when no modal is open."""
    if ctx.modal == "prompt":
        return key_prompt(ctx, key, k)
    if ctx.modal == "manual":
        return key_manual(ctx, key, k)
    if ctx.modal == "help":
        ctx.modal = None
        return True
    return None
