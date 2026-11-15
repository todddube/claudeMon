# claudeMon reorganization plan

Status: proposed, not started. The goal is a layout that is easy to extend, installable with
Homebrew, and proven to behave the same as today, apart from a short list of
[declared deltas](#declared-deltas).

## Goals and stop line

We stop when every item has a passing check:

| Goal | Checked by |
|---|---|
| **Organized**: the tree below is in place | The tree exists; `test_boundaries` passes |
| **Easy to extend**: a page, subcommand or data source touches one module plus one registry line | `test_extension` registers a dummy of each using only those touch points |
| **Brew-installable** from this repo | CI installs the formula from the PR checkout; a post-merge job installs from GitHub `main` |
| **Same behaviour** on macOS and Linux | The parity harness shows only the declared deltas |
| **Modern tooling** | `pyproject.toml`, uv, ruff lint, pytest, CI on macOS and Linux |

Out of scope: multi-device sync, export formats, tagged releases, and the separate
`homebrew-claudemon` tap repo. The layout leaves room for sync (a new data source); none of it is
built here.

## Folder tree

```
claudeMon/
├── claudemon.py             kept: becomes a thin wrapper so ./claudemon.py still works from a clone
├── pyproject.toml  uv.lock  .python-version  .git-blame-ignore-revs
├── claudeMon.code-workspace VS Code workspace (renamed from claudemon.code-workspace)
├── Formula/claudemon.rb     HEAD formula, tappable from this repo
├── src/claudemon/
│   ├── __init__.py          __version__ (the only copy)
│   ├── __main__.py          python -m claudemon
│   ├── cli.py               the argparse parser, moved out of claudemon.py; flags unchanged
│   ├── commands.py          COMMANDS registry (snapshot, loops, install, …)
│   ├── window.py            --window launcher (was launch.py)
│   ├── core/                paths, runtime (tap_python, self_command), fmt, config
│   ├── tap/                 tap.py (byte-identical, standalone) + installer.py (was install.py)
│   ├── sources/             transcript, limits, procs, store
│   └── ui/
│       ├── app.py           main loop, chrome, global keys, state shared between pages
│       ├── draw.py  widgets.py  themes.py  manual.py  mini.py
│       ├── headless.py      FakeWin and its curses stub, shared by tests and tools
│       └── pages/           __init__.py holds the ordered PAGES list; one module per page
├── tests/                   existing suites + parity/, test_naming, test_boundaries,
│                            test_extension, test_packaging, test_tap_python
├── tools/                   was utils/: grid, make_demo, shots
├── docs/                    SPEC (moved from the root), ARCHITECTURE, RELEASING, review-fixes, this plan
├── screenshots/
└── .github/workflows/ci.yml was tests.yml
```

### Why this shape

- **A feature is one file plus `core`.** Working on the cache page means `ui/pages/cache.py`, not
  the 1,933-line `tui.py`.
- **Slices are coarse on purpose.** About 5k lines of app code doesn't earn a folder per feature.
  Limits and tap status are used by several pages, so they live in shared layers.
- **`sources/` is a shared data layer, not a feature.** Every page reads the same parsed
  transcripts, through `Store` methods instead of reaching into internals.
- **Rules are tests.** `test_boundaries` fails if `core` imports curses, or if headless commands
  import the UI.

### Page contract

Each page is `Page(id, title, key, render, side, on_key, tick, manual_topic)`.

- **Keys don't change.** Today keys are positional (`1`–`9`, `0`, with `s` hardcoded for the last
  of the 11 pages); each page now declares the key it has today.
- **Shared state lives on `App`,** passed to pages as `ctx`: selection, time range, theme, graph
  style. Page-only state lives in the page module.
- **One module can provide more than one page.** The session and weekly limit pages share
  `page_limit` today, so `pages/limits.py` exports both.
- **Saved prefs load unchanged.** `config.json` keeps storing `page_name` (the title); code uses `id`.
- **Smoke tests** take the page list from `PAGES`. The non-page screens (`mini`, the manual and its
  topics, the first-launch prompt, the inspector) stay listed by hand.
