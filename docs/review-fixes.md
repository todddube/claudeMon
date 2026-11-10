# Review fixes: change log

Fixes for the findings of three reviews of `main` @ `0da058b`:

- **A**: the repo audit workflow (`claudemon-repo-audit`, bugs #1–#15).
- **F1**: a second-opinion review of that audit (corrections, plus missed issues M1–M11).
- **F2**: a review of the critical paths: tap, installer, privacy and terminal handling (C1–C14).

Status key: **Fixed**, **Not a bug** (verified, no change), **Deferred** (deliberately left out of this change, with the reason).

## Testing

| Check | Result |
|---|---|
| `python3 -m unittest` (Python 3.9.6 and 3.13) | 73 tests pass (16 before). Plain discovery used to find 0 tests; `tests/__init__.py` fixes that. |
| New tests run against the original code (`0da058b`) | 39 of 47 fail, so they really cover the bugs. The other 8 guard behaviour that already worked (passthrough, exit codes, `parse_etime`). |
| Real data, sandbox config directory (transcripts and registry symlinked read-only, `settings.json` copied) | `snapshot` and `loops` work. Weekly burn rate 88 → 59 %/day, the correct figure for 38 → 40 % in about 50 min. Background tasks shown as running 21 → 3, with 20 shown as stopped. |
| Real process table | MCP servers 16 → 28: all 28 real ones found, and the two false positives (`zsh -c …`, `python -c …`) are gone. Desktop-hosted `claude` CLIs are now recognised, and the `disclaimer` wrapper is not mistaken for one. |
| Registry start-time check | All 14 live sessions pass; the largest gap is 2.8 s against a 120 s cutoff. |
| TUI in a pty, 150×46 | Page keys, Alt+x, `²`, mini toggling, Esc, Ctrl-C and SIGTERM all exit with status 0 and no traceback. Preferences are saved. Quitting from `--mini` restores 46×150, not the old 50×160. |
| Live tap | Ran under real Claude Code status-line refreshes, first with the old install's command and then after migration. |
| Migration in the sandbox | The first launch re-points an old install at `~/.claude/claudemon/tap.py` and adds the marker. The command renders through `sh`, and uninstall/install round-trip. |

`.github/workflows/tests.yml` runs compileall and the tests on macOS with Python 3.9 and 3.13.

## What changes on an existing install

On the next launch, `install.repair()` will rewrite `~/.claude/settings.json` once, with a backup first:

- The status line and hook move from the checkout's `tap.py` to `~/.claude/claudemon/tap.py`.
- `# claudemon` is appended to the status-line command.

After that the repo can be moved or deleted without breaking your status line.

---

## Installer, `install.py`

| Finding | Status | What changed |
|---|---|---|
| F2 C1 / F1 M1: a checkout path that needs quoting (a space, `~`) is never detected, so every install re-wraps, the backup is overwritten, and uninstall can't remove it | **Fixed** | Commands are recognised by parsing them (`shlex.split`: argv[1] is `tap.py`, argv[2] is `statusline`/`hook`), never by substring, and they are rebuilt from parts rather than edited with a regex. `unwrap()` peels any number of nested layers, so installs already broken this way are repaired by `install`/launch and fully reverted by `uninstall`. |
| F2 C2: a user's own `…/tap.py statusline` is hijacked by `repair()` and deleted by `uninstall` | **Fixed** | Every command we write ends with `# claudemon` (a shell comment). An unmarked command counts as ours only if its `tap.py` is claudeMon's: our installed copy, or a directory that contains `claudemon.py` or is named claudemon. |
| F2 C3: the status line depends on the checkout's path; moving or deleting the repo blanks it | **Fixed** | `install` copies `tap.py` to `~/.claude/claudemon/tap.py` and points `settings.json` there. Each launch refreshes the copy if it differs. Old installs are migrated on the next launch. The README documents a manual uninstall. |
| F2 C14: two checkouts fight over `settings.json` through `repair()` | **Fixed** | Both now point at the same installed copy, so `repair()` has nothing to flip. |
| A #11 / F2 C5: `_save` replaces a symlinked `settings.json` and resets 0600 to 0644 | **Fixed** | Writes go through `realpath`. The temp file is created next to the target, keeps its mode, and is fsync'd before the atomic replace. Indentation (tabs or n spaces) is kept. `ensure_ascii=False`, so `é` stays `é`. |
| F2 C6: uninstall restores a stale backup over edits made after install | **Fixed** | Uninstall takes the current `statusLine` object and swaps in the original embedded in the command, so later edits and new fields such as `padding` survive. The backup is used only when no original is embedded. |
| F2 C9: a non-UTF-8 locale writes mojibake into `settings.json` | **Fixed** | Every read and write of `settings.json`, the backups and `config.json` is explicitly UTF-8. |
| A #3 / F2 C10: odd shapes (`[]`, `null`, a string `statusLine`, `hooks: []` …) or a read-only directory raise, and `repair()` at startup is unguarded | **Fixed** | `_check_shape()` validates before any change, and `install`/`uninstall` return "unexpected shape; not touching it". `installed()` and `repair()` never raise. `PermissionError` and other `OSError`s become messages. The TUI also wraps install and uninstall. |
| F2 C13: backups collide within a second, are never pruned, and there's a lost-update race and no fsync | **Fixed** | Backups are named with `time_ns()`, written 0600, and pruned to the last 10. `_save` re-reads the file and refuses to write (`Conflict`) if it changed since it was read. fsync happens before the rename. Temp names are per-process. |
| State directory permissions | **Fixed** | `~/.claude/claudemon/` is set to 0700, and the tap creates its files 0600. |

## Tap, `tap.py`

| Finding | Status | What changed |
|---|---|---|
| F2 C7: `session_id` is used unsanitised as a filename; `../../settings` overwrote `settings.json` | **Fixed** | The id must match `[A-Za-z0-9_-]{1,128}` in both the status-line and hook paths, or nothing is written. |
| F2 C8: a hanging original gives a 10 s blank, drops partial output and orphans grandchildren | **Fixed** | After recording, the tap `exec`s the original (`/bin/sh -c`) with the same stdin bytes, taken from an unlinked temp file. Output streams straight through; the exit code, signals and Claude Code's own timeout behave exactly as without the tap, and there is no timeout or buffering of ours. If exec fails, a fallback runs the original in its own process group, kills the whole group on timeout, and still prints any partial output. |
| A #10 / F1 2.5 (raised to Medium): stale percentages from idle sessions make the forecast flap and inflate the rate | **Fixed** (also in `limits.py`) | The tap keeps a per-window peak in `tap_last.json`. Within the same reset window (±600 s), a reading below the peak is stale and is not logged. A new window is always logged. |
| F2 C12: two sessions with different percentages defeat the 60 s throttle | **Fixed** | Same mechanism: the lower, stale reading is dropped before the throttle check. |
| A command run without a shell would pass `# claudemon` to `tap.py` as arguments | **Fixed** | `main()` strips the trailing marker tokens. |
| Hook stdin read with the locale's encoding | **Fixed** | Reads bytes; a non-object payload is ignored. |

## Data layer

| Finding | Status | What changed |
|---|---|---|
| A #1: a record that is valid JSON but the wrong shape raises out of `Transcript._refresh`, killing the indexer ("loading" forever) or the TUI | **Fixed** | Non-object records are skipped, and each `_ingest` is wrapped (`bad_records` counts them). Typed accessors (`_str`, `_int`, `_dict`) keep odd values out of state, for example a string `input_tokens` that would crash a later sum. |
| A #2: `LimitLog.refresh` guards only `json.loads`; a bad row crashes every relaunch | **Fixed** | `parse_row()` validates each record: object type, finite numeric `ts` (a string `ts` used to crash `forecast` later), and numeric `pct`. `self.__init__()` is replaced by an explicit `_reset()`. |
| A #10 (forecast side) | **Fixed** | `forecast` picks the newest reported reset window, not the last row's, and keeps only the running maximum within it, so the displayed % never drops to a stale value and stale-to-fresh steps no longer count as burn. Test: a fresh session at +1 %/h plus an idle session stuck at 28 % now forecasts about 24 %/day (it was thousands). |
| F1 M2: background tasks stopped with `TaskStop` show as "running" forever | **Fixed** | A successful `TaskStop` (also `KillShell`/`KillBash`) marks its task `stopped` with an end time; a call with `is_error` is ignored. The Tasks page shows stopped tasks as neutral rather than failed. |
| A #6: data race; the indexer inserts into dicts the UI iterates | **Fixed** | Every reader iterates a snapshot (`list(...)`), including the paths F1 found in `draw_mini` and `_refresh_agents`. The subagent check-then-insert now happens under `Store.lock`. `Transcript._lock` is deliberately not taken by readers (F1 2.2: it would block the UI during a long parse). |
| F1 M7: a non-object `sessions/<pid>.json` crashes `Store.refresh` | **Fixed** | `read_json` returns only objects, `sessionId` must be a string, and each session's refresh is guarded on its own. |
| F1 M8: the indexer thread has no exception handler | **Fixed** | `Store.index()` (now public) guards each transcript and always ends with `indexed=True` in a `finally`. `claudemon.py` calls the public method. |
| A #8: pid reuse makes a stale registry entry look live | **Fixed** | Uses F1's safer option: `ps` runs first, and an entry is live only if `now - etime` is within 120 s of the registry's `startedAt`. With no process table (demo mode, `ps` failing) it falls back to the pid check, so demo mode and the tests are unaffected. |
| A #9 / F1 M9: a subagent is "finished" after 10 min of silence, even while blocked on a tool; `stoppedByUser` is ignored | **Fixed** | `stoppedByUser` counts as finished. A subagent waiting on a tool stays running for up to 2 h of silence; otherwise the 10-minute rule applies. |
| A #12: open/read after stat is outside a try; rewrites are detected by size only | **Fixed** | `OSError` returns False, and an inode change resets the transcript. |
| Perf: the first index reads each transcript whole | **Fixed** | Reads in 4 MB blocks and carries the partial tail between them. |
| Status files and `limits.jsonl` grow without bound | **Fixed** | At launch, `Store.prune_state()` deletes tap status files older than 8 days and compacts `limits.jsonl` (rows older than 8 days) once it passes 1 MB. In memory, observations older than 8 days are dropped. |
| A #15: `short_model` misses `[1m]`, `@date`, `us.anthropic.` and legacy ids | **Fixed** | `claude-opus-4-7[1m]` → Opus 4.7, `…sonnet-4-5@2025…` → Sonnet 4.5, `claude-3-5-sonnet-…` → Sonnet 3.5. |

## Processes, `procs.py`

| Finding | Status | What changed |
|---|---|---|
| A #4: macOS `ps` truncates `comm`, so Desktop-hosted `claude` is not recognised | **Fixed** | When `comm` is truncated, the full executable path is recovered from `args`, matching known names and stopping before the first ` -`. That covers paths with spaces ("Application Support") and keeps the `disclaimer --pgroup -- …/claude` wrapper from counting. No extra `ps` call. |
| A #7: any argv containing "mcp" is an MCP server (`grep -r mcp .`, `git commit -m 'fix mcp'`) | **Fixed**, not as A proposed | A's stricter rule would have missed all 28 real servers (F1 2.3). Instead: shells are classified first, and a process is MCP only if its program, or the first script or package a launcher (node, npx, uvx, python…) runs, is named for MCP (`mcp` as a whole name part: `@scope/mcp`, `.bin/mcp`, `mcp-server-x`, `/mcp/`). A shell wrapping such a launcher (`sh -c "npx mcp-server-x"`) counts as the server. |

## TUI, `tui.py`, `config.py`, `launch.py`, `claudemon.py`

| Finding | Status | What changed |
|---|---|---|
| F2 C4: `--mini` on first launch hides the install prompt, and Enter installs the tap | **Fixed** | The first-run prompt is never raised in the mini view; the mini footer's "⚡ tap off: I I" stays. |
| F1 M3 / F2 C11: Ctrl-C prints a traceback, skips saving and leaves the mini window size | **Fixed** | The loop runs inside `try/finally`. Ctrl-C, SIGTERM and SIGHUP leave like `q`: preferences are saved, the window size and title are restored. |
| F2 C11: quitting after `--mini` resizes to a 50×160 it never had | **Fixed** | The start size is recorded at launch and given back on exit; a real full-size start window becomes the "full" size. |
| F2 C11: `CSI 8 t` is sent to terminals that don't honour it (tmux, screen) | **Fixed** | It is sent only for Terminal and iTerm outside tmux/screen. Override with `CLAUDEMON_RESIZE=0/1`. |
| F1 M4: any Alt/Esc-prefixed key quits | **Fixed** | After Esc, if more input follows within 30 ms (Alt+key, an unrecognised sequence) it is swallowed. A lone Esc still quits. |
| F1 M5 / A #13: `²` crashes (`int()` on a non-ASCII digit); page mapping is hard-coded | **Fixed** | One `DIGITS = "1234567890"` table and `digit_page()`, clamped to the number of pages, used by `on_key`, `key_mini` and `go`. |
| F1 M6: `config.json` with `page: 99`, `interval: 7`, a list etc. crashes every launch | **Fixed** | `config.load()` returns only a dict. Each value is range- and type-checked (`page`, `span`, `interval`, `theme`, `graph`, `full_size`). The page is also saved by title (`page_name`), so a future reordering keeps the choice. Saves are atomic. |
| `tick()`: the forecast line and `store.refresh()` are unguarded (A #6) | **Fixed** | Both are guarded: an error shows in the flash line, and the previous forecast is kept. |
| F1 M10: the Session limit page waits for data forever on accounts that report only the weekly limit | **Fixed** | With the tap working and the other window reporting, the page, sidebar and mini view say "not reported" and explain why. |
| F1 M11: the first-run text says "Needs you" needs the tap | **Fixed** (text) | It now says limits, cost and context size need the tap, and that without it "Needs you" is a best guess. `waitingFor` is not shown yet (Deferred, cosmetic). |
| F2 C14: `--size` is interpolated into AppleScript unescaped | **Fixed** | `launch.parse_size()` requires `\d{2,4}x\d{1,4}`; the CLI rejects anything else. |
| Follow-up: `m` and `?` did nothing in the mini view | **Fixed** | They switch to the full view and open the manual or help. |
| Follow-up: below 70×16 the first-run prompt is not drawn, but ⏎ still installs the tap | **Fixed** | While the window is too small the prompt ignores every key except q/Esc (quit), and the screen says to enlarge the window to answer it. |
| Follow-up: mini resizes the whole window, tabs included | **Fixed** (docs) | README and manual suggest `--window --mini` and document `CLAUDEMON_RESIZE`. |
| F2 C14: docs claim claudeMon writes only to `~/.claude/claudemon/` | **Fixed** | README, SPEC and the manual describe the `settings.json` edits, the installed copy, backups and permissions. |

## Tests and tooling

- `tests/__init__.py`, so plain `python3 -m unittest` finds the tests.
- `tests/test_install.py` (27 tests): installer and tap in throwaway config directories.
- `tests/test_units.py` (28 tests): transcript, limits, procs, store, model names, the TUI's key and config handling, launch.
- The `test_smoke.py` ResourceWarning is fixed (the `sleep 300` helper is waited on).
- `.github/workflows/tests.yml`: CI on macOS with Python 3.9 and 3.13.

## Code review of this change

An independent `/code-review high` of the full diff raised 10 findings. Each one was checked against the code. 9 were real and are fixed, with a regression test for each. 1 was wrong.

| Finding | Verdict | Fix |
|---|---|---|
| `Transcript.refresh()` runs on two threads with no lock | **Wrong** | `refresh()` already holds a per-transcript `_lock` around `_refresh()`, so the offset and partial tail are never touched by both threads at once. |
| An unmarked old install from a moved or deleted checkout not named "claudemon" is wrapped a second time | Fixed | An unmarked status line is also recognised when its `tap.py` is the one a marked `# claudemon` hook in the same settings runs (old installs always added one), or when the file's header says it is claudeMon's tap. |
| `tap.py`: with no `resets_at`, every later reading counted as the same window, so drops were skipped for good | Fixed | No reset time means no stale filtering, in the tap and in `forecast`. |
| `tap.py`: an idle session on the previous window and an active one on the new window alternate, defeating the throttle | Fixed | Windows are ordered by reset time: a reading from an older window than the peak's is stale and skipped, and the peak only moves forward. |
| Pid-reuse check used `startedAt`, which may move after `/clear` or `/resume` in a long-running process | Fixed | It now uses the registry's `procStart`, the process's own start in UTC (it matched `ps` to 1 s for all 14 live sessions). Without it, the pid is trusted. |
| `# claudemon` was matched as a substring in hooks, so a user's hook `… # claudemon alerts` would be rewritten or deleted | Fixed | A hook is ours only when it parses as `… tap.py hook <Event> # claudemon`. |
| `compact()` rewrote `limits.jsonl` on every launch even when nothing was dropped, and could lose rows the tap appended meanwhile | Fixed | It skips the rewrite when nothing would be dropped, copies rows appended during the rewrite, and cleans up its temp file. |
| `claude mcp serve` was no longer classed as an MCP server | Fixed | `claude` counts as a launcher, so its `mcp` subcommand is recognised. |
| `config.save()` left a temp file behind when a value could not be serialised | Fixed | It serialises before creating the file, and removes the temp file on any error. |
| The Settings page showed "page error" when `settings.json` had an unexpected shape | Fixed | It uses `install.safe_status()` and shows the reason in red in the Data sources panel. |

The test suite is now 73 tests and passes on Python 3.9 and 3.13.

## Not changed, on purpose

| Item | Why |
|---|---|
| A #5: a content-less `dequeue` clears the prompt queue | F1 measured this on 30 days of real transcripts. The early wipe happened twice, not 165 times, and A's fix (pop the oldest prompt) would remove the wrong prompt 168 times. Even a full FIFO leaves 7 stale prompts where the current "clear" leaves 1. The current behaviour is the better trade-off, so it stays. |
| A #14: division by zero in the context gauges | Not a bug (F1). `Session.context()` never returns size 0, and `Canvas` keeps `w ≥ 2`. |
| A §3, §5: split `tui.py` into page modules, extract `fmt.py`, package as `claudemon/` with `pyproject.toml`, add a key table that drives the help screen | Refactors rather than fixes. They are best done as their own PR on top of this test suite (A's roadmap and F1 both say tests first). |
| A perf: mtime-gated `meta.json` reads; `ps` off the UI thread | Measured as low priority (`refresh` ~62 ms). No user-visible problem. |
| F2 C11: resizing a window that holds iTerm splits or Terminal tabs resizes the others too | There's no reliable way to detect splits. `CLAUDEMON_RESIZE=0` turns resizing off. |
| F2 C14: a `statusLine` in project or local settings bypasses the tap | That is Claude Code's precedence; claudeMon only edits user settings. |
| Linux | Still untested; CI runs on macOS only (the tests use `/bin/sh`, BSD `ps` and a Latin-1 locale). |
