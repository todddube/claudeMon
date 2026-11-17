# Parity harness

Proves the reorganization keeps behaviour: the same scenarios run against a pinned baseline
commit and the tree under test, with the same inputs and interpreter, and every output is
compared after masking. See "Parity proof" in `docs/reorg-plan.md`.

```sh
python3 tests/parity/harness.py                          # pin (BASELINE) vs the working tree
python3 tests/parity/harness.py --candidate baseline     # the pin against itself
python3 tests/parity/harness.py --baseline HEAD~1        # a commit against its parent
python3 tests/parity/harness.py --python /usr/bin/python3 --python python3.13 --repeat 20
python3 tests/parity/harness.py --candidate baseline --python /usr/bin/python3 \
    --candidate-python python3.13                        # what already differs between Pythons (one-off)
python3 tests/parity/harness.py --list-masks             # every mask and pin
python3 tests/parity/harness.py --only pty --keep out/   # some scenarios; keep both sides' outputs
```

Exit status 0 is parity, 1 is a difference (the diffs are printed), 2 is a harness failure
(including the driver timing out while the store indexes).

| File | Role |
|---|---|
| `harness.py` | Runner: baseline worktree, sides, fixtures, pty, masks (`MASKS`), declared deltas (`DELTAS`), comparison |
| `scenarios.py` | The scenarios: CLI, page grids, key scripts, installer, tap, `--window`, pty |
| `frozen.py` | Launcher for every Python the harness starts: frozen clock, then the target as a script or `-m` |
| `driver.py` | Headless driver: fake curses window, page grids, key scripts, installer repair |
| `adapter_baseline.py` | The only code that knows the baseline's internals; frozen with the pin |
| `adapter_tree.py` | The same for the tree under test; changes as the App changes, reviewed like code |
| `BASELINE` | The pinned baseline commit |

Safety: every scenario sets `CLAUDE_CONFIG_DIR` and `HOME` to folders under a `mktemp`
directory before Python starts, and the harness refuses to run if either resolves to the
real home or its `.claude`. The baseline is a fresh `git worktree add --detach` under that
directory, removed in a `finally`, so several runs (and several worktrees) can run at once.
Nothing is written into the tree under test (`PYTHONDONTWRITEBYTECODE=1`).

Keeping the pin current: a behaviour change lands on `main` as its own PR; merge `main`
into the branch, re-run `--candidate baseline`, and update `BASELINE` in the merge commit.
The harness is deleted in one commit once the reorganization's stop line is met.
