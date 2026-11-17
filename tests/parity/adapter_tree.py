"""Parity adapter for the tree under test (the working tree): the src/claudemon/ package.

It is the only harness code that knows the tree's internals. It changes as the App
changes (phase 5); review every change like code, because a wrong adapter can hide a
difference.
"""

import os
import sys

# Paths inside the tree, relative to its root.
CLI = "claudemon.py"                 # the command line, run as a script
DEMO = "tools/make_demo.py"          # the demo-home generator
TAP_SOURCE = "src/claudemon/tap/tap.py"   # the tap the installer copies


def load(root):
    """Make the tree importable and return the handles the driver uses."""
    sys.path.insert(0, os.path.join(root, "src"))
    from claudemon.sources import store
    from claudemon.tap import installer as install
    from claudemon.ui import app as tui
    from claudemon.ui import draw
    return dict(draw=draw, install=install, store=store, tui=tui)


class Adapter:
    def __init__(self, root):
        self.m = load(root)

    # store
    def new_store(self):
        st = self.m["store"].Store()
        st.start()
        return st

    def indexed(self, st):
        return bool(st.indexed)

    # app
    def set_ascii(self):
        draw = self.m["draw"]
        draw.set_ascii(draw.detect_ascii())

    def new_app(self, win, st, cfg):
        return self.m["tui"].App(win, st, cfg)

    def tick(self, app):
        app.tick(force=True)

    def go(self, app, page):
        app.go(page)

    def draw(self, app):
        app.draw()

    def on_key(self, app, key):
        return app.on_key(key)

    def save(self, app):
        app.save()

    def state(self, app):
        """What a user could see changed by a key: the page, the view and the open modal."""
        return {"page": app.pages[app.page].title, "mini": bool(app.mini), "modal": app.modal, "flash": app.flash}

    # installer
    def repair(self):
        return self.m["install"].repair()

    def installed(self):
        return self.m["install"].installed()
