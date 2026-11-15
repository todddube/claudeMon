# claudeMon reorganization plan

Status: proposed, not started. Revised after the Fable review of 815b5bb; every finding is folded in
below. The goal is a layout that is easy to extend, installable with Homebrew, and proven to behave the
same as today on macOS and Linux, apart from a short list of [declared deltas](#declared-deltas).

## Goals and stop line

We stop when every item has a passing check:

| Goal | Checked by |
|---|---|
| **Organized**: the tree below is in place | The tree exists; `test_boundaries` passes (from phase 3b on) |
| **Easy to extend**: a page, subcommand or data source touches one module plus one registry line | `test_extension` registers a dummy page, subcommand and data source at runtime, each through its registry only |
| **Brew-installable** from this repo | The brew script installs the formula from the local checkout (the same script the PR job runs); after merge, a post-merge job installs from GitHub `main` |
| **Same behaviour** on macOS and Linux | The parity harness shows only the declared deltas, on the Mac and on BOSS (Ubuntu in WSL2), and in the GitHub Linux job once pushed |
| **Modern tooling** | `pyproject.toml`, uv, ruff lint, pytest, CI on macOS and Linux |

Out of scope: multi-device sync, export formats, tagged releases, the separate `homebrew-claudemon`
tap repo, and the code quirks listed under [Kept as-is](#kept-as-is). The layout leaves room for sync
(a new data source); none of it is built here.

## Folder tree

```
claudeMon/
├── claudemon.py             kept: a self-replacing wrapper, so ./claudemon.py, a symlink to it and
│                            `python -c "import claudemon"` from the root all reach the package
├── tap.py                   kept: a short shim that execs the real tap, for installs from before PR #1
├── pyproject.toml  uv.lock  .git-blame-ignore-revs
├── claudemon.code-workspace unchanged
├── Formula/claudemon.rb     HEAD formula, tappable from this repo
├── src/claudemon/
│   ├── __init__.py          __version__ (the only copy)
│   ├── __main__.py          python -m claudemon
│   ├── cli.py               the argparse parser (git mv of claudemon.py); flags unchanged
│   ├── commands.py          COMMANDS registry (snapshot, loops, install, uninstall)
│   ├── window.py            --window launcher (was launch.py)
│   ├── core/                paths, runtime (tap_python, self_command), fmt, config
│   ├── tap/                 tap.py (byte-identical, standalone) + installer.py (was install.py)
│   ├── sources/             __init__.py holds the ordered SOURCES list; transcript, limits, procs, store
│   └── ui/
│       ├── app.py           main loop, chrome, global keys, navigation, state shared between pages
│       ├── draw.py  widgets.py  themes.py  manual.py  mini.py  modals.py
│       ├── headless.py      FakeWin and an explicit install() of the curses stub; no import side effects
│       └── pages/           __init__.py holds the ordered PAGES list; one module per page
├── tests/                   existing suites (still unittest classes) + parity/, test_naming,
│                            test_boundaries, test_extension, test_packaging, test_tap_python
├── tools/                   was utils/: grid, make_demo, shots
├── docs/                    SPEC (moved from the root), ARCHITECTURE, RELEASING, review-fixes, this plan
├── screenshots/
└── .github/workflows/tests.yml  keeps its name; gains the Linux, ruff, parity and brew jobs
```

No `.python-version`: a pyenv user whose `python3` shim reads it would get an error from
`./claudemon.py` if that exact version isn't installed. CI and uv name their versions explicitly.

### Why this shape

- **A feature is one file plus `core`.** Working on the cache page means `ui/pages/cache.py`, not
  the 1,947-line `tui.py`.
- **Slices are coarse on purpose.** About 5k lines of app code doesn't earn a folder per feature.
  Limits and tap status are used by several pages, so they live in shared layers.
- **`sources/` is a shared data layer, not a feature.** Every page reads the same parsed
  transcripts, through `Store` methods instead of reaching into internals.
- **Rules are tests.** `test_boundaries` fails if `core/` or `sources/` imports `ui/` or curses, or if
  a headless route (`snapshot`, `loops`, `install`, `uninstall`, `--version`, `--window`) loads curses.
  The rule is about curses, not the `ui/` folder: `cli.py` imports `ui/themes.py` for the `--theme`
  choices, and that stays allowed because `themes.py` and `ui/__init__.py` import nothing.

### Page contract

Each page is `Page(id, title, key, render, side, on_key, tick, manual_topic)`.

- **All 11 are pages,** Inspect included (key `0`). The non-page screens are the mini view, the
  manual and its topics, the help overlay, the first-launch prompt and the too-small guard; they live
  in `ui/mini.py` and `ui/modals.py` and are not covered by the contract.
- **Keys don't change.** Today keys are positional (`1`–`9`, `0` through `DIGITS`, with `s` hardcoded
  for the last of the 11 pages); each page now declares the key it has today. The mini view handles
  most global keys itself (PR #2 added `m`, `?` and more), and its page keys re-implement the full
  view's; it looks them up in `PAGES` instead.
- **Key routing.** The modal layer goes first (prompt, manual, help), then `z`, then the page's
  `on_key`, then the global keys. Today `on_key` has per-page branches: arrows and Enter on Settings
  and Tasks, `U` only on Settings, `e` for Models. Those become the pages' `on_key`; the default
  "Enter opens Inspect" stays a global fallback.
- **The App owns navigation.** Pages call `ctx.go(page_id, session=None)`; Tasks' `task_open` and the
  mini view's Enter both go through it. Nothing else sets the current page.
- **The App owns the per-tick work.** `App.tick` refreshes the store, computes both limit forecasts
  (shared by the limit pages, Projects, the mini view and the sidebar), calls every page's `side()`
  into the sidebar cache, and calls every page's `tick` hook, as today: the Tasks tree is built every
  tick even off-page and in mini. Pages never touch the sidebar cache.
- **Shared state lives on `App`,** passed to pages as `ctx`: selection, time range, theme, graph
  style, forecasts, tap state, flash. Page-only state (Models' `by_effort`, Tasks' cursor) lives in
  the page module.
- **One module can provide more than one page.** The session and weekly limit pages share
  `page_limit` today, so `pages/limits.py` exports both.
- **Saved prefs load unchanged.** `config.json` stores both `page` (the index) and `page_name` (the
  title); both keep their meaning, because order and titles don't change. Code uses `id`.
- **Manual links stay.** `manual_topic` replaces the title lookup in `manual.topic_for_page`. Topic
  ids and their order stay, because `-p manual:<prefix>` matches in list order (`manual:s` is Session
  limit, `manual:t` is the tap chapter).
- **Smoke tests** take the page list from `PAGES`, as `go()` strings: the smoke list today is title
  prefixes plus arguments (`inspect:web shop`), and `go()` keeps prefix matching on titles. The
  non-page screens (`mini`, `manual`, `manual:tap`, `prompt`) stay listed by hand.
- `tasks.py` is page logic, so it moves next to the Tasks page; its `build()` is what the page's
  `tick` hook calls.

**As built (the phase 5 glue):**

- `Page` also takes `state`, a factory for page-only state the App keeps at `ctx.page_state[id]`
  (Tasks' tree and cursor), so two Apps in one process never share it. `on_key(ctx, key, k)` returns
  True when it handled the key; `side`, `tick` and `render` take `ctx` first.
- Navigation is `ctx.go_page(page_id, session=None)`; `App.go(start)` keeps its meaning as the `-p`
  string (title prefixes, digits, `manual:<prefix>`, `mini`, `prompt`), which the parity adapter,
  `tools/grid.py` and the smoke tests use.
- `o` (Token burn's overall view) and `e` (Models' effort split) stay global keys and App state: they
  toggle from any page today, and the parity key scripts press `e` off the Models page.
- `ui/tasks.py` became `ui/pages/tasks_tree.py`, beside `ui/pages/tasks.py`, so the page's
  `fdur` (from `core/fmt`) and the tree's own `fdur` stay apart.
- The mini view (`ui/mini.py`) and the modals (`ui/modals.py`) moved in the same step, as functions
  of the App, so no two later units edit the same file. Every Store read the pages need is a Store
  method (`forecast`, `limit_samples`, `session_count`, `index_status`, `proc`, `cli_procs`,
  `desktop_procs`, plus the existing queries).

### Cost of extending

| Add a | Touches |
|---|---|
| Page | One module + one `PAGES` line |
| Subcommand | One function + one `COMMANDS` entry |
| Data source | One module + one `SOURCES` entry |

**One extension model for data sources: a registry.** `SOURCES` is an ordered list of
`(name, factory)` pairs. `Store.__init__` builds each one as `store.<name>`, so `store.limits` and
`store.procs` keep their names and no call site changes; `Store.refresh` refreshes them in list order
(`procs` before liveness checks, `limits` after the transcripts, as today), and each entry keeps its
current error handling (`limits` failures are swallowed, `procs` already never raises). Transcripts
are the Store's own core, not a source. This replaces "three hand-written `Store` lines", which no test
could check.

`test_extension` keeps these numbers honest. A future sync feature would be one of each; its
prerequisite, a second data root, is described in `ARCHITECTURE.md` and not built.

## Entry points

Every route calls the same `claudemon.cli:main`:

| Route | Command |
|---|---|
| Clone, no install (stock `/usr/bin/python3` 3.9 works) | `./claudemon.py`, or a symlink to it on `PATH` |
| Clone with uv | `uv run claudemon` |
| Module | `python -m claudemon` |
| Installed (brew, `uv tool install`) | `claudemon` |

Today `claudemon.py` is the whole CLI: the parser, `snapshot`, `loops`, `--window` forwarding and
the tty check (117 lines). Phase 3a moves it to `src/claudemon/cli.py` with `git mv`, so its history
follows; phase 2 has already moved `snapshot` and `loops` behind `COMMANDS`. Phase 3b writes a new
root `claudemon.py`: a wrapper that uses only syntax Python 3.9 parses and works two ways.

- **Run as a script** (`./claudemon.py`, a symlink, `python claudemon.py`, or `python -m claudemon`
  from the root, which finds the root file first): it puts `<realpath of its own file>/../src` first on
  `sys.path` and calls `claudemon.cli.main()`. `realpath` matters: the README tells users to symlink
  it into `~/.local/bin`, and the symlink's own folder has no `src/`.
- **Imported as `claudemon`** (`python -c "import claudemon"` from the root, `python -m pytest`, a tool
  that puts the root on `sys.path`; about 20 tests do exactly this): it inserts `src/`, removes itself
  from `sys.modules`, imports the real package and leaves it in `sys.modules["claudemon"]`. Python
  hands the importer whatever `sys.modules` holds when the import finishes, so the importer gets the
  package, and `import claudemon.cli` works too.

So `--import-mode=importlib` is a convenience, not the fix. Rules that keep one copy of each module:

- Nothing puts the repo root on `sys.path` on purpose. The `tools/` scripts add `src/`.
- Two module objects for one file would split globals such as `draw.ascii_mode` and
  `transcript.READ_BLOCK` (which a test patches), so `test_packaging` asserts `claudemon.__file__` is
  under `src/` or site-packages on every route, and that the wrapper never stays in `sys.modules`.
- Tests cover each route: `./claudemon.py`, a symlink to it from another folder, `python -m claudemon`
  from the root and from elsewhere, and `python -c "import claudemon.cli"` from the root.

The wrapper is not in the wheel, and its late import needs a ruff `E402` exemption.

**`python3 -m unittest -v` keeps working** from a clone with the stock Python: `tests/__init__.py`
stays, new tests are written as `unittest.TestCase` classes, and the wrapper's self-replacement makes
the in-process and `-c` imports resolve. CI runs it once on 3.9 with nothing installed, as the
clone-route proof; pytest is the everyday runner.

**Old installs.** Until 34d06b6 (PR #1), the installer pointed `settings.json` straight at
`<clone>/tap.py`. Newer installs run a copy at `~/.claude/claudemon/tap.py`, which the move
doesn't touch. For the older ones:

- **Still recognised.** Marked commands are found by the `# claudemon` marker. Unmarked ones, from
  before the marker existed, are found by `installer._ours`, which counts a command as claudeMon's when
  `claudemon.py` sits beside its `tap.py`, or the path contains `claudemon`, or the file's first 400
  bytes contain `tap for claudeMon`. Because `claudemon.py` stays at the root, both kinds are still
  found and re-pointed at the copy by the next `claudemon` start or `claudemon install`.
- **No outage, thanks to a root `tap.py` shim.** Without it, Python would fail to open `<clone>/tap.py`
  before the tap could exec the user's own status line, so that would vanish too, not just ours. The
  shim is a few lines of 3.9-safe stdlib: its docstring keeps `tap for claudeMon` in the first 400
  bytes, and it execs the same interpreter on `src/claudemon/tap/tap.py` with the same arguments. It
  is a [declared delta](#declared-deltas), excluded from ruff's `UP` rules and from the wheel, and is
  removed in a later release, not in this plan.

The parity harness's legacy-checkout fixture covers both kinds, with the shim in place.

## Naming rule

The repo name, `claudeMon`, is the name. Where tooling forces lowercase, or existing installs
depend on it, the machine form is the same name lowercased: `claudemon`.

| Form | Used for | Why |
|---|---|---|
| `claudeMon` | Prose, UI and window titles, docs, GitHub URLs, the `pyproject` project name, formula `homepage`/`head`/caveats | The repo name. PyPI and pip normalise `claudeMon` to `claudemon`, so the project name can keep its case |
| `claudemon` | Formula and tap name | Homebrew requires lowercase |
| `claudemon` | Python import package (`src/claudemon/`), found by name under `src/` (`[tool.setuptools.packages.find]`), never derived from the project name | Convention; mixed-case packages are unsafe on case-insensitive filesystems |
| `claudemon` | CLI command, `~/.claude/claudemon/`, the `# claudemon` settings marker, `claudemon.code-workspace` | Existing installs and habits depend on them |
| `claudemon` in prose | Where the text means the command, e.g. "run `claudemon install`" | It is the command |
| `CLAUDEMON_*` | `_ASCII`, `_RESIZE`, `_TERMINAL`, `_DEMO` | Uppercase of the machine form |

- **Forced exception:** the Ruby class `Claudemon`, only inside `Formula/claudemon.rb`.
- **Formula `desc`:** `brew audit` rejects a desc that starts with the name or with an article, so
  it reads "Task manager for Claude Code".
- **Never used:** `ClaudeMon`, `Claudemon` (outside the formula class), `claude-mon`, `claude_mon`,
  `Claude Mon`.
- **Frozen strings**, kept byte-for-byte so existing installs keep working:
  - `b"tap for claudeMon"` and the `tap.py` docstring it matches (also in the root shim)
  - `MARK = "# claudemon"` and the tap's `["#", "claudemon"]`
  - the `claudemon.py` legacy-checkout check, and the `tap.py` basename the installer parses
  - the temp-file patterns `.<name>.claudemon.<pid>.tmp` (installer), `.config.<pid>.tmp` (config)
    and `<path>.<pid>.tmp` (tap and the limits compactor)
  - the state files under `~/.claude/claudemon/` (`tap.py`, `config.json`, `limits.jsonl`,
    `tap_last.json`, `status/<sid>.json`, `status/<sid>.hook.json`, `statusline.backup.json`,
    `settings.<ns>.bak.json`)
  - the four env var names
  - page titles (stored in `page_name`), theme names (stored in `theme`) and manual topic ids
    (matched by `-p manual:<prefix>`)

`tests/test_naming.py` fails on a banned spelling, and on the settings marker written as
`# claudeMon` at the end of a command string. Headings and comments like `# claudeMon` in
`README.md` are fine.

**Renames are file moves only:**

- `utils/` → `tools/`
- `SPEC.md` → `docs/SPEC.md`, with README links updated (including the `#1-what-himamushi-is` anchor)
- the flat modules → `src/claudemon/`, with `claudemon.py` → `cli.py`, `install.py` →
  `tap/installer.py`, `launch.py` → `window.py`, `version.py` folded into `__init__.py`

Not renamed: `claudemon.code-workspace` (a case-only rename is churn for no user) and
`.github/workflows/tests.yml` (renaming it would rename the required checks).

No string, identifier, env var, path or marker changes.

## Python version and the tap interpreter

**The project stays on Python 3.9+.** `requires-python = ">=3.9"`, ruff's `target-version = "py39"`,
and CI tests 3.9 and the newest Python. The app has no dependencies, CI already passes on 3.9, and the
primary route is clone-and-run on the stock macOS `/usr/bin/python3` (3.9), so nothing earns a higher
floor. The wrapper has no version check.

**`tap.py` runs on the system Python.** Claude Code runs the tap on every status-line refresh, using
the interpreter path the installer writes into `~/.claude/settings.json`. If that path disappears,
the status line goes blank and nothing is running to notice.

**Today** (`paths.stable_python()`), the installer bakes whatever Python ran it, made a little more
stable:

- An Xcode or Command Line Tools Python becomes `/usr/bin/python3`.
- A Homebrew Cellar path becomes `<prefix>/bin/python3`.
- Anything else, including venv, uv and pyenv paths, is baked as-is.

On reinstall and repair it keeps an interpreter that's already baked, unless that interpreter has
vanished; then it falls back to the same rule as a fresh install (`install.py:300`, `:317`).

**New rule, `core/runtime.tap_python()`**, for fresh installs and for that vanished-interpreter
fallback (a working baked interpreter is always kept):

| Platform | Baked interpreter | Why |
|---|---|---|
| macOS | `/usr/bin/python3` (3.9 today), if the Command Line Tools are installed and a timed probe runs | Survives brew upgrades and uninstalls, `uv tool uninstall` and deleting the clone. Brew's and uv's paths all move or disappear |
| Linux | `/usr/bin/python3`, if it runs | The distro's Python, managed by the package manager (3.14 on BOSS) |
| Otherwise | A base (non-venv) interpreter, with a warning from `claudemon install` | Never a venv path, which an uninstall would delete |

**It lands first, in phase 1, before uv.** Once uv is in, `uv run ./claudemon.py install` would bake
`.venv/bin/python` as-is, and keep-existing would preserve it after the venv is gone.

**Standing rule:** `tap.py` uses only syntax and stdlib that run on the oldest system Python we bake
(3.9), and must also pass on the newest Python. CI enforces both, and `tap.py` is unchanged here.
`tap.py` duplicates `WINDOWS` and `SAME_WINDOW_S` from `limits.py` on purpose (it imports nothing); a
test asserts the two copies agree.

The parity harness normalises interpreter paths, so it can't see this change. `test_tap_python`
covers the cases directly: Command Line Tools present or absent, probe timeout, running from a venv,
a vanished baked interpreter, Linux.

**`core/runtime.self_command()`** returns the argv that starts claudeMon again, for `--window`:

| Started as | `self_command()` |
|---|---|
| `./claudemon.py` or a symlink to it | `[sys.executable, <realpath of the wrapper>]`; the wrapper records its path when it runs |
| `python -m claudemon` | `[sys.executable, "-m", "claudemon"]` |
| An installed `claudemon` (brew, `uv tool`) | `[<absolute sys.argv[0] as invoked>]`, not its realpath: brew's `/opt/homebrew/bin/claudemon` is stable, while the Cellar path behind it changes on upgrade |

No `cd`: nothing depends on the working directory. Today `launch.py` builds
`cd <ROOT> && exec <python> <ROOT>/claudemon.py`, with `ROOT` from `__file__`; after the move that
would point at `src/claudemon/claudemon.py` and fail silently, only when a window opens. The parity
harness's `--window` scenarios and `test_tap_python`'s `self_command` cases catch that.

## Tooling

- **pyproject while flat (phases 1-2): tool config only.** `[project]` with `name = "claudeMon"`,
  `requires-python = ">=3.9"`, `dynamic = ["version"]` and `dependencies = []`; dependency groups;
  `[tool.ruff]` and `[tool.pytest.ini_options]`. No `[build-system]` and no script entry: flit-core
  can't build a flat multi-module tree, and `claudemon.cli:main` has no target yet. uv treats a
  pyproject without a build system as a virtual project and installs only the groups (checked with
  uv 0.12.1).
- **Packaging from phase 3b (as built: setuptools, see the next bullet):** PEP 621, src layout,
  `[build-system]` setuptools, the package found as `claudemon*` under `src/`, version read from
  `__init__.__version__`, script `claudemon = "claudemon.cli:main"`. Originally planned with flit-core and
  `[tool.flit.module] name = "claudemon"`, which was required because flit-core 4.2 derives the module
  name from the project name without lowercasing, so `claudeMon` would look for `src/claudeMon/`,
  which passes on case-insensitive macOS and fails on Linux. `tap/tap.py` ships in the wheel as an
  ordinary file of the package; the installer copies its bytes.
- **Build backend: setuptools (changed in phase 3b).** Homebrew builds the backend from source at
  install time, so the smallest backend wins:
  - flit-core was the first choice but cannot build this tree: flit-core 3.12, 4.0.2 and 4.2.0 all
    stop with "Multiple files or folders could be module claudemon" when both the root
    `claudemon.py` (kept as the clone route's wrapper) and `src/claudemon/` exist.
  - setuptools (>= 77, for the SPDX `license`) has no dependencies of its own; the formula needs it
    as a resource.
  - hatchling pulls several.
  - `uv_build` needs Rust to build from source.
- **uv:** `uv sync`, `uv run claudemon` (from 3b), `uv run pytest`, `uv run ruff check`. Dependency
  groups `dev` (pytest, ruff) and `shots` (pillow) replace both `requirements.txt` files. The lock
  forks where it must: pytest 9 needs 3.10+, so 3.9 gets the last 8.x.
- **ruff: lint only.** `ruff check` runs in CI with the default rule set (`E4`, `E7`, `E9`, `F`), no
  `E501` (draw.py's glyph tables are long), no `ruff format` pass and no import sorting (`I`), so
  there is no large reformatting diff. `tap.py` and the root shim are excluded from the rules that
  would modernise their syntax (`UP`).
- **pytest** with `--import-mode=importlib`. The existing unittest classes keep their tests; their
  imports and paths are updated in phase 3.
- **`.gitignore`** gains `.venv/`, `dist/`, `build/`, `*.egg-info/`, `.ruff_cache/`, `.pytest_cache/`,
  and `images/` becomes `/images/` so it can't hide a package folder of that name.

### CI

`.github/workflows/tests.yml` keeps its name and its `test` job with the `test (3.9)` and
`test (3.13)` labels, so the owner's required-check settings don't change; new jobs are added beside
it, and he opts them in as required when he wants. Every job can gate a PR except the post-merge brew
job, which runs after the merge and opens an issue on failure instead.

| Job | macOS | Linux |
|---|---|---|
| ruff check | ✓ | |
| pytest on 3.9 and newest | ✓ | ✓ |
| `python -m unittest` on 3.9, nothing installed (the clone route) | ✓ | |
| Parity harness (fetches the pinned commit; `actions/checkout` is depth 1) | ✓ | ✓ |
| Tap on the system `/usr/bin/python3`, 3.9 and newest | ✓ | ✓ |
| Wheel build, install + `claudemon --version` | ✓ | ✓ |
| Brew: install from the PR checkout, then `brew style` and `brew audit --strict` on the pristine formula | ✓ | |
| Brew, after merge: install from GitHub `main` (not a PR check) | ✓ | |

Nothing is pushed in this run, so the workflow is written and its steps run locally; the Mac and
BOSS are the proof until it is pushed.

**What Linux proves:** the app, every page (drawn headless), the installer, the tap and the CLI
run correctly on Linux, on BOSS (Ubuntu in WSL2, Python 3.14 as `/usr/bin/python3`, 3.9 from
`uv python install 3.9`, no Homebrew) and in the GitHub job. It does not test typing into a real
interactive terminal, `--window` only has its generated commands checked, and brew is macOS-only.

## Homebrew

**Now, tapping this repo directly:**

```
brew tap todddube/claudemon https://github.com/todddube/claudeMon
brew install --HEAD todddube/claudemon/claudemon
claudemon install
```

- **Fully qualified name.** Tapping alone doesn't make Homebrew trust a formula; a fully qualified
  `brew install` does (Homebrew 7.0.13: `cmd/install.rb:197` trusts fully qualified names;
  `cmd/trust.rb` is the explicit step). The CI job confirms it. If that is wrong, the fallback is to
  document `brew trust`.
- **Formula:** a virtualenv, `depends_on "python@3.14"`, `head` on `main`, and a `test do` running
  `claudemon --version`.
- **Caveats:**
  - Run `claudemon install` after installing; brew may not write to `~/.claude`.
  - Run `claudemon uninstall` before `brew uninstall`.
  - Upgrade with `brew upgrade --fetch-HEAD claudemon`.

**Testing the formula in CI.** `brew install --HEAD` clones the formula's `head` URL, which is
GitHub `main`, not the PR. Three traps, and how the job avoids them:

- **`brew tap <name> <checkout>` clones committed state,** so editing `head` in the checkout does
  nothing. The job writes the patched formula into a separate local tap made with
  `brew tap-new local/claudemon --no-git`, whose files are used as they are on disk.
- **`actions/checkout` leaves a shallow detached HEAD with no local `main`,** so `head ..., branch: "main"`
  can't resolve. The job fetches with `fetch-depth: 0`, creates a branch `ci-head` at the PR commit,
  and the patched formula reads `head "file://$GITHUB_WORKSPACE", branch: "ci-head"`. It installs
  `local/claudemon/claudemon`, so the PR's own code is what gets installed.
- **Auditing the patched formula audits the wrong file.** Style and audit run on the pristine
  `Formula/claudemon.rb`, tapped from the checkout as `todddube/claudemon` (committed state is exactly
  what is wanted there) and trusted with `brew trust` before `brew audit --strict`.

The same steps live in one script, `tools/brew-check.sh`, which the job calls and which runs on the
Mac against a temporary branch of the local repo. A post-merge job installs from GitHub `main`
unmodified, as a user would.

**Later, the short `brew tap todddube/claudemon`.** This needs steps only the repo owner can take:

1. Merge the packaging work to `main`.
2. Create the public repo `todddube/homebrew-claudemon` and add `Formula/claudemon.rb`.
3. Optionally tag `v0.1.0`, so `--HEAD` is no longer needed.

The install line stays the same; only the tap line gets shorter. Already-tapped machines keep
working, or switch with `brew tap --custom-remote`.

## Parity proof

Parity is differential: a pinned baseline commit, at or after 815b5bb, against the new tree, with the
same inputs and interpreter. It lives in `tests/parity/`.

**A fresh baseline worktree per run.** Each run does
`git worktree add --detach <mktemp -d>/baseline <pin>`, runs with `PYTHONDONTWRITEBYTECODE=1`, and
removes the worktree and prunes in a `finally`. Never a fixed path, so several worktrees (and
several agents) can run the harness at once. Demo homes are `mktemp` directories too, never
`tools/shots.py`'s shared `$TMPDIR/claudemon-demo`.

**Never the real `~/.claude`.** Every scenario sets `CLAUDE_CONFIG_DIR` (and `HOME`) to a temp
directory before Python starts, because paths are read at import and every TUI start runs
`installer.repair()`, which writes `settings.json`. The harness refuses to run if either resolves
under the real home's `.claude`.

**Only stable surfaces.** The harness drives each tree from the outside:

- the CLI as a subprocess;
- a small driver script run as a subprocess, for headless page grids and key scripts;
- a pty, for real terminal startup.

**A small adapter per tree is the only place that knows its internals.** Today that is the import
lines plus `App(win, store, cfg)`, `.tick`, `.go`, `.draw`, `.on_key`. The baseline adapter is frozen
with the pin; the new tree's adapter changes as phase 5 changes the App, and those changes are
reviewed like code, because a wrong adapter can hide a difference.

**Masks and pins** (every one is listed in the harness, so nothing is hidden silently):

| Source of drift | Handling |
|---|---|
| Clock (`time.time`, `datetime.now`, header clock, demo data) | Every Python the harness starts (CLI, driver, pty) goes through a launcher, `tests/parity/frozen.py`, that installs a frozen `time.time` and `datetime` before any import, then runs the target as a script would (`sys.argv`, `sys.path[0]` = the script's real folder) or as `-m`. No `sitecustomize`, which would itself touch `sys.path` |
| Fixture file timestamps | Set to the frozen time |
| Tap runs | The tap is run by `/bin/sh` from Claude Code's command, so it can't be frozen: `_seen` in `status/<sid>.json` and `ts` in `limits.jsonl` and `tap_last.json` are masked |
| `Store`'s background index thread | The driver waits for indexing and fails if it doesn't finish in time; it never renders anyway as `tools/grid.py` does after 10 s |
| Process table (`ps` elapsed time, CPU, RSS) | Demo mode, plus a fake `ps` for the non-demo home |
| Live pids | Demo sessions register under a live helper pid (`make_demo --pid`, a `sleep` per side); pids are masked to `<PID>` in output and state |
| Temp and backup names (pid, `time_ns`) | Masked to `<PID>` / `<NS>` |
| Hash order, timezone, locale | `PYTHONHASHSEED=0`, `TZ=UTC`, a fixed UTF-8 locale (`proc_start` parses `%a %b` with the locale) |
| Interpreter paths | Normalised to `<PY>` (tap interpreter covered by `test_tap_python`) |
| Shared state between scenarios | A fresh copy of the demo home per side and scenario |

| What | Compared |
|---|---|
| CLI | stdout, stderr and exit code for every flag, `snapshot`, `loops`, error paths, and a non-tty run |
| TUI (headless) | Page grids across sizes, themes, graph styles and ASCII; key scripts with `config.json` after each key, including mini `m` and `?` (which leave mini for a modal), the mini view's other global keys, and the too-small window (`too_small()` and the first-launch prompt's guard in `key_prompt`); `--mini` |
| TUI (pty) | Startup flags, first-launch prompt, resize and title escapes, SIGTERM saving prefs |
| Installer | `settings.json` bytes, backups and messages for install, uninstall and repair, including a legacy checkout (both kinds, through the root shim) and a symlinked `settings.json` |
| `--window` | Generated shell and AppleScript for every terminal branch, stubbed |
| Tap | sha256 of the source, the wheel copy and the installed copy |
| State | Tree and contents of `~/.claude/claudemon/` after each scenario |

Edge homes: empty, `--no-tap`, malformed `config.json`, a `CLAUDE_CONFIG_DIR` with spaces, and
non-demo with a fake `ps`.

**Python versions.** Both sides always run on the same interpreter, on 3.9 and on the newest Python.
A one-off run of the baseline on 3.9 against itself on the newest lists what already differs between
versions (for example, 3.9's `fromisoformat` rejects some timestamps newer Pythons accept); those are
facts about today, not deltas.

**Stable before trusted.** The harness must pass baseline-against-baseline 20 times in a row on
the Mac and on BOSS before anything moves.

**Keeping the baseline current.** Behaviour changes don't ride in migration commits. When one is
needed mid-migration, it lands on `main` as its own PR, and then:

1. Merge `main` into the branch.
2. Re-run baseline-against-baseline.
3. Update the pinned commit in the same commit as the merge.

**Retirement.** When the stop line is met, the last run's results go into the final PR's description,
and the harness is deleted in one commit, so it doesn't rot. The page-grid smoke tests stay.

### Linux fixes come first

Linux has never been run. The first step of phase 0 is the current suite and a demo run on BOSS.
`procs.py` is the likely break, but not because `comm` has spaces: it has them on macOS too, and
`exe_from` already recovers macOS's truncated paths. On Linux `comm` is a bare name cut at 15
characters that can contain spaces (`tmux: server`, `Web Content`), and that shifts the
`split(None, 6)` at `procs.py:115`, so `args` is mis-split or the line is dropped. Fixing that
changes behaviour, so:

- Linux fixes land on today's flat layout, as their own small commits, before the baseline is pinned.
- macOS output must be unchanged by them; parity against the previous commit checks that.
- Tests that can't hold on Linux are fixed, not skipped silently: the unwritable-settings test
  (`chmod 0o500`) skips with a reason when running as root.

### Declared deltas

The only differences the harness allows:

1. **`--window` relaunch command.** It uses `self_command()`, so it works from brew and uv installs,
   and drops `cd ROOT`.
2. **Baked tap interpreter** follows `tap_python()` on fresh installs and when the baked interpreter
   has vanished. A working baked interpreter is kept.
3. **Legacy `<clone>/tap.py` installs run through the root shim** until the next `claudemon` start or
   `claudemon install` re-points them at the copy. Output is the same; there is one extra exec.

Not deltas, because they are kept: the Python floor (3.9), `python3 -m unittest`, and both `page` and
`page_name` in `config.json`.

## Kept as-is

The gather pass over every module found quirks that are behaviour, so the parity harness would flag
any fix. None is changed in this plan; each can be its own PR on `main` later.

- Doc drift: `tui.py`'s docstring says ten pages (there are 11); SPEC lists graph ranges
  `1 m / 5 m / 15 m / 1 h` (the code has 5m to 24h) and promises pie and over-the-week views; the
  prompt shows an `L Later` chip with no `L` binding (any key dismisses).
- Duplicates: `tasks.fdur` and `tui.fdur` (only `tui`'s moves to `core/fmt`; they merge only after a
  test shows they agree), `tasks.STATE_ROLE` and `tui.STATE_ROLE_TUI` (the latter looks unused), the
  cache hit-ratio formula in three places, the 70×16 size threshold in four, the key lists in help,
  footer, manual, README and SPEC.
- Write-only or dead state: `Store.session_for_pid`, `Store.tap_seen`, `Store.index_errors` (set only
  in `index()`), `Session.seen`, `Transcript.bad_records`, `Transcript.read_totals`, `LimitLog.plan`.
- Cost per tick: `installed()` reads `settings.json` every tick (and Settings twice more), every
  page's sidebar and the Tasks tree are computed in mini too, and forecasts scan all sessions per gap.
- Prefs other than `tap_prompt_seen` are saved only on a clean exit; `--mini` launches never show the
  first-launch prompt; the mini view's `m` opens the Welcome chapter, not the page's.
- Display strings name `~/.claude/...` even under a custom `CLAUDE_CONFIG_DIR`.

## Migration phases

Each phase is one or more commits on `joe/reorganize-plan`, can be reverted on its own, and passes
the parity harness on the Mac and on BOSS. PR boundaries are cut later from the commits.

0. **Parity harness, plus Linux fixes.** Run the suite on BOSS; build the harness on the flat layout;
   land any Linux fixes as separate commits; then pin the baseline (at or after 815b5bb) once it
   passes 20 times in a row on both machines.
1. **Tap interpreter, then tooling, still flat.**
   - First, `tap_python()` in a flat `runtime.py`, used by the installer, with `test_tap_python`.
   - Then the tool-config `pyproject.toml` (no build system), `uv.lock`, the `.gitignore` additions,
     ruff with a 3.9 target, pytest, the Linux, ruff and clone-route jobs added to `tests.yml`, and
     `test_naming`. The two `requirements.txt` files go; the README's install and tests sections say so.
2. **Untangle, still flat.**
   - `fmt.py` with `tui`'s formatters, so `snapshot` stops importing the TUI.
   - `self_command()`, used by the window launcher, with its `test_tap_python` cases.
   - The `COMMANDS` registry.
   - `FakeWin` and the curses stub into a flat `headless.py` whose `install()` patches curses only
     when called; `utils/grid.py` and the tests call it.
   - The tap/limits constants test.
3. **The move, in two commits.** They land together; only 3a is listed in
   `.git-blame-ignore-revs`, and `git bisect` skips it, since 3a alone doesn't run.
   - **3a. `git mv` and import rewrites only.** Every module to its place in `src/claudemon/`,
     `utils/` → `tools/`, `SPEC.md` → `docs/`. Import lines are rewritten everywhere, including the
     import lines inside tests' `-c` code strings and the tools. Nothing else changes, so the blame
     skip hides nothing.
   - **3b. Make it run.**
     - The new root `claudemon.py` (self-replacing wrapper) and the root `tap.py` shim.
     - Packaging: `[build-system]`, the package name, the script entry, `__main__.py`, and the
       wheel half of `test_packaging` (`claudemon.__file__`, `installer.TAP_SRC` exists in the
       installed wheel and matches `src/claudemon/tap/tap.py` byte for byte).
     - The tests that go vacuous or break, by name: the glyph audit in `test_smoke.py:27` globs
       `src/claudemon/` and `tools/` recursively and asserts it scanned at least 20 files;
       `copy_checkout` in `test_install.py:15-23` copies the wrapper, the shim and `src/` as a tree;
       `ROOT / "tap.py"` in `test_smoke.py:168` and `test_install.py:215,259,264` points at the real
       tap (the legacy fixture keeps the root path, which is now the shim); `test_units.py:309`'s
       `import utils.grid` becomes `claudemon.ui.headless` plus `install()`; the `utils/...` script
       paths become `tools/...`. CI's `compileall .` keeps running on 3.9 over the whole tree.
     - The entry-point route tests, `test_boundaries`, and the `.git-blame-ignore-revs` file.
     - README: install, run, layout, tests and screenshot sections; SPEC links.

   3a touches every file and conflicts with any open PR, so the owner picks a window when no other PRs
   are open.
4. **Brew.** Formula, `tools/brew-check.sh`, the brew half of `test_packaging`, both CI brew jobs,
   README install routes.
5. **Pages.** First the glue: the `Page` contract, `ctx`, `PAGES`, `widgets.py` (the App's chart,
   kv, toggles, badge, chip and callout helpers), the `SOURCES` registry, and the new tree's parity
   adapter. It is proven on one simple page (Traffic: no page-only state, no navigation), then on the
   limits pair (two pages from one module) and on Tasks (navigation and a `tick` hook). The contract
   is reviewed before the rest move one page at a time, then mini and the modals.
6. **Seams and docs.** Pages read only through `Store` methods (`test_boundaries` gains that rule);
   then `test_extension`, `ARCHITECTURE.md` with the three extension recipes, a naming pass over
   README and docs, and the harness's retirement.

**Stop after phase 6**, when every row in [Goals and stop line](#goals-and-stop-line) has a passing check.

## Execution

This run works on the one local branch, `joe/reorganize-plan`, and pushes nothing.

1. **Phases 0-3, serially,** in the main checkout's branch. Each commit runs the suite and the parity
   harness on the Mac, then on BOSS (synced with a git bundle and checked out detached under
   `~/code/claudemon`).
2. **The page/Store glue** (the start of phase 5), serially, because every later unit builds on it.
3. **Then parallel units,** each in its own git worktree under `claudemon-work/`, outside the repo:
   brew (phase 4), one unit per remaining page (the limits pair is one unit), mini, and the modals.
   Each unit runs the harness in its own temporary baseline worktree, which is why the harness has to
   be safe to run concurrently. Units come back one at a time; the branch re-runs the suite and the
   harness on the Mac and BOSS after each.
4. **Phase 6, serially,** once every unit is in.

The main checkout is left clean between steps, with scratch files kept outside the repo, and no
run touches the real `~/.claude`: every install, uninstall, tap or TUI run gets a temporary
`CLAUDE_CONFIG_DIR` and `HOME`.

## Decisions

| Question | Decision |
|---|---|
| Python floor | 3.9+ throughout; `tap.py` also kept runnable on the system Python |
| `./claudemon.py` | Kept, as a self-replacing wrapper; a symlink to it keeps working |
| Root `tap.py` | Kept as a shim for pre-PR #1 installs, removed in a later release |
| Project name | `claudeMon` in pyproject; `claudemon` only where forced |
| Formatting | Lint only: no `ruff format`, no import sorting |
| Data-source extension | A `SOURCES` registry, like `PAGES` and `COMMANDS` |
| Headless curses stub | In the package, patched only by an explicit `install()` |
| Workspace file, `tests.yml` | Not renamed |
| Linux | Proven on BOSS and in CI; Linux fixes land before the baseline is pinned |
| Short tap name | Wanted; needs `todddube/homebrew-claudemon`, created by the repo owner |
| Multi-device sync | Out of scope; the layout leaves room |

**Open, for the repo owner:**

1. Can `Formula/` live in this repo now?
2. Will you create `homebrew-claudemon` later?
3. When is a good window for the phase 3 move?
4. Which of the new CI jobs should become required checks?