- `tasks.py` is page logic, so it moves next to the Tasks page.

### Cost of extending

| Add a | Touches |
|---|---|
| Page | One module + one `PAGES` line |
| Subcommand | One function + one `COMMANDS` entry |
| Data source | One module + three `Store` lines (construct, refresh, query method) |

`test_extension` keeps these numbers honest. A future sync feature would be one of each; its
prerequisite, a second data root, is described in `ARCHITECTURE.md` and not built.

## Entry points

Every route calls the same `claudemon.cli:main`:

| Route | Command |
|---|---|
| Clone, no install | `./claudemon.py` |
| Clone with uv | `uv run claudemon` |
| Module | `python -m claudemon` |
| Installed (brew, `uv tool install`) | `claudemon` |

Today `claudemon.py` is the whole CLI: the parser, `snapshot`, `loops`, `--window` forwarding and
the tty check (117 lines). Phase 3 moves all of that into `cli.py` and `commands.py`, and
`claudemon.py` becomes a wrapper that:

- **checks the Python version first.** On Python older than 3.11 it prints "claudeMon needs Python
  3.11+; try `uv run claudemon`" and exits non-zero. The wrapper uses only syntax old Pythons parse.
- **puts `src/` first on `sys.path`.** Otherwise `import claudemon` inside it would load the wrapper
  itself, because the script's own folder is searched first.

The wrapper only protects itself; anything else that puts the repo root first on `sys.path` would
also find the wrapper instead of the package. So:

- pytest runs with `--import-mode=importlib`, and `tests/__init__.py` goes.
- The `tools/` scripts add `src/` to the path, not the repo root.
- `test_packaging` asserts `claudemon.__file__` is under `src/` (or the installed site-packages).

The wrapper is not in the wheel, and its late import needs a ruff `E402` exemption.

