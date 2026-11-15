# claudeMon architecture

A map of the code for a new contributor. For what the monitor shows and why, read [SPEC.md](SPEC.md).
For how the code got this shape, read [reorg-plan.md](reorg-plan.md).

## The layers

```
src/claudemon/
  core/       paths, config, fmt, runtime        shared plumbing, stdlib only
  sources/    transcripts, limits, procs, store  the data layer, one Store in front
  tap/        tap.py, installer.py               what Claude Code runs, and what installs it
  ui/         app, pages/, widgets, mini, ...    the curses interface
  cli.py  commands.py  window.py                 the command line, one-shot commands, --window
```

| Layer | Holds | May import |
|---|---|---|
| `core/` | Paths, `config.json`, number and time formatting, the Python the tap runs on | the standard library |
| `sources/` | Readers for transcripts, the limits log and the process table, and `Store` | `core/`, `sources/` |
| `tap/` | `tap.py` (the status-line tap and hook) and `installer.py` | `core/`; `tap.py` only the standard library |
| `ui/` | The App, the pages, the mini view, the modals, the manual | `core/`, `tap/installer`, `sources/` (an allow-list, below) |
| `cli.py`, `commands.py`, `window.py` | Argument parsing, the headless subcommands, the terminal launcher | everything; `ui` only for `themes` and, to run the TUI, `ui.app` |

`tests/test_boundaries.py` enforces these rules:

- `core/`, `sources/` and `tap/` never import `claudemon.ui` or `curses`.
- `tap/tap.py` imports only the standard library.
- `ui/__init__.py` and `ui/themes.py` import nothing, so `cli.py` can read the theme names for `--theme`
  without loading curses.
- The headless routes (`snapshot`, `loops`, `install`, `uninstall`, `--version`, `--window`) never load curses.
- `ui/` and `commands.py` read the Store only through its public methods (see "The Store").
- `ui/` imports from `claudemon.sources` only `Store` (the App), the state constants `IDLE`, `NEEDS_YOU`,
  `WORKING`, `DONE` and `LONG_TOOLS`, `short_model` and `weight` from `sources.store`, and `WINDOWS` from
  `sources.limits`.

Imports are absolute (`from claudemon.ui import widgets as W`), never relative.

## The three registries

Each extension point is an ordered list or dict that one module owns. `tests/test_extension.py` adds an
entry to each from test code that only appends, so the recipes below are tested, not just described.

| Add a | Touches |
|---|---|
| Page | One module in `ui/pages/` and one line in `ui/pages/__init__.py` |
| Subcommand | One function and one entry in `commands.py` |
| Data source | One module in `sources/` and one line in `sources/__init__.py` |

### Add a page

Write `src/claudemon/ui/pages/fleet.py`:

```python
"""Page f, Fleet: what it shows."""

from claudemon.ui.pages import Page


def render(ctx, y, x, h, w):
    ctx.scr.put(y + 1, x + 2, "%d sessions" % ctx.store.session_count(), ctx.T("fg"))


def side(ctx):
    return [], "%d sessions" % ctx.store.session_count(), ""


PAGE = Page("fleet", "Fleet", "f", render, side, manual_topic="Fleet")
```

Add `from claudemon.ui.pages import ... fleet ...` and a `fleet.PAGE` line to `PAGES`. The position in
the list is the position in the sidebar. Add a manual topic with the same id to `ui/manual.py`
(an unknown `manual_topic` opens the Welcome chapter). Use a key no global binding takes.

### Add a subcommand

In `commands.py`:

```python
def cmd_hello(args):
    print("hello")


COMMANDS = {
    ...
    "hello": cmd_hello,
}
```

`cli.py` builds its choices from `COMMANDS` when it runs, so `claudemon hello` and `--help` pick it up. The
function takes the parsed `argparse` namespace. A command that reads data builds a `Store` and calls its
public methods, as `cmd_snapshot` does.

### Add a data source

Write a class in `src/claudemon/sources/` with a `refresh()` method, then add one line:

```python
SOURCES = [
    ("procs", Processes, "first"),
    ("limits", LimitLog, "last"),
    ("probe", Probe, "last"),
]
```

`Store()` builds each entry as `store.<name>`. `Store.refresh()` calls `refresh()` on the `"first"` entries
before it reads the live registry and on the `"last"` entries after the transcripts, in list order within
a stage. A source whose `refresh()` raises is skipped, so one source never takes the Store down. Expose
what pages need as a public Store method; pages never reach `store.probe` directly.

## The page contract

`ui/pages/__init__.py` defines `Page` and the ordered `PAGES` list. Every function a page provides takes
the App as its first argument, `ctx`.

| Field | Meaning |
|---|---|
| `id` | Stable name; the key of `ctx.page_state` and `ctx.side_cache` |
| `title` | Shown in the sidebar and saved as `page_name` in `config.json`; frozen |
| `key` | The key that opens the page (1-9, 0, s); frozen |
| `render(ctx, y, x, h, w)` | Draw into the rectangle right of the sidebar |
| `side(ctx)` | `(spark values, line 1, line 2)` for the sidebar entry |
| `on_key(ctx, key, k)` | Optional. The page's own keys; True when it handled the key |
| `tick(ctx)` | Optional. Per-tick work, run on every page and in mini |
| `state()` | Optional. A factory for page-only state, kept at `ctx.page_state[id]` |
| `manual_topic` | The manual topic id that `m` opens |

The App owns navigation and the per-tick work:

- `App.on_key` routes a key in this order: the flash is cleared; the modal layer; `q`, `Q` and Esc quit;
  `z` toggles mini; in mini, the mini view takes the rest; the current page's `on_key`; then the global
  keys (page keys, arrows, Tab, `h` and `l`, selection, Enter, `g`, `u`, `t`, `b`, `o`, `e`, `a`, `r`,
  `m`, `?`, `I`).
