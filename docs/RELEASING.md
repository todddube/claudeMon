# Releasing

claudeMon has no tagged releases yet. Users install from the `main` branch, so "releasing" means
merging to `main` with the checks green. This page says what to run first, what CI does, and how
users pick up a change.

## The version

There is one version string, `__version__` in `src/claudemon/__init__.py`. `pyproject.toml` reads it
(`dynamic = ["version"]`), and `claudemon --version` prints it. Change it there and nowhere else.

## Before merging

Run these from the repo root.

```sh
uv run --python /usr/bin/python3 pytest -q     # the floor, Python 3.9
uv run --python 3.13 pytest -q                 # the newest
python3 -m unittest                            # the clone route: stock Python, nothing installed
uv run ruff check
python3 tests/parity/harness.py --python /usr/bin/python3 --python "$(command -v python3.13)"
tools/brew-check.sh                            # on a Mac with Homebrew
```

- The parity harness compares the tree with the commit pinned in `tests/parity/BASELINE`. It exists
  for the reorganisation and can be retired with it.
- `tools/brew-check.sh` clones the checkout, installs the formula from that clone through a local tap,
  runs `claudemon --version` and `brew test`, then styles and audits the pristine formula. It
  uninstalls and untaps everything on exit, whether it passed or not, but it leaves `python@3.14`
  installed if it had to pull it in. `CLAUDEMON_BREW_CHECK=1 pytest tests/test_packaging.py` runs it
  from the test suite.

## CI jobs

Defined in `.github/workflows/tests.yml`.

| Job | Runs on | PR check |
|---|---|---|
| `test` (3.9, 3.13) | macOS | Yes, and the required check names |
| `test-linux` (3.9, 3.13) | Linux | Can be |
| `lint` | Linux | Can be |
| `clone-route` | macOS | Can be |
| `wheel` | macOS, Linux | Can be |
| `parity` (3.9, 3.13) | macOS, Linux | Can be |
| `tap-system-python` | macOS, Linux | Can be |
| `brew` | macOS | Can be |
| `brew-main` | macOS | No: runs only on a push to `main` |

Keep the `test` job's name and matrix, so the repository's required-check settings keep matching.
The owner opts the other jobs in as required when wanted.

## After the merge: brew-main

`brew-main` taps `todddube/claudemon` from GitHub and installs `main` as a user would, then runs
`claudemon --version` with a temporary `CLAUDE_CONFIG_DIR`. If it fails it opens an issue titled
"brew install --HEAD fails on main", with a link to the run. That means a user following the README
would hit the same failure: fix it on `main`. Typical causes are a Python or setuptools change that
the formula's `setuptools` resource no longer matches, and a Homebrew policy change.

## How users upgrade

| Installed with | Upgrade with |
|---|---|
| Homebrew | `brew upgrade --fetch-HEAD claudemon` |
| uv | `uv tool upgrade claudeMon` |
| A clone | `git pull` |
| The Claude Code plugin | `claude plugin marketplace update claudemon`, then `claude plugin update claudemon@claudemon` (or `git pull`, for a marketplace added from a clone) |

The plugin has no version of its own: Claude Code versions it by the commit, so every merge to `main`
is a new plugin release. A plugin user restarts Claude Code after updating.

After an upgrade nothing else is needed: the tap in `~/.claude/claudemon/` is repaired by the app on
its next start. To remove claudeMon, run `claudemon uninstall` first, then `brew uninstall claudemon`.

## Homebrew trust

Homebrew 7 refuses to load a formula from an untrusted tap. Tapping does not trust it, but a fully
qualified `brew install --HEAD todddube/claudemon/claudemon` is accepted without `brew trust`
(verified with Homebrew 7.0.13). `brew test` by the same
qualified name does need it: it stops with "Refusing to load formula ... from untrusted tap".
`tools/brew-check.sh` runs `brew trust` for its two taps before `brew test`, `brew style` and
`brew audit`. Users who only
install need nothing extra.

## Owner-only steps for the short tap

These need the repository owner's GitHub account. Until they are done, users use the long form,
`brew tap todddube/claudemon https://github.com/todddube/claudeMon`.

1. Merge the packaging work to `main`.
2. Create the public repository `todddube/homebrew-claudemon` and copy `Formula/claudemon.rb` into its
   `Formula/` folder. After that `brew tap todddube/claudemon` works with no URL. Machines that
   tapped the long form keep working, or switch with `brew tap --custom-remote`.
3. Optionally tag `v0.1.0`, then add a `url` and `sha256` stable block to the formula so `--HEAD` is
   no longer needed. Keep the copy in the tap repository in step with `Formula/claudemon.rb` here.
