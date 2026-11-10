"""claudeMon's own preferences (theme, page, graph range, update interval).

The file is user-editable, so load() only promises a dict; the UI validates each value."""

import json
import os

from paths import STATE_DIR

CONFIG_FILE = STATE_DIR / "config.json"


def load():
    try:
        with open(CONFIG_FILE, "rb") as fh:
            cfg = json.loads(fh.read())
    except (OSError, ValueError):
        return {}
    return cfg if isinstance(cfg, dict) else {}


def save(cfg):
    tmp = CONFIG_FILE.with_name(".config.%d.tmp" % os.getpid())
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        text = json.dumps(cfg, indent=2, ensure_ascii=False)     # fails before any file exists
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, CONFIG_FILE)
    except (OSError, TypeError, ValueError):
        try:
            tmp.unlink()
        except OSError:
            pass