**Old installs.** Until 34d06b6 (PR #1), the installer pointed `settings.json` straight at
`<clone>/tap.py`. Newer installs run a copy at `~/.claude/claudemon/tap.py`, which the move
doesn't touch. For the older ones:

- **Still recognised.** Marked commands are found by the `# claudemon` marker. Unmarked ones, from
  before the marker existed, are found by `install._ours`, which counts a command as claudeMon's when
  `claudemon.py` sits beside its `tap.py`. Because `claudemon.py` stays at the root, both kinds are
  still found and re-pointed at the copy.
- **Status line breaks until repaired.** The move takes `tap.py` out of the root, so on those
  machines the status line is blank from the pull until the next `claudemon` start or
  `claudemon install`, which repairs it. The README's upgrade note says to run `claudemon install`
  once after pulling.

The parity harness's legacy-checkout fixture covers both kinds.

## Naming rule

The repo name, `claudeMon`, is the name. Where tooling forces lowercase, or existing installs
depend on it, the machine form is the same name lowercased: `claudemon`.

| Form | Used for | Why |
|---|---|---|
| `claudeMon` | Prose, UI and window titles, docs, GitHub URLs, the `pyproject` project name, formula `homepage`/`head`/caveats, the workspace file | The repo name. PyPI and pip normalise `claudeMon` to `claudemon`, so the project name can keep its case |
| `claudemon` | Formula and tap name | Homebrew requires lowercase |
| `claudemon` | Python import package (`src/claudemon/`) | Convention; mixed-case packages are unsafe on case-insensitive filesystems |
| `claudemon` | CLI command, `~/.claude/claudemon/`, the `# claudemon` settings marker | Existing installs depend on them |
| `claudemon` in prose | Where the text means the command, e.g. "run `claudemon install`" | It is the command |
| `CLAUDEMON_*` | `_ASCII`, `_RESIZE`, `_TERMINAL`, `_DEMO` | Uppercase of the machine form |

- **Forced exception:** the Ruby class `Claudemon`, only inside `Formula/claudemon.rb`.
- **Formula `desc`:** `brew audit` rejects a desc that starts with the name or with an article, so
  it reads "Task manager for Claude Code".
- **Never used:** `ClaudeMon`, `Claudemon` (outside the formula class), `claude-mon`, `claude_mon`,
  `Claude Mon`.
- **Frozen strings**, kept byte-for-byte so existing installs keep working:
  - `b"tap for claudeMon"` and the `tap.py` docstring it matches
  - `MARK = "# claudemon"`
  - the `claudemon.py` legacy-checkout check
  - the temp-file patterns `.<name>.claudemon.<pid>.tmp` (installer), `.config.<pid>.tmp` (config)
    and `<path>.<pid>.tmp` (tap)
  - the four env var names

`tests/test_naming.py` fails on a banned spelling, and on the settings marker written as
`# claudeMon` at the end of a command string. Headings and comments like `# claudeMon` in
`README.md` are fine.

**Renames are file moves only:**

- `claudemon.code-workspace` → `claudeMon.code-workspace` (a case-only rename, so two `git mv` steps on macOS)
- `utils/` → `tools/`
- `SPEC.md` → `docs/SPEC.md`, with README links updated
- `tests.yml` → `ci.yml`
- the flat modules → `src/claudemon/`, with `install.py` → `tap/installer.py` and `launch.py` → `window.py`

No string, identifier, env var, path or marker changes.

## Python version and the tap interpreter

**The project needs Python 3.11+.** That covers `requires-python`, ruff's target and all code, from
phase 3 on.

**One exception: `tap.py` keeps running on the system Python.** Claude Code runs the tap on every
status-line refresh, using the interpreter path the installer writes into `~/.claude/settings.json`.
If that path disappears, the status line goes blank and nothing is running to notice.

**Today** (`paths.stable_python()`), the installer bakes whatever Python ran it, made a little more
stable:

- An Xcode or Command Line Tools Python becomes `/usr/bin/python3`.
- A Homebrew Cellar path becomes `<prefix>/bin/python3`.
- Anything else, including venv, uv and pyenv paths, is baked as-is.

On reinstall it keeps an interpreter that's already baked, unless that interpreter has vanished.

**New rule**, for fresh installs only (existing installs keep whatever they have):

| Platform | Baked interpreter | Why |
|---|---|---|
| macOS | `/usr/bin/python3` (3.9 today), if the Command Line Tools are installed and a timed probe runs | Survives brew upgrades and uninstalls, `uv tool uninstall` and deleting the clone. Brew's and uv's 3.11+ paths all move or disappear |
| Linux | `/usr/bin/python3`, if it runs | The distro's Python, managed by the package manager |
| Otherwise | A base (non-venv) interpreter, with a warning from `claudemon install` | Never a venv path, which an uninstall would delete |

**Standing rule:** `tap.py` uses only syntax and stdlib that run on the oldest system Python we bake
(3.9), and must also pass on the newest Python. CI enforces both, and `tap.py` is unchanged here.

The parity harness normalises interpreter paths, so it can't see this change. `test_tap_python`
covers the cases directly: Command Line Tools present or absent, probe timeout, running from a
venv, Linux.

## Tooling

- **pyproject:** PEP 621, src layout, `name = "claudeMon"`, `dependencies = []`, script
  `claudemon = "claudemon.cli:main"`.
- **Build backend: flit-core.** Homebrew builds the backend from source at install time, so the
  smallest backend wins:
  - flit-core has no dependencies of its own.
  - hatchling pulls several.
  - `uv_build` needs Rust to build from source.
- **uv:** `uv sync`, `uv run claudemon`, `uv run pytest`, `uv run ruff check`. Dependency groups
  `dev` (pytest, ruff) and `shots` (pillow) replace both `requirements.txt` files.
- **ruff: lint only.** `ruff check` runs in CI, with no `ruff format` pass and no import sorting
  (`I`), so there is no large reformatting diff. `tap.py` is excluded from the rules that would
  modernise its syntax (`UP`).
- **pytest** with `--import-mode=importlib`. The existing unittest classes keep their tests; their
  imports and paths are updated in phase 3.

### CI

Every job is required: a failure fails the build.

| Job | macOS | Linux |
|---|---|---|
| ruff check | ✓ | |
| pytest on 3.11 and newest | ✓ | ✓ |
| Parity harness | ✓ | ✓ |
| Tap on the system `/usr/bin/python3`, 3.9 and newest | ✓ | ✓ |
| Wheel install + `claudemon --version` | ✓ | ✓ |
| Brew: install from the PR checkout, then `brew style` and `brew audit --strict` | ✓ | |
| Brew, after merge: install from GitHub `main` | ✓ | |

**What Linux CI proves:** the app, every page (drawn headless), the installer, the tap and the CLI
run correctly on Linux. It does not test typing into a real interactive terminal, and `--window`
only has its generated commands checked.

## Homebrew

**Now, tapping this repo directly:**

```
brew tap todddube/claudemon https://github.com/todddube/claudeMon
brew install --HEAD todddube/claudemon/claudemon
claudemon install
```

- **Fully qualified name.** Tapping alone doesn't make Homebrew trust a formula; a fully qualified
  `brew install` does. This comes from reading the Homebrew 7 source, and the CI job confirms it.
  If that is wrong, the fallback is to document `brew trust` or the equivalent step.
- **Formula:** a virtualenv, `depends_on "python@3.14"`, `head` on `main`, and a `test do` running
  `claudemon --version`.
- **Caveats:**
  - Run `claudemon install` after installing; brew may not write to `~/.claude`.
  - Run `claudemon uninstall` before `brew uninstall`.
  - Upgrade with `brew upgrade --fetch-HEAD claudemon`.

**Testing the formula in CI.** `brew install --HEAD` clones the formula's `head` URL, which is
GitHub `main`, not the PR. So:

- The PR job taps the checkout and points `head` at it with a `file://` URL before installing. The
  PR's own code is what gets installed.
- Audit and style run after the install, because audit needs the formula to be trusted.
- A post-merge job installs from GitHub `main` unmodified, as a user would.

**Later, the short `brew tap todddube/claudemon`.** This needs steps only the repo owner can take:

1. Merge the packaging work to `main`.
2. Create the public repo `todddube/homebrew-claudemon` and add `Formula/claudemon.rb`.
3. Optionally tag `v0.1.0`, so `--HEAD` is no longer needed.

The install line stays the same; only the tap line gets shorter. Already-tapped machines keep
working, or switch with `brew tap --custom-remote`.

## Parity proof

Parity is differential: a pinned baseline commit of `main` in a git worktree, against the new tree,
with the same inputs and interpreter. It lives in `tests/parity/`.

**Only stable surfaces.** The harness drives each tree from the outside:

- the CLI as a subprocess;
- a small driver script run as a subprocess, for headless page grids and key scripts;
- a pty, for real terminal startup.

The driver's import lines are the only place that knows each tree's internal layout.

**Masks and pins** (every one is listed in the harness, so nothing is hidden silently):

| Source of drift | Handling |
|---|---|
| Clock (`datetime.now`, `time.time`, header clock, demo data) | Frozen before any import |
| Fixture file timestamps | Set to the frozen time |
| `Store`'s background index thread | The driver waits for indexing to finish before the first frame |
| Process table (`ps` elapsed time, CPU, RSS) | Demo mode, plus a fake `ps` for the non-demo home |
| Temp and backup names (pid, `time_ns`) | Masked to `<PID>` / `<NS>` |
| Hash order, timezone, locale | `PYTHONHASHSEED=0`, `TZ=UTC`, fixed locale |
| Interpreter paths | Normalised to `<PY>` (tap interpreter covered by `test_tap_python`) |
| Shared state between scenarios | A fresh copy of the demo home per side and scenario |

| What | Compared |
|---|---|
| CLI | stdout, stderr and exit code for every flag, `snapshot`, `loops`, error paths, and a non-tty run |
| TUI (headless) | Page grids across sizes, themes, graph styles and ASCII; key scripts with `config.json` after each key; `--mini` |
| TUI (pty) | Startup flags, first-launch prompt, resize and title escapes, SIGTERM saving prefs |
| Installer | `settings.json` bytes, backups and messages for install, uninstall and repair, including a legacy checkout and a symlinked `settings.json` |
| `--window` | Generated shell and AppleScript for every terminal branch, stubbed |
| Tap | sha256 of the source, the wheel copy and the installed copy |
| State | Tree and contents of `~/.claude/claudemon/` after each scenario |

Edge homes: empty, `--no-tap`, malformed `config.json`, a `CLAUDE_CONFIG_DIR` with spaces, and
non-demo with a fake `ps`.

**Stable before trusted.** The harness must pass baseline-against-baseline 20 times in a row on
both macOS and Linux before anything moves.

**Keeping the baseline current.** When `main` moves:

1. Merge it into the branch.
2. Re-run baseline-against-baseline.
3. Update the pinned commit in the same PR.

### Linux fixes come first

Linux has never been tested. `procs.py` is the likely break: it splits `ps` output assuming `comm`
has no spaces, which isn't true on Linux. Fixing that changes behaviour, so:

- Linux fixes land on today's flat layout, as their own small PRs, before the baseline is pinned.
- macOS output must be unchanged by them; parity against the previous commit checks that.

### Declared deltas

The only differences the harness allows:

1. **Python floor.** On Python older than 3.11, `./claudemon.py` prints the version message instead
   of running. This is a real change for users: today the README says the stock macOS
   `/usr/bin/python3` (3.9) works. The README changes with it and points them at `uv run claudemon`
   or brew. A one-off run of today's code on 3.9 and 3.13 lists any output that already differs
   between Python versions.
2. **`--window` relaunch command.** It uses `self_command()`, so it works from brew and uv installs,
   and drops `cd ROOT`.
3. **Baked tap interpreter on fresh installs** follows the new rule above. Existing installs are
   untouched.

## Migration phases

Each phase is one or more PRs, can be reverted on its own, and passes the parity harness.

0. **Parity harness, plus Linux fixes.** Build the harness on today's `main`, land any Linux fixes as
   separate PRs, then pin the baseline once it passes 20 times in a row on both OSes.
1. **Tooling, still flat.** pyproject (`requires-python >= 3.9` for now), uv, ruff with a 3.9
   target, CI rename and the Linux job, `test_naming`, workspace rename.
2. **Untangle, still flat.**
   - `fmt.py`, so `snapshot` stops importing the TUI.
   - `tap_python()` and `self_command()`, with `test_tap_python`.
   - The `COMMANDS` registry.
   - `FakeWin` and its curses stub into a shared module.
3. **One mechanical move** into `src/claudemon/`, listed in `.git-blame-ignore-revs`:
   - `claudemon.py` becomes the wrapper.
   - `tap.py` stays byte-identical.
   - Tests and tools switch to the new imports.
   - `requires-python` and ruff's target rise to 3.11.

   This touches every file and conflicts with any open PR, so land it with todddube when no other
   PRs are open.
4. **Brew.** Formula, `test_packaging`, both CI brew jobs, README install routes.
5. **Pages.** The page contract and `widgets.py` first, proven on one simple page, then the limits
   pair (two pages from one module). The contract is reviewed before the rest move one PR per page,
   then mini and the modals.
6. **Seams and docs.** The UI goes through `Store` methods; then `test_boundaries`, `test_extension`,
   `ARCHITECTURE.md` with the three extension recipes, and a naming pass over README and docs.

**Stop after phase 6**, when every row in [Goals and stop line](#goals-and-stop-line) has a passing check.

## Decisions

| Question | Decision |
|---|---|
| Python floor | 3.11+ from phase 3, with `tap.py` kept runnable on the system Python |
| `./claudemon.py` | Kept, as a thin wrapper |
| Project name | `claudeMon` in pyproject; `claudemon` only where forced |
| Formatting | Lint only: no `ruff format`, no import sorting |
| Linux | Required in CI; Linux fixes land before the baseline is pinned |
| Short tap name | Wanted; needs `todddube/homebrew-claudemon`, created by the repo owner |
| Multi-device sync | Out of scope; the layout leaves room |

**Open, for the repo owner:**

1. Can `Formula/` live in this repo now?
2. Will you create `homebrew-claudemon` later?
3. When is a good window for the phase 3 move?
