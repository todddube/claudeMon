"""Installer and tap tests. Every case runs in a throwaway CLAUDE_CONFIG_DIR, and
the checkout-location cases run from a copy of the sources."""

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = [p.name for p in ROOT.glob("*.py")]


def copy_checkout(dest):
    dest = Path(dest)
    dest.mkdir(parents=True)
    for name in SOURCES:
        shutil.copy2(ROOT / name, dest / name)
    return dest


class Home(unittest.TestCase):
    """A temp ~/.claude plus helpers to run claudemon commands against it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.settings = self.home / "settings.json"
        self.root = ROOT

    def tearDown(self):
        self._tmp.cleanup()

    def env(self, **extra):
        e = dict(os.environ, CLAUDE_CONFIG_DIR=str(self.home))
        e.update(extra)
        return e

    def cli(self, cmd, root=None, **env):
        r = subprocess.run([sys.executable, str(Path(root or self.root) / "claudemon.py"), cmd],
                           env=self.env(**env), capture_output=True, text=True)
        self.assertNotIn("Traceback", r.stderr)
        return (r.stdout + r.stderr).strip()

    def py(self, code, root=None, **env):
        r = subprocess.run([sys.executable, "-c", code], cwd=str(root or self.root), env=self.env(**env),
                           capture_output=True, text=True)
        self.assertNotIn("Traceback", r.stderr, r.stderr)
        return r.stdout.strip()

    def write(self, obj):
        self.settings.write_text(json.dumps(obj) if not isinstance(obj, str) else obj)

    def read(self):
        return json.loads(self.settings.read_text(encoding="utf-8"))

    def command(self):
        return self.read()["statusLine"]["command"]

    def render(self, stdin='{"session_id":"abc"}'):
        """Run the installed status-line command the way Claude Code does (through sh)."""
        r = subprocess.run(["/bin/sh", "-c", self.command()], input=stdin, env=self.env(),
                           capture_output=True, text=True, timeout=20)
        return r.stdout, r.returncode


class Install(Home):
    def test_points_at_the_installed_copy_with_a_marker(self):
        self.write({"statusLine": {"type": "command", "command": "echo hi"}})
        self.assertIn("installed", self.cli("install"))
        cmd = self.command()
        self.assertIn(str(self.home / "claudemon" / "tap.py"), cmd)
        self.assertTrue(cmd.endswith("# claudemon"))
        self.assertTrue((self.home / "claudemon" / "tap.py").exists())
        self.assertEqual(self.render(), ("hi\n", 0))

    def test_checkout_path_with_a_space(self):
        root = copy_checkout(self.tmp / "My Repo")
        original = {"statusLine": {"type": "command", "command": "echo orig"}}
        self.write(original)
        self.assertIn("installed", self.cli("install", root))
        self.assertIn("already", self.cli("install", root))
        self.assertIn("already", self.cli("install", root))
        self.assertEqual(self.command().count("statusline"), 1, "tap nested inside itself")
        backup = json.loads((self.home / "claudemon" / "statusline.backup.json").read_text())
        self.assertEqual(backup["statusLine"], original["statusLine"])
        self.assertIn("removed", self.cli("uninstall", root))
        self.assertEqual(self.read(), original)
        self.assertIn("not installed", self.cli("uninstall", root))

    def test_moving_or_deleting_the_checkout_keeps_the_status_line(self):
        root = copy_checkout(self.tmp / "checkout")
        self.write({"statusLine": {"type": "command", "command": "echo still here"}})
        self.cli("install", root)
        shutil.rmtree(root)
        self.assertEqual(self.render(), ("still here\n", 0))

    def test_a_users_own_tap_py_is_not_taken_for_ours(self):
        mine = {"statusLine": {"type": "command", "command": "python3 ~/bin/tap.py statusline"}}
        self.write(mine)
        self.assertEqual(self.py("import install; print(install.repair())"), "")
        self.assertEqual(self.read(), mine)
        self.assertIn("installed", self.cli("install"))
        self.assertIn("'python3 ~/bin/tap.py statusline'", self.command())
        self.cli("uninstall")
        self.assertEqual(self.read(), mine)

    def test_a_users_hook_mentioning_claudemon_is_left_alone(self):
        """Review: '# claudemon' as a substring used to claim a user's own hook."""
        mine = {"type": "command", "command": "terminal-notifier -message hi # claudemon alerts"}
        self.write({"hooks": {"Notification": [{"hooks": [dict(mine)]}]}})
        self.cli("install")
        hooks = [h for e in self.read()["hooks"]["Notification"] for h in e["hooks"]]
        self.assertIn(mine, hooks)
        self.assertEqual(len(hooks), 2)
        self.cli("uninstall")
        self.assertEqual(self.read(), {"hooks": {"Notification": [{"hooks": [mine]}]}})

    def test_uninstall_keeps_edits_made_after_install(self):
        self.write({"statusLine": {"type": "command", "command": "echo A"}})
        self.cli("install")
        s = self.read()
        s["statusLine"]["command"] = s["statusLine"]["command"].replace("'echo A'", "'echo B'")
        s["statusLine"]["padding"] = 2
        self.write(s)
        self.cli("uninstall")
        self.assertEqual(self.read()["statusLine"], {"type": "command", "command": "echo B", "padding": 2})

    def test_fresh_home_round_trip(self):
        self.cli("install")
        self.assertEqual(self.render(), ("", 0))
        self.cli("uninstall")
        self.assertEqual(self.read(), {})
        self.assertFalse((self.home / "claudemon" / "tap.py").exists())

    def test_symlink_and_mode_are_kept(self):
        real = self.tmp / "dotfiles" / "settings.json"
        real.parent.mkdir()
        real.write_text(json.dumps({"model": "opus"}))
        os.chmod(real, 0o600)
        self.settings.symlink_to(real)
        self.cli("install")
        self.assertTrue(self.settings.is_symlink())
        self.assertEqual(stat.S_IMODE(real.stat().st_mode), 0o600)
        self.assertIn("statusLine", json.loads(real.read_text()))
        self.assertEqual(stat.S_IMODE((self.home / "claudemon").stat().st_mode), 0o700)

    def test_non_ascii_survives_a_latin1_locale(self):
        original = {"env": {"K": "sécret ✓"}, "statusLine": {"type": "command", "command": "echo ✓"}}
        self.write(json.dumps(original, ensure_ascii=False))
        self.cli("install", LC_ALL="en_US.ISO8859-1", LANG="en_US.ISO8859-1", PYTHONUTF8="0")
        self.assertEqual(self.read()["env"], original["env"])
        self.cli("uninstall", LC_ALL="en_US.ISO8859-1", LANG="en_US.ISO8859-1", PYTHONUTF8="0")
        self.assertEqual(self.read(), original)

    def test_unexpected_shapes_are_refused_not_crashed(self):
        for bad in ("[]", "null", '{"statusLine": "echo hi"}', '{"hooks": []}',
                    '{"hooks": {"Notification": {}}}', '{"hooks": {"Notification": ["x"]}}'):
            self.write(bad)
            self.assertIn("unexpected shape", self.cli("install"), bad)
            self.assertIn("unexpected shape", self.cli("uninstall"), bad)
            self.assertEqual(self.settings.read_text(), bad)
            self.assertEqual(self.py("import install; print(install.installed(), repr(install.repair()))"), "False ''")

    def test_unwritable_settings_gives_a_message(self):
        self.write({})
        os.chmod(self.home, 0o500)
        try:
            out = self.cli("install")
        finally:
            os.chmod(self.home, 0o700)
        self.assertIn("cannot", out)

    def test_backups_are_unique_and_pruned(self):
        self.write({"statusLine": {"type": "command", "command": "echo hi"}})
        for _ in range(7):
            self.cli("install")
            self.cli("uninstall")
        backups = list((self.home / "claudemon").glob("settings.*.bak.json"))
        self.assertEqual(len(backups), 10)
        for b in backups:
            self.assertEqual(stat.S_IMODE(b.stat().st_mode), 0o600)

    def test_conflicting_write_is_refused(self):
        self.write({"a": 1})
        out = self.py(
            "import install, json\n"
            "s, raw = install._read()\n"
            "open(install.SETTINGS_FILE, 'w').write(json.dumps({'a': 2}))\n"
            "try:\n    install._save({'a': 3}, raw)\nexcept install.Conflict:\n    print('conflict')\n")
        self.assertEqual(out, "conflict")
        self.assertEqual(self.read(), {"a": 2})


