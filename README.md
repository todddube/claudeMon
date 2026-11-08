# claudeMon

**A task manager for Claude Code, in your terminal.** See every Claude Code session on your
machine at a glance: token burn, context, prompt cache, models and effort, subagents,
background tasks, and when you will hit your session or weekly limit.

Python standard library only. Reads local files only. Uses no tokens.

![Token burn](screenshots/token-burn.png)

Inspired by [Himamushi](SPEC.md#1-what-himamushi-is), a web dashboard posted to r/ClaudeCode.
claudeMon takes the same idea into a btop-style terminal UI and adds a live task tree,
re-read loop detection, honest limit forecasts and a built-in manual.

## Install

```sh
git clone https://github.com/todddube/claudeMon.git
cd claudeMon
./claudemon.py
```

No dependencies and no build step.

## Run

```sh
./claudemon.py                 # in this terminal (150×40 or larger is best)
./claudemon.py --window        # in its own window titled "claudeMon" (Terminal, iTerm or Ghostty)
./claudemon.py -t dracula      # pick a theme
./claudemon.py -p tasks        # start on a page (name or number)
```

Put it on your PATH with `ln -s "$PWD/claudemon.py" ~/.local/bin/claudemon`.
**Requirements:** macOS with Python 3.9 or newer (the `/usr/bin/python3` that comes with the Xcode
command line tools works; tested on 3.9 and 3.13), a 256-colour terminal and, ideally, a UTF-8 locale (the
default in Terminal, iTerm and Ghostty). Without one (a C locale, the Linux console, `TERM=dumb`) claudeMon
switches to plain-ASCII drawing by itself; force it with `--ascii` or `CLAUDEMON_ASCII=1`, or turn it off with
`CLAUDEMON_ASCII=0`. Linux should work but is untested. If macOS asks to install
the command line tools the first time you run it, accept, then run it again.

`--window` drives Terminal, iTerm or Ghostty through AppleScript, so macOS may ask once to let your
terminal control it (System Settings > Privacy & Security > Automation). If you decline, just run
`./claudemon.py` directly.

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
- `settings.json` is backed up to `~/.claude/claudemon/` before every change.
- `claudemon uninstall` (or `U` `U` on Settings) restores it exactly.
- If you move this folder, or the Python it was installed with disappears, the next launch re-points the installed tap automatically.

The manual explains it in full (`m`, chapter "The tap"):

![Manual: the tap](screenshots/manual-tap.png)

## The pages

Jump with `1`–`9`, `0` and `s`, or `←` `→`. Press **`m`** on any page for the manual chapter about it.

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

## Themes

`claude`, `btop`, `dracula`, `nord`, `gruvbox`, `matrix`, `amber`, `c64`, `synthwave`, `mono`.
Press `t` to cycle, or pick one on Settings. `b` switches graphs between solid blocks and braille.

| | |
|---|---|
| ![btop](screenshots/theme-btop.png) | ![dracula](screenshots/theme-dracula.png) |
| ![c64](screenshots/theme-c64.png) | ![synthwave](screenshots/theme-synthwave.png) |
| ![matrix](screenshots/theme-matrix.png) | |

## Keys

| Key | |
|---|---|
| `1`–`9` `0` `s` | jump to a page |
| `←` `→` Tab | previous / next page |
| `↑` `↓` `j` `k` | select a session or row |
| `⏎` | inspect the selected session |
| `g` / `G` | graph range 5m · 15m · 1h · 6h · 24h |
| `o` · `e` · `a` | overall view · model·effort split · include finished sessions |
| `t` · `b` · `u` | theme · graph style · update interval 1/2/5/10 s |
| `I` `I` · `U` `U` | install the tap · remove it (on Settings) |
| `m` · `?` · `q` | manual · key help · quit |

## Other commands

```sh
claudemon snapshot     # one-shot text summary of live sessions and limits
claudemon loops        # files re-read 3+ times with no edit, per session
claudemon install      # add the tap          claudemon uninstall   # remove it
```

## Layout

| File | |
|---|---|
| `claudemon.py` | entry point and command line |
| `tui.py` `draw.py` `themes.py` | the interface, drawing primitives, colour themes |
| `store.py` `transcript.py` `limits.py` | sessions, transcript parsing, limit forecasting |
| `tasks.py` `procs.py` | the Tasks tree and the process snapshot |
| `tap.py` `install.py` | the status-line tap and its reversible installer |
| `manual.py` `launch.py` `config.py` `paths.py` | manual text, window launcher, preferences, locations |
| `tools/` | demo data generator and the screenshot renderer |

See [SPEC.md](SPEC.md) for the analysis of Himamushi, the data sources and the design.

## Privacy

claudeMon reads `~/.claude` (transcripts, the live session registry, jobs, scheduled tasks) and the
process list, and writes only to `~/.claude/claudemon/`. Nothing leaves your machine. The
screenshots above use synthetic demo data, never real sessions.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

Standard library only. They render every page (Unicode and ASCII, plus a tiny terminal) from the demo
data, round-trip the tap install and uninstall, and check the CLI on an empty home.

## Regenerating the screenshots

```sh
python3 tools/shots.py              # all of them into ./screenshots
python3 tools/shots.py tasks manual # just these
```

`tools/make_demo.py` writes a fake `~/.claude` (eight sessions, subagents, a background task, a
re-read loop, five days of history, and limits with a blind spot). `tools/shots.py` runs claudeMon
headless on it and renders the screen with headless Chrome, Chromium or Edge (set `CHROME` to
point at one), so no display is needed. To try the demo yourself:

```sh
python3 tools/make_demo.py /tmp/demo --pid $$ && CLAUDE_CONFIG_DIR=/tmp/demo CLAUDEMON_DEMO=1 ./claudemon.py
```

## License

[MIT](LICENSE). claudeMon is an independent project and is not affiliated with Anthropic or
with the author of Himamushi.