- `App.tick` runs every interval: `store.refresh()`, both limit forecasts into `ctx.forecasts`, the tap
  check, `-p page:session` resolution, every page's `tick`, then every page's `side` into
  `ctx.side_cache`. Pages never write the cache; an exception in `side` becomes an "error" entry.
- `App.draw` draws the header, the sidebar, the current page's `render` (an exception shows
  "page error: ...") and the footer, then the modals. Below 70 columns by 16 rows it draws only the
  too-small guard.
- A page changes page only through `ctx.go_page(page_id, session=None)`. `App.go(start)` is the `-p` string
  parser (`mini`, `prompt`, `manual[:topic]`, a key, a number or a title prefix, then `:session name`).
- `o` (Token burn's overall view) and `e` (Models' effort split) are global keys and App state.

What a page may read from `ctx`: `scr`, `T(role)`, `store`, `span`, `span_i`, `style`, `interval`, `overall`,
`by_effort`, `show_all`, `forecasts`, `tap_ok`, `flash`, `theme_cursor`, `page_state`, `pages`, `page`,
`sel`, `sel_sid`, `mini`, `modal`, `man_i` and `man_scroll`. Methods: `session_list()`, `selected()`,
`move(d)`, `go_page()`, `index_of()`, `page_for_key()`, `confirm(key, msg)`, `do_install()`,
`not_reported(key)`. Shared drawing (charts, toggles, badges, chips, the tap callout) lives in
`ui/widgets.py`, and every non-ASCII glyph needs an entry in `draw.ASCII_MAP`.

## The Store

`sources/store.py` is the only way pages, the mini view, the modals and the commands read data. They call
its public methods and read attributes of the `Session` objects those return.

| Method | Returns |
|---|---|
| `live_sessions()` | Live sessions: Needs you, Working, Idle, Done, then newest |
| `recent_sessions(since)` | Sessions live or active since `since` |
| `calls(since, sessions=None)` | `(session, Call, agent or None)` for calls since `since` |
| `series(span, n, metric, ...)` | `n` buckets of `metric(call)` over the last `span` seconds |
| `totals(since, sessions=None)` | A `Usage` summed over those calls |
| `tokens_between(t0, t1)` | Total tokens of all calls in a range |
| `forecast(key)` | The limit forecast for `five_hour` or `seven_day` |
| `limit_samples()`, `session_count()`, `index_status()` | Counts and indexing progress |
| `proc(pid)`, `cli_procs()`, `desktop_procs()` | Process table views |
| `jobs()`, `scheduled()` | Daemon jobs and scheduled tasks |
| `start()`, `index()`, `refresh()`, `prune_state()` | Lifecycle, called by the App and the commands |

A test walks every file under `ui/` and `commands.py`: in `<x>.store.<name>` the name must be a public
method of `Store`, so adding a method needs no test edit and reaching into `store.sessions` or
`store.limits` fails. Add a query as a Store method first, then call it from the page.

## The tap

`tap/tap.py` is a standalone file that the installer copies to `~/.claude/claudemon/tap.py`. Claude Code
runs it as the status line and as the Notification hook, on the system Python (`core.runtime.tap_python()`
picks it), so it imports only the standard library and works on Python 3.9. Its bytes are frozen: existing
installs match on its docstring ("tap for claudeMon") and the `# claudemon` settings marker. It writes
`status/<sid>.json`, `status/<sid>.hook.json` and `limits.jsonl` for the Store to read. The root `tap.py`
is a shim for installs that predate the package layout.

## The headless route

`ui/headless.py` installs a curses colour stub and provides `FakeWin`, a grid of `(char, attr)` cells, so the
App draws without a terminal. Three things use it:

- `tools/grid.py COLSxROWS THEME PAGE [STYLE]` prints a screen as JSON.
- `tests/support.py` runs the App in a subprocess with a demo home built by `tools/make_demo.py`
  (`DemoHome`, `ui()`). A subprocess, because `install()` patches curses for the whole process and paths
  are read from `CLAUDE_CONFIG_DIR` at import.
- `tests/parity/` compares screens and outputs against a pinned commit.

Set `CLAUDE_CONFIG_DIR` and `HOME` to a temporary folder for any such run: every App start repairs the tap
entry in `settings.json`.

## Where state lives

| Path | Holds |
|---|---|
| `~/.claude/claudemon/config.json` | Preferences: `theme`, `page` (the index), `page_name` (the title, preferred on load), `span`, `interval`, `graph`, `mini`, `full_size`, `tap_prompt_seen` |
| `~/.claude/claudemon/tap.py` | The installed tap |
| `~/.claude/claudemon/status/` | Per-session status-line JSON and hook events |
| `~/.claude/claudemon/limits.jsonl` | The rate-limit observations the forecasts use |
| `~/.claude/claudemon/*.backup.json`, `settings.*.bak.json` | Backups the installer takes before it edits `settings.json` |

`core/paths.py` reads `CLAUDE_CONFIG_DIR` once, at import, and derives every path from it. All file names
here are frozen. Preferences other than `tap_prompt_seen` are saved when the App exits cleanly.

## A second data root

Not built. A future multi-device view would need a second place to read sessions from, for example a folder
synced from another machine. Most of the shape is already there:

- Paths are read at import from one `CLAUDE_CONFIG_DIR`, so a second root means paths that belong to a
  source, not module constants. That is the main change.
- The Store keys sessions by session id, so sessions from another root merge without a new structure, once
  ids are unique across machines.
- The new reader is a data source: one module and one `SOURCES` line, exposed through Store methods.

None of this exists today. The prerequisite for starting it is the path change, because every reader
currently takes its location from `core/paths.py`.