class Migration(Home):
    """Installs made before the tap was copied into ~/.claude/claudemon."""

    def legacy(self, tap_path, original="echo legacy"):
        py = sys.executable
        import shlex
        cmd = "%s %s statusline" % (py, shlex.quote(str(tap_path)))
        if original:
            cmd += " -- " + shlex.quote(original)
        hook = "%s %s hook Notification # claudemon" % (py, shlex.quote(str(tap_path)))
        self.write({"statusLine": {"type": "command", "command": cmd},
                    "hooks": {"Notification": [{"hooks": [{"type": "command", "command": hook}]}]}})

    def test_repair_moves_an_old_install_to_the_copy(self):
        self.legacy(ROOT / "tap.py")
        self.assertIn("re-pointed", self.py("import install; print(install.repair())"))
        self.assertIn(str(self.home / "claudemon" / "tap.py"), self.command())
        self.assertTrue(self.command().endswith("# claudemon"))
        self.assertEqual(self.py("import install; print(repr(install.repair()))"), "''")
        self.assertEqual(self.render(), ("legacy\n", 0))
        hook = self.read()["hooks"]["Notification"][0]["hooks"][0]["command"]
        self.assertIn(str(self.home / "claudemon" / "tap.py"), hook)

    def test_nested_taps_from_the_old_quoting_bug_are_unwrapped(self):
        import shlex
        tap = self.tmp / "My Repo" / "claudemon" / "tap.py"
        inner = "%s %s statusline -- %s" % (sys.executable, shlex.quote(str(tap)), shlex.quote("echo deep"))
        self.legacy(tap, original=inner)
        self.assertEqual(self.py("import install; print(install.unwrap(install._read()[0]['statusLine']['command']))"),
                         "echo deep")
        self.cli("install")
        self.assertEqual(self.command().count("statusline"), 1)
        self.cli("uninstall")
        self.assertEqual(self.read()["statusLine"]["command"], "echo deep")
        self.assertNotIn("hooks", self.read())

    def test_old_install_from_a_deleted_checkout_is_recognised(self):
        """Review: a moved checkout not named claudemon was wrapped a second time."""
        tap = self.tmp / "src" / "cmon" / "tap.py"          # never existed on disk
        self.legacy(tap, original="echo mine")
        self.cli("install")
        self.assertEqual(self.command().count("statusline"), 1)
        self.assertEqual(self.render(), ("mine\n", 0))
        self.cli("uninstall")
        self.assertEqual(self.read(), {"statusLine": {"type": "command", "command": "echo mine"}})

    def test_vanished_interpreter_is_replaced(self):
        self.cli("install")
        p = self.settings
        p.write_text(p.read_text().replace(json.dumps(self.command().split()[0])[1:-1], "/gone/python3"))
        self.assertIn("/gone/", p.read_text())
        self.assertIn("re-pointed", self.py("import install; print(install.repair())"))
        self.assertNotIn("/gone/", p.read_text())

    def test_repair_refreshes_a_stale_copy(self):
        self.cli("install")
        (self.home / "claudemon" / "tap.py").write_text("# old\n")
        self.assertEqual(self.py("import install; print(install.repair())"), "tap updated")
        self.assertEqual((self.home / "claudemon" / "tap.py").read_bytes(), (ROOT / "tap.py").read_bytes())


