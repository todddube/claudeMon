"""Number, duration and clock formatters shared by the TUI and the one-shot commands."""

import time
from datetime import datetime


def ftok(n):
    n = n or 0
    for div, suf in ((1e9, "G"), (1e6, "M"), (1e3, "k")):
        if abs(n) >= div:
            v = n / div
            return ("%.2f" % v if v < 10 else "%.1f" % v if v < 100 else "%.0f" % v) + suf
    return "%d" % n


def fdur(s):
    if s is None:
        return "—"
    s = int(max(0, s))
    if s >= 86400:
        return "%dd%02dh" % (s // 86400, s % 86400 // 3600)
    if s >= 3600:
        return "%dh%02dm" % (s // 3600, s % 3600 // 60)
    if s >= 60:
        return "%dm%02ds" % (s // 60, s % 60)
    return "%ds" % s


def fclock(ts, weekday=False):
    if not ts:
        return "—"
    d = datetime.fromtimestamp(ts)
    return d.strftime("%a %H:%M" if weekday or abs(ts - time.time()) > 20 * 3600 else "%H:%M")


def fdate(ts, weekly):
    d = datetime.fromtimestamp(ts)
    return d.strftime("%a %-d %b %H:%M") if weekly else d.strftime("%H:%M")


def fpct(f):
    return "—" if f is None else "%d%%" % round(f * 100)
