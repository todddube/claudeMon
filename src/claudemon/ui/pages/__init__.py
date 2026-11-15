"""The pages, in sidebar order. Adding a page is one module plus one PAGES line.

Every function a page provides takes the App as its first argument, `ctx`:

  render(ctx, y, x, h, w)   draw the page into the rectangle right of the sidebar
  side(ctx)                 -> (spark values, line 1, line 2) for its sidebar entry; the App calls it
                            every tick and caches the result (pages never touch that cache)
  on_key(ctx, key, k)       optional: the page's own keys, tried before the global ones while the
                            page is showing; True when it handled the key
  tick(ctx)                 optional: per-tick work, run every tick on every page and in mini
  state()                   optional: a factory for page-only state, kept at ctx.page_state[id]

`key` is the key that opens the page (as today: 1-9, 0, s), `title` is shown in the sidebar and
saved as `page_name` in config.json, and `manual_topic` is the manual topic id that m opens.
Pages read data only through Store methods and change the page only through ctx.go_page().
"""


class Page:
    __slots__ = ("id", "title", "key", "render", "side", "on_key", "tick", "manual_topic", "state")

    def __init__(self, id, title, key, render, side, on_key=None, tick=None, manual_topic=None, state=None):
        self.id, self.title, self.key = id, title, key
        self.render, self.side, self.on_key, self.tick = render, side, on_key, tick
        self.manual_topic, self.state = manual_topic, state

    def __repr__(self):
        return "Page(%r, %r, %r)" % (self.id, self.title, self.key)


from claudemon.ui.pages import burn, cache, context, inspect, limits, models, projects, settings, tasks, traffic  # noqa: E402

PAGES = [
    burn.PAGE,
    tasks.PAGE,
    context.PAGE,
    cache.PAGE,
    traffic.PAGE,
    models.PAGE,
    limits.SESSION,
    limits.WEEKLY,
    projects.PAGE,
    inspect.PAGE,
    settings.PAGE,
]