class Tap(Home):
    def tap(self, *args, stdin="{}"):
        return subprocess.run([sys.executable, str(ROOT / "tap.py"), *args], input=stdin, env=self.env(),
                              capture_output=True, text=True, timeout=20)

    def test_output_and_exit_code_pass_through(self):
        r = self.tap("statusline", "--", "cat; exit 3", stdin='{"session_id":"x"}')
        self.assertEqual((r.stdout, r.returncode), ('{"session_id":"x"}', 3))

    def test_marker_without_a_shell(self):
        r = self.tap("statusline", "--", "cat", "#", "claudemon", stdin="raw")
        self.assertEqual(r.stdout, "raw")

    def test_session_id_cannot_escape_the_status_dir(self):
        self.write({"keep": True})
        self.tap("statusline", stdin='{"session_id":"../../settings"}')
        self.tap("hook", "Notification", stdin='{"session_id":"../../settings"}')
        self.assertEqual(self.read(), {"keep": True})
        self.assertEqual(sorted(p.name for p in self.home.iterdir() if p.name != "claudemon"), ["settings.json"])

    def test_stale_limit_readings_are_not_logged(self):
        for pct in (38, 28, 29, 38, 30, 39, 38, 39):
            self.tap("statusline", stdin=json.dumps({"session_id": "s%d" % pct, "rate_limits": {
                "seven_day": {"used_percentage": pct, "resets_at": 1795000000}}}))
        rows = [json.loads(l) for l in (self.home / "claudemon" / "limits.jsonl").read_text().splitlines()]
        self.assertEqual([r["seven_day"]["pct"] for r in rows], [38, 39])

    def test_without_resets_at_a_drop_is_still_logged(self):
        """Review: with no resets_at every later reading counted as the same window."""
        for pct in (90, 3):
            self.tap("statusline", stdin=json.dumps({"session_id": "a", "rate_limits": {"five_hour": {"used_percentage": pct}}}))
        rows = [json.loads(l) for l in (self.home / "claudemon" / "limits.jsonl").read_text().splitlines()]
        self.assertEqual([r["five_hour"]["pct"] for r in rows], [90, 3])

    def test_an_idle_session_on_the_previous_window_is_stale(self):
        """Review: sessions on old and new windows alternated and defeated the throttle."""
        for _ in range(3):
            for pct, resets in ((95, 1795000000), (4, 1795018000)):
                self.tap("statusline", stdin=json.dumps({"session_id": "s%d" % pct, "rate_limits": {
                    "five_hour": {"used_percentage": pct, "resets_at": resets}}}))
        rows = [json.loads(l) for l in (self.home / "claudemon" / "limits.jsonl").read_text().splitlines()]
        self.assertEqual([r["five_hour"]["pct"] for r in rows], [95, 4])

    def test_a_new_window_is_logged_even_when_lower(self):
        for pct, resets in ((90, 1795000000), (2, 1795604800)):
            self.tap("statusline", stdin=json.dumps({"session_id": "a", "rate_limits": {
                "seven_day": {"used_percentage": pct, "resets_at": resets}}}))
        rows = (self.home / "claudemon" / "limits.jsonl").read_text().splitlines()
        self.assertEqual(len(rows), 2)

    def test_files_are_private(self):
        self.tap("statusline", stdin='{"session_id":"a","rate_limits":{"five_hour":{"used_percentage":5}}}')
        for p in ("status/a.json", "limits.jsonl", "tap_last.json"):
            self.assertEqual(stat.S_IMODE((self.home / "claudemon" / p).stat().st_mode), 0o600, p)

    def test_odd_input_never_breaks_it(self):
        for stdin in ("not json", "[]", '{"session_id": 5}', '{"rate_limits": "x"}', "",
                      '{"session_id":"a","rate_limits":{"five_hour":{"used_percentage":"9"}}}'):
            r = self.tap("statusline", "--", "echo ok", stdin=stdin)
            self.assertEqual((r.stdout, r.returncode, r.stderr), ("ok\n", 0, ""), stdin)
            r = self.tap("hook", "Notification", stdin=stdin)
            self.assertEqual((r.returncode, r.stderr), (0, ""), stdin)


if __name__ == "__main__":
    unittest.main()
