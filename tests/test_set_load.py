"""
Tests for scripts/set_load.py. Run all tests with:

    .venv/bin/python -m unittest discover -s tests -v

1. write_profile() and apply_named_profile() write exactly the same files as
   before "Spike now" was added (git commit c22cdcc), so the workers and
   scripts/run_experiments.py see no difference.
2. A spike is written to load/<worker>.spike.json in the same way, and bad
   spike values are refused.
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BEFORE = "c22cdcc"   # the last commit that changed set_load.py before "Spike now"

sys.path.insert(0, os.path.join(ROOT, "scripts"))
import set_load  # noqa: E402  (scripts/set_load.py)


class FixedClock:
    """Takes the place of datetime in set_load.py, so set_at is the same in every file."""

    @staticmethod
    def now():
        return datetime(2026, 10, 5, 6, 0, 0, tzinfo=timezone(timedelta(hours=3)))


def files_written(module, write):
    """Call write(module) with LOAD_DIR in a new folder; return {file name: text}."""
    with tempfile.TemporaryDirectory() as folder, \
            mock.patch.object(module, "LOAD_DIR", folder), \
            mock.patch.object(module, "datetime", FixedClock):
        write(module)
        files = {}
        for name in sorted(os.listdir(folder)):
            with open(os.path.join(folder, name)) as f:
                files[name] = f.read()
        return files


class SameFilesAsBefore(unittest.TestCase):

    def setUp(self):
        try:
            source = subprocess.run(["git", "show", f"{BEFORE}:scripts/set_load.py"], cwd=ROOT,
                                    capture_output=True, text=True, check=True).stdout
        except (OSError, subprocess.CalledProcessError):
            self.skipTest(f"git commit {BEFORE} is not available")
        self.before = types.ModuleType("set_load_before")
        self.before.__file__ = set_load.__file__   # so it finds load/profiles/ too
        exec(compile(source, "set_load_before.py", "exec"), self.before.__dict__)

    def test_write_profile(self):
        profiles = [{"mode": "constant", "level": 0.25},
                    {"mode": "steps", "steps": [[0, 0.2], [60.0, 0.9]], "repeat": 0}]
        for name in set_load.named_profiles():
            with open(os.path.join(set_load.PROFILES_DIR, f"{name}.json")) as f:
                profiles += json.load(f).values()
        for profile in profiles:
            with self.subTest(profile=profile):
                before = files_written(self.before, lambda m: m.write_profile("fl-worker-1", profile))
                now = files_written(set_load, lambda m: m.write_profile("fl-worker-1", profile))
                self.assertEqual(list(before), ["fl-worker-1.json"])   # and no .tmp file left
                self.assertEqual(before, now)

    def test_apply_named_profile(self):
        for name in set_load.named_profiles():
            with self.subTest(profile=name):
                before = files_written(self.before, lambda m: m.apply_named_profile(name))
                now = files_written(set_load, lambda m: m.apply_named_profile(name))
                self.assertEqual(list(before), ["fl-worker-1.json", "fl-worker-2.json"])
                self.assertEqual(before, now)


class Spike(unittest.TestCase):

    def test_write_spike(self):
        files = files_written(set_load, lambda m: m.write_spike("fl-worker-2", 0.5, 30.0))
        self.assertEqual(list(files), ["fl-worker-2.spike.json"])   # and no .tmp file left
        self.assertEqual(json.loads(files["fl-worker-2.spike.json"]),
                         {"height": 0.5, "duration": 30.0,
                          "set_at": FixedClock.now().astimezone().isoformat(timespec="seconds")})

    def command_line(self, *arguments):
        """Run set_load.py with these arguments. Returns ({file name: content}, exit message)."""
        stopped = []

        def run(module):
            with mock.patch.object(sys, "argv", ["set_load.py", *arguments]), \
                    contextlib.redirect_stdout(io.StringIO()):
                try:
                    module.main()
                except SystemExit as stop:
                    stopped.append(str(stop.code))

        files = {name: json.loads(text) for name, text in files_written(set_load, run).items()}
        return files, (stopped[0] if stopped else None)

    def test_command_line(self):
        files, stopped = self.command_line("all", "spike", "--height", "0.7", "--duration", "15")
        self.assertIsNone(stopped)
        self.assertEqual(sorted(files), ["fl-worker-1.spike.json", "fl-worker-2.spike.json"])
        self.assertEqual(files["fl-worker-1.spike.json"]["height"], 0.7)
        self.assertEqual(files["fl-worker-1.spike.json"]["duration"], 15.0)

        files, _ = self.command_line("fl-worker-1", "spike")
        spike = files["fl-worker-1.spike.json"]
        self.assertEqual((spike["height"], spike["duration"]), (0.5, 30.0))   # the defaults

    def test_bad_spike_is_refused(self):
        for arguments in (["--height", "1.5"], ["--height", "-0.1"], ["--duration", "0.5"]):
            with self.subTest(arguments=arguments):
                files, stopped = self.command_line("fl-worker-1", "spike", *arguments)
                self.assertEqual(files, {})
                self.assertTrue(stopped.startswith("not changed:"), stopped)


class Offset(unittest.TestCase):

    def test_offset_is_added_to_both_workers(self):
        plain = files_written(set_load, lambda m: m.apply_named_profile("bursts"))
        shifted = files_written(set_load, lambda m: m.apply_named_profile("bursts", offset=1234))
        for worker_file in ("fl-worker-1.json", "fl-worker-2.json"):
            self.assertEqual(json.loads(shifted[worker_file]),
                             dict(json.loads(plain[worker_file]), offset=1234))

    def test_negative_offset_is_a_problem(self):
        self.assertEqual(set_load.check({"mode": "constant", "level": 0.5, "offset": -1}),
                         ["offset must not be negative"])


if __name__ == "__main__":
    unittest.main()
