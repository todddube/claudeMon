"""claudeMon's own preferences (theme, page, graph range, update interval)."""

import json

from paths import STATE_DIR

CONFIG_FILE = STATE_DIR / "config.json"


def load():
    try:
        with open(CONFIG_FILE) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save(cfg):
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w") as fh:
            json.dump(cfg, fh, indent=2)
    except OSError:
        pass
