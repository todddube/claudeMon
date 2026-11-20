# claudeMon

**A task manager for Claude Code, in your terminal.** See every Claude Code session on your
machine at a glance: token burn, context, prompt cache, models and effort, subagents,
background tasks, and when you will hit your session or weekly limit.

Python standard library only. Reads local files only. Uses no tokens.

![Token burn](screenshots/token-burn.png)

Inspired by [Himamushi](docs/SPEC.md#1-what-himamushi-is), a web dashboard posted to r/ClaudeCode.
claudeMon takes the same idea into a btop-style terminal UI and adds a live task tree,
re-read loop detection, honest limit forecasts and a built-in manual.

## Install

### Homebrew

```sh
brew tap todddube/claudemon https://github.com/todddube/claudeMon
brew install --HEAD todddube/claudemon/claudemon
claudemon install
```

- Run `claudemon install` after installing: it adds the tap (see below) to Claude Code.
- Run `claudemon uninstall` before `brew uninstall`, so your status line is restored first.
- Upgrade with `brew upgrade --fetch-HEAD claudemon`.

The short form, `brew tap todddube/claudemon`, comes later.

### uv

Install it as a command with [uv](https://docs.astral.sh/uv/), from a clone or straight from GitHub:

```sh
uv tool install .                                            # from a clone
uv tool install git+https://github.com/todddube/claudeMon    # or without one
```

### A clone

```sh
git clone https://github.com/todddube/claudeMon.git
cd claudeMon
./claudemon.py
```

No dependencies and no build step: standard library only. The root `claudemon.py` runs the package in
`src/claudemon/` straight from the clone, on the stock `/usr/bin/python3` (3.9). Put it on your PATH with
`ln -s "$PWD/claudemon.py" ~/.local/bin/claudemon`. From a clone you can also run `uv run claudemon` or
`python3 -m claudemon` (from the clone's folder).

### Claude Code plugin

This repo is also a Claude Code plugin. It adds a `/claudemon` command that opens claudeMon in its own window.
Install it once, for every project, from a terminal:

```sh
claude plugin marketplace add todddube/claudeMon
claude plugin install claudemon@claudemon --scope user
```

Or, inside a Claude Code session, run `/plugin marketplace add todddube/claudeMon` and then
`/plugin install claudemon@claudemon`. Restart Claude Code, then type `/claudemon` in any session:

```text
/claudemon                # open claudeMon in a new window
/claudemon --mini         # the mini view
/claudemon -t dracula -p tasks
```

It takes the same flags as `claudemon` (see [Run](#run)). The plugin runs claudeMon from its own copy, so
you don't need Homebrew, uv or a clone. With only the plugin installed you have no `claudemon` command to
install the tap from, so do it in the app: open `/claudemon`, go to Settings and press `I` twice (see
[the tap](#-install-the-tap-for-limits-and-alerts)).

| To | Run |
|---|---|
| Update | `claude plugin marketplace update claudemon`, then `claude plugin update claudemon@claudemon`, then restart Claude Code |
| Remove | `claude plugin uninstall claudemon@claudemon`, then `claude plugin marketplace remove claudemon` |

Remove the tap first (Settings, `U` twice) if you installed it and are removing claudeMon entirely.

## Run

The examples use `claudemon`, the command from Homebrew, uv or the symlink. From a clone, run
`./claudemon.py` instead; it takes the same arguments.

```sh
claudemon                 # in this terminal (150×40 or larger is best)
claudemon --window        # in its own window titled "claudeMon" (Terminal, iTerm or Ghostty; macOS only)
claudemon --mini          # start in the mini view (z switches between mini and full)
claudemon -t dracula      # pick a theme (t cycles, b cycles graph styles)
claudemon -p tasks        # start on a page (name or number)
```

Inside Claude Code, with the [plugin](#claude-code-plugin) installed, `/claudemon` does the same as
`claudemon --window` and takes the same flags (`/claudemon --mini`).

**Requirements:** Python 3.9 or newer (macOS's `/usr/bin/python3` from the Xcode command line tools works;
tested on 3.9 and 3.13), a 256-colour terminal and, ideally, a UTF-8 locale (the default in Terminal, iTerm
and Ghostty). Without one (a C locale, the Linux console, `TERM=dumb`) claudeMon switches to plain-ASCII
drawing by itself; force it with `--ascii` or `CLAUDEMON_ASCII=1`, or turn it off with `CLAUDEMON_ASCII=0`.
macOS and Linux are both tested (Ubuntu in WSL2, and CI's ubuntu-latest); `--window` works on macOS only.
If macOS asks to install the command line tools the first time you run it, accept, then run it again.

`--window` drives Terminal, iTerm or Ghostty through AppleScript, so macOS may ask once to let your
terminal control it (System Settings > Privacy & Security > Automation). If you decline, just run
`claudemon` directly.

## ⚡ Install the tap for limits and alerts

Claude Code reports your account limits only through its status line. The **tap** records each
status-line refresh. Without it, the limit forecasts, per-session cost, exact context window size
and reliable "Needs you" alerts stay empty; everything else works already.

On first launch claudeMon asks whether to install it (or skip until later):

![First-run prompt](screenshots/first-run-prompt.png)

If the tap is off you will see it everywhere: a yellow chip in the header and footer, `⚡ install
tap` in the sidebar, and a full callout on the pages that need it. Press **`I` twice** on any page,
or run `claudemon install`.

![Limit page without the tap](screenshots/tap-needed.png)

- Your status line keeps working: the tap passes its input straight through to your original command.
- The tap is copied to `~/.claude/claudemon/tap.py` and `settings.json` points there, so moving or
  deleting this folder never breaks your status line. Each launch refreshes the copy.
- `settings.json` is backed up to `~/.claude/claudemon/` before every change (the last 10 are kept).
  A symlinked `settings.json` (dotfile managers) stays a symlink, and its permissions are kept.
- `claudemon uninstall` (or `U` `U` on Settings) restores your original status line and removes the hook.
- If the Python it was installed with disappears, the next launch re-points the tap at a working one.
- To remove it by hand (for example after deleting this folder): in `~/.claude/settings.json`, set
  `statusLine.command` back to the quoted command after `--` (or delete `statusLine` if there is none),
  and delete the Notification hook whose command ends in `# claudemon`.

The manual explains it in full (`m`, chapter "The tap"):

![Manual: the tap](screenshots/manual-tap.png)

## The pages

Jump with `1`–`9`, `0` and `s`, or `←` `→`. Press **`m`** on any page for the manual chapter about it.

### Mini view: the essentials in a small window

Press **`z`** on any page (or start with `--mini`). claudeMon shrinks its window to fit: both limits
with their forecast, the overall burn and cache, and one line per live session with its state, model
and effort, context, tokens per minute and the tool it is running. The window grows and shrinks as
sessions come and go. Press `z` again, `⏎` (Inspect) or a page key and it returns to its full size.
Resizing works in Terminal and iTerm; in other terminals, tmux or full screen the size is left alone.
The whole window is resized, so run it in a window of its own (`--window --mini`) rather than as one tab of
several. `CLAUDEMON_RESIZE=0` turns resizing off; `CLAUDEMON_RESIZE=1` forces it in another terminal.

![Mini view](screenshots/mini.png)

### Tasks: everything Claude is doing right now

A live tree of sessions, the tool each one is running, subagents (with their own model and effort),
background shells and their results, queued prompts, daemon jobs and scheduled tasks. Select a row
for details, including a live tail of a background task's output. `⏎` opens the session in Inspect.

![Tasks](screenshots/tasks.png)

### Session and weekly limits

Observed usage, a projection with best and worst cases, and the hatched stretch between "full" and
the reset. Usage that appears while this machine was silent (phone, web, another computer) is
shaded and labelled **unattributed**, and is left out of the burn rate, so a fresh session never
inherits someone else's burst. Every forecast says how long ago it was last observed.

![Session limit](screenshots/session-limit.png)
![Weekly limit](screenshots/weekly-limit.png)

### Prompt cache

Hit ratio, cache writes, and for each session when its cache goes cold and what it would cost to
rebuild. Reply before the timer runs out.

![Prompt cache](screenshots/prompt-cache.png)

### Models, context, traffic

Which models and effort levels are burning output (and which sessions use them), how full every
context window is, and tokens in, out and cached per minute. Spotting `xhigh` on a job that needs
`medium` is the cheapest win there is.

![Models](screenshots/models.png)
![Context](screenshots/context.png)
![Traffic](screenshots/traffic.png)

### Projects and Inspect

Each project's share of your weekly usage, and a deep look at one session: tools, subagents and
**Loop watch**, which flags files read three or more times with no edit in between (an agent
going in circles). `claudemon loops` prints the same report in a shell.

![Projects](screenshots/projects.png)
![Inspect](screenshots/inspect.png)

### Manual and settings

![Manual](screenshots/manual.png)
![Settings](screenshots/settings.png)

## Graph styles

Press **`b`** to cycle how every graph is drawn, from the big charts to the sidebar sparklines. Settings
shows all five side by side on the same data, and your choice is remembered.

| Style | Look |
|---|---|
| `blocks` | solid `▁▂▃▄▅▆▇█` columns (the default) |
| `braille` | fine 2×4 dot area, the most detail per cell |
| `dots` | stippled `·:░▒` shading, lighter and softer |
| `line` | a thin braille trace with no fill, like an oscilloscope |
| `ascii` | plain `.-=#`, for any terminal |

![Graph styles on Settings](screenshots/settings.png)

The same Traffic page in each style:

| | |
|---|---|
| ![blocks](screenshots/graph-blocks.png) | ![braille](screenshots/graph-braille.png) |
| ![dots](screenshots/graph-dots.png) | ![line](screenshots/graph-line.png) |
| ![ascii](screenshots/graph-ascii.png) | |

Without a UTF-8 locale (or with `--ascii`) *everything*, borders and icons too, is drawn in plain ASCII:

![ASCII fallback](screenshots/ascii-fallback.png)

## Themes

Ten themes. Press `t` to cycle, or pick one on Settings. Every theme re-colours the borders, the
gradient gauges and the per-series chart colours.

| | |
|---|---|
| ![claude](screenshots/theme-claude.png) | ![btop](screenshots/theme-btop.png) |
| ![dracula](screenshots/theme-dracula.png) | ![nord](screenshots/theme-nord.png) |
| ![gruvbox](screenshots/theme-gruvbox.png) | ![matrix](screenshots/theme-matrix.png) |
| ![amber](screenshots/theme-amber.png) | ![c64](screenshots/theme-c64.png) |
| ![synthwave](screenshots/theme-synthwave.png) | ![mono](screenshots/theme-mono.png) |

## Keys

| Key | |
|---|---|
| `1`–`9` `0` `s` | jump to a page |
| `←` `→` Tab | previous / next page |
| `↑` `↓` `j` `k` | select a session or row |
| `⏎` | inspect the selected session |
| `g` / `G` | graph range 5m · 15m · 1h · 6h · 24h |
| `o` · `e` · `a` | overall view · model·effort split · include finished sessions |
| `t` · `b` · `u` | theme · graph style (blocks, braille, dots, line, ascii) · update interval 1/2/5/10 s |
| `I` `I` · `U` `U` | install the tap · remove it (on Settings) |
| `m` · `?` · `q` | manual · key help · quit |

## Other commands

```sh
claudemon snapshot     # one-shot text summary of live sessions and limits
claudemon loops        # files re-read 3+ times with no edit, per session
claudemon install      # add the tap          claudemon uninstall   # remove it
```

## Layout

| Path | |
|---|---|
| `claudemon.py` | runs claudeMon from a clone (a small wrapper around `src/claudemon/`) |
| `tap.py` | a shim for installs from before the tap was copied to `~/.claude/claudemon/`; removed in a later release |
| `src/claudemon/` `cli.py` `commands.py` `window.py` | the command line, the one-shot subcommands, the `--window` launcher |
| `src/claudemon/core/` | locations, preferences, formatters, which Python the tap and new windows use |
| `src/claudemon/sources/` | sessions, transcript parsing, limit forecasting, the process snapshot |
| `src/claudemon/tap/` | the status-line tap (standalone) and its reversible installer |
| `src/claudemon/ui/` | the interface: the app loop, one module per page in `pages/`, the mini view and modals, drawing primitives, colour themes, the manual text |
| `pyproject.toml` `uv.lock` | packaging and developer tooling: uv dependency groups, ruff and pytest settings |
| `Formula/` | the Homebrew formula, `claudemon.rb` |
| `.claude-plugin/` `commands/` | the Claude Code plugin: its manifest, the marketplace that lists it, and the `/claudemon` command |
| `docs/` | [SPEC](docs/SPEC.md), [ARCHITECTURE](docs/ARCHITECTURE.md), [RELEASING](docs/RELEASING.md) and the review notes |
| `tests/` | the test suite, its shared helpers in `tests/support.py`, and the parity harness in `tests/parity/` |
| `tools/` | demo data generator, the screenshot pipeline and the formula check ([README](tools/README.md)) |

See [docs/SPEC.md](docs/SPEC.md) for the analysis of Himamushi, the data sources and the design, and
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how to add a page, subcommand or data source.

## Privacy

claudeMon reads `~/.claude` (transcripts, the live session registry, jobs, scheduled tasks) and the
process list, and writes to `~/.claude/claudemon/` (created private to your user). Installing the
tap also edits `~/.claude/settings.json`, with a backup first. Nothing leaves your machine. The
screenshots above use synthetic demo data, never real sessions.

## Tests

```sh
python3 -m unittest -v     # from a clone, standard library only
uv run pytest              # everyday runner (uv installs pytest and ruff from the dev group)
uv run ruff check          # lint
```

About 15 seconds. Each file covers one area:

| File | What it checks |
|---|---|
| `test_smoke.py` | renders every page (Unicode and ASCII, plus a tiny terminal) from the demo data, and the CLI on an empty home |
| `test_install.py` | round-trips the tap install against throwaway config directories (odd `settings.json` shapes, symlinks, a checkout path with a space, older installs) |
| `test_units.py` | feeds malformed and real-shaped records to the parsers, the limit forecast, the process classifier and the TUI's key handling |
| `test_tap_python.py` | which Python the tap bakes, and how `--window` starts claudeMon again |
| `test_packaging.py` | every way of starting claudeMon reaches the one package in `src/`, the built wheel (with uv), and the Homebrew formula; the real brew run needs `CLAUDEMON_BREW_CHECK=1` |
| `test_boundaries.py` | the layers (data layers never import the interface or curses), the headless routes, and that pages read data only through Store methods |
| `test_naming.py` | the claudeMon and claudemon naming rule |
| `test_extension.py` | a page, a subcommand and a data source added through their registries |
| `test_pages_graphs.py`, `test_pages_interactive.py` | the chart pages and the pages with their own keys |
| `test_mini.py`, `test_modals.py` | the mini view, and the help, manual and first-launch overlays |

`tests/parity/harness.py` (`python3 tests/parity/harness.py`; see [tests/parity/README.md](tests/parity/README.md))
compares the screens and commands against a pinned earlier commit, for changes that must not alter behaviour.

CI runs the tests on macOS and Linux with Python 3.9 and 3.13, plus ruff, the wheel, the tap on the system
Python and Homebrew. [docs/RELEASING.md](docs/RELEASING.md) describes how a release is cut.

## Regenerating the screenshots

```sh
python3 tools/shots.py                 # all of them into ./screenshots
python3 tools/shots.py tasks manual    # just these
```

The pipeline needs no display and uses synthetic data; see [tools/README.md](tools/README.md) for how
it works, how to add a screenshot and how to try the demo data yourself.
