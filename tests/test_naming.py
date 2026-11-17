"""The naming rule (docs/reorg-plan.md, "Naming rule"): the name is claudeMon, its machine form is
claudemon, and nothing else. Fails on a banned spelling anywhere in the tracked text files, and on the
settings marker written as `# claudeMon` at the end of a command string."""

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

BANNED = re.compile(r"ClaudeMon|Claudemon|claude-mon\b|claude_mon\b|Claude Mon\b")
# The marker is `# claudemon`; a string ending in `# claudeMon` would not be recognised.
BAD_MARKER = re.compile(r"# claudeMon(\"|'(?!s\b))")
# Forced exception: the Ruby class name in the formula, nowhere else.
FORMULA_CLASS = re.compile(r"^class Claudemon < Formula\s*$")

# Files that name the banned spellings on purpose.
SKIP = {"docs/reorg-plan.md", "tests/test_naming.py", "uv.lock"}
SKIP_DIRS = {".git", ".venv", "__pycache__", ".ruff_cache", ".pytest_cache", "dist", "build", "images", "screenshots"}


def tracked_files():
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=str(ROOT), capture_output=True, check=True).stdout
        return [ROOT / n for n in out.decode("utf-8").split("\0") if n]
    except (OSError, subprocess.CalledProcessError):      # a source archive without .git
        return [p for p in ROOT.rglob("*") if p.is_file() and not SKIP_DIRS & set(p.relative_to(ROOT).parts)]


def text_lines(path):
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except (UnicodeDecodeError, OSError):
        return []                                          # binary: screenshots and the like


class Naming(unittest.TestCase):
    def scan(self, pattern, allow=None):
        hits = []
        for path in tracked_files():
            rel = path.relative_to(ROOT).as_posix()
            if rel in SKIP or SKIP_DIRS & set(path.relative_to(ROOT).parts):
                continue
            for n, line in enumerate(text_lines(path), 1):
                if pattern.search(line) and not (allow and rel == "Formula/claudemon.rb" and allow.match(line)):
                    hits.append("%s:%d: %s" % (rel, n, line.strip()[:100]))
        return hits

    def test_no_banned_spelling(self):
        self.assertEqual(self.scan(BANNED, FORMULA_CLASS), [], "use claudeMon (the name) or claudemon (the command)")

    def test_marker_is_not_written_with_the_name_case(self):
        self.assertEqual(self.scan(BAD_MARKER), [], "the settings marker is `# claudemon`")

    def test_the_real_marker_is_still_lowercase(self):
        import sys
        sys.path.insert(0, str(ROOT / "src"))
        try:
            from claudemon.tap import installer as install
        finally:
            sys.path.remove(str(ROOT / "src"))
        self.assertEqual(install.MARK, "# claudemon")

    def test_the_rule_catches_what_it_should(self):
        for bad in ("ClaudeMon", "Claudemon", "claude-mon", "claude_mon", "Claude Mon"):
            self.assertTrue(BANNED.search("x %s y" % bad), bad)
        for fine in ("claudeMon", "claudemon", "claude-monitor", "# claudeMon: a task manager"):
            self.assertFalse(BANNED.search(fine), fine)
        self.assertTrue(BAD_MARKER.search('cmd = "tap # claudeMon"'))
        self.assertTrue(BAD_MARKER.search("cmd = 'tap # claudeMon'"))
        self.assertFalse(BAD_MARKER.search("# claudeMon: a task manager"))
        self.assertFalse(BAD_MARKER.search("# claudeMon's own state"))


if __name__ == "__main__":
    unittest.main()
