"""Rate-limit history and forecasting.

Claude Code only reports account limits through the status line, so every
observation comes from the tap (see tap.py) and lands in limits.jsonl. Gaps
matter: when the bar jumps after a long silence (phone, web, another
computer) the jump is recorded as *unattributed* and left out of the burn
rate, so a fresh local session does not inherit someone else's burst.
"""

import json
import os
import time
from datetime import datetime

from paths import LIMITS_LOG

WINDOWS = {
    "five_hour": dict(label="Session", span=5 * 3600, recent=3600, slice=900, unit=3600, unit_name="h"),
    "seven_day": dict(label="Weekly", span=7 * 86400, recent=86400, slice=6 * 3600, unit=86400, unit_name="day"),
}
GAP_S = 15 * 60          # longer than this without an observation = blind spot
GAP_MIN_JUMP = 1.0        # points: smaller rises after a silent gap (e.g. the first message of a day) are not blind spots
STALE_S = 15 * 60        # forecast is flagged stale after this long
KEEP_S = 8 * 86400       # observations older than this are dropped (the longest window is 7 days)
COMPACT_BYTES = 1 << 20  # compact limits.jsonl at startup once it is larger than this
SAME_WINDOW_S = 600      # resets values this close belong to the same limit window


def to_epoch(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value / 1000 if value > 1e12 else float(value)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


class Obs:
    __slots__ = ("ts", "pct", "resets", "session")

    def __init__(self, ts, pct, resets, session):
        self.ts, self.pct, self.resets, self.session = ts, pct, resets, session


class Forecast:
    def __init__(self):
        self.pct = None
        self.resets = None
        self.observed = None
        self.points = []          # [(ts, pct)] in the current period
        self.gaps = []            # [(t0, t1, jump_pct, local_tokens)]
        self.rate = None          # %/s from recent attributed observations
        self.worst = None
        self.best = None
        self.note = ""

    def eta(self, rate):
        if self.pct is None or not rate or rate <= 0:
            return None
        return (self.observed or time.time()) + (100 - self.pct) / rate

    @property
    def stale(self):
        return self.observed is not None and time.time() - self.observed > STALE_S


def _num(v):
    """A finite float from an int/float (not bool), else None."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    v = float(v)
    return v if v == v and abs(v) != float("inf") else None


def parse_row(rec):
    """[(window key, Obs)] from one limits.jsonl record; [] for anything malformed."""
    if not isinstance(rec, dict):
        return []
    ts = _num(rec.get("ts"))
    if ts is None:
        return []
    out = []
    for key in WINDOWS:
        w = rec.get(key)
        if not isinstance(w, dict):
            continue
        pct = w.get("pct")
        if isinstance(pct, str):
            try:
                pct = float(pct)
            except ValueError:
                continue
        pct = _num(pct)
        if pct is None:
            continue
        sid = rec.get("sid")
        out.append((key, Obs(ts, pct, to_epoch(w.get("resets")), sid if isinstance(sid, str) else None)))
    return out


def compact(path=LIMITS_LOG, now=None, keep_s=KEEP_S, min_bytes=COMPACT_BYTES):
    """Drop rows older than keep_s once the log is larger than min_bytes. Never raises."""
    now = now or time.time()
    try:
        if os.path.getsize(path) <= min_bytes:
            return False
        with open(path, "rb") as fh:
            data = fh.read()
        lines = data.splitlines(True)
        keep = []
        for raw in lines:
            try:
                rec = json.loads(raw)
            except ValueError:
                continue
            ts = _num(rec.get("ts")) if isinstance(rec, dict) else None
            if ts is not None and now - ts <= keep_s and raw.endswith(b"\n"):
                keep.append(raw)
        if len(keep) == len(lines):
            return False                      # nothing to drop: leave the file alone
        tmp = "%s.%d.tmp" % (path, os.getpid())
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.writelines(keep)
                with open(path, "rb") as cur:     # rows the tap appended while we worked
                    cur.seek(len(data))
                    fh.write(cur.read())
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return True
    except (OSError, ValueError):
        return False


class LimitLog:
    def __init__(self, path=LIMITS_LOG):
        self.path = path
        self._reset()

    def _reset(self):
        self.offset = 0
        self.obs = {k: [] for k in WINDOWS}
        self.plan = ""

    def refresh(self):
        try:
            size = os.path.getsize(self.path)
        except OSError:
            return
        if size < self.offset:                # rewritten (compacted or truncated): start over
            self._reset()
        if size == self.offset:
            return
        try:
            with open(self.path, "rb") as fh:
                fh.seek(self.offset)
                data = fh.read()
        except OSError:
            return
        end = data.rfind(b"\n") + 1
        self.offset += end
        for raw in data[:end].splitlines():
            try:
                rec = json.loads(raw)
            except ValueError:
                continue
            for key, o in parse_row(rec):
                self.obs[key].append(o)
        cutoff = time.time() - KEEP_S
        for key, obs in self.obs.items():
            if obs and obs[0].ts < cutoff:
                self.obs[key] = [o for o in obs if o.ts >= cutoff]

    def forecast(self, key, local_tokens_between=None):
        """Forecast one window. `local_tokens_between(t0, t1)` lets gaps be
        checked against what local sessions actually spent in that time."""
        cfg = WINDOWS[key]
        f = Forecast()
        obs = self.obs[key]
        if not obs:
            f.note = "no data yet: install the status-line tap"
            return f
        # The current window is the newest one any session reported (the last row
        # may come from an idle session still showing the previous window).
        newest = max(obs, key=lambda o: o.ts)
        resets = max((o.resets for o in obs if o.resets), default=None)
        start = (resets - cfg["span"]) if resets else newest.ts - cfg["span"]
        period = sorted((o for o in obs if o.ts >= start
                         and (not resets or not o.resets or abs(o.resets - resets) < SAME_WINDOW_S)),
                        key=lambda o: o.ts)
        # Usage never falls within a window, so a lower reading is stale (another
        # session re-rendering an old value): keep the running maximum only.
        # Without a reset time a drop may be a real reset, so nothing is filtered then.
        if resets:
            mono, peak = [], None
            for o in period:
                if peak is None or o.pct >= peak:
                    mono.append(o)
                    peak = o.pct
            period = mono
        period = period or [newest]
        last = period[-1]
        f.pct, f.resets, f.observed = last.pct, resets or last.resets, last.ts
        f.points = [(o.ts, o.pct) for o in period]

        # split into attributed intervals and blind-spot jumps
        intervals = []
        for a, b in zip(period, period[1:]):
            dt, dp = b.ts - a.ts, b.pct - a.pct
            if dt <= 0:
                continue
            if dt > GAP_S and dp >= GAP_MIN_JUMP:
                local = local_tokens_between(a.ts, b.ts) if local_tokens_between else None
                f.gaps.append((a.ts, b.ts, dp, local))
                continue
            intervals.append((a.ts, b.ts, max(0.0, dp)))

        now = last.ts
        f.rate = rate_between(intervals, now - cfg["recent"], now)
        f.best = rate_between(intervals, start, now)
        slices = []
        t = start
        while t < now:
            r = rate_between(intervals, t, t + cfg["slice"])
            if r is not None:
                slices.append(r)
            t += cfg["slice"]
        f.worst = max(slices) if slices else f.rate
        if f.rate is None:
            f.rate = f.best
        if len(period) < 3:
            f.note = "insufficient recent data"
        elif f.stale:
            f.note = "stale: no observation in %d min" % ((time.time() - f.observed) // 60)
        return f


def rate_between(intervals, t0w, t1w):
    """Average %/s over [t0w, t1w], counting only attributed intervals."""
    span = used = 0.0
    for t0, t1, dp in intervals:
        lo, hi = max(t0, t0w), min(t1, t1w)
        if hi > lo:
            span += hi - lo
            used += dp * (hi - lo) / (t1 - t0)
    return used / span if span > 300 else None
