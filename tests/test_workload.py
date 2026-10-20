"""
Tests for workload/workload.py. Run all tests with:

    .venv/bin/python -m unittest discover -s tests -v

1. Without a new spike, the worker does exactly what it did before "Spike
   now" was added. The version from git commit c22cdcc and the current one
   run side by side through the same load-file changes (every named profile
   of both workers, set_load.py's defaults, broken files, a replay, ...).
   They must print exactly the same lines: the intended load of every
   second, the profile changes and the training speed.
2. "Spike now" adds a spike on top of the running profile without
   restarting it, stops after its duration, and is ended by a new profile.

The real worker trains a model and sleeps. Here the time is faked instead:
the clock only moves when the worker "trains" (0.02 s per step) or sleeps,
so a run of an hour takes a few seconds and gives the same result every time.
scikit-learn is not needed (.venv does not have it): a stand-in is used.
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PROFILES_DIR = os.path.join(ROOT, "load", "profiles")
BEFORE = "c22cdcc"   # the last commit that changed workload.py before "Spike now"

sys.path.insert(0, os.path.join(ROOT, "scripts"))
from set_load import build_parser  # noqa: E402  (scripts/set_load.py)


# ----------------------------------------------------------------------
# Stand-ins for the clock and the model
# ----------------------------------------------------------------------
class StopRun(Exception):
    """Raised by the fake clock to end the worker's endless loop."""


class FakeClock:
    """Takes the place of the time module. It only moves when the worker trains or sleeps."""

    def __init__(self, seconds, events):
        self.now = 1000.0
        self.seconds = seconds    # stop after this many one-second slots
        self.events = events      # {slot: function}, run just before that slot
        self.slot = 0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        # The worker sleeps once at the end of every slot.
        self.now += seconds
        self.slot += 1
        if self.slot == self.seconds:
            raise StopRun
        if self.slot in self.events:
            self.events[self.slot]()


class FakeModel:
    """Takes the place of SGDClassifier: one training step takes 0.02 s."""

    def __init__(self, clock):
        self.clock = clock

    def partial_fit(self, X, y, classes):
        self.clock.now += 0.02

    def score(self, X, y):
        return 0.5


# ----------------------------------------------------------------------
# Loading and running a version of the worker
# ----------------------------------------------------------------------
def load_worker(source, name):
    """Make a module from the text of a workload.py, with stand-ins for scikit-learn."""
    stand_ins = {part: types.ModuleType(part)
                 for part in ("sklearn", "sklearn.datasets", "sklearn.linear_model")}
    stand_ins["sklearn.datasets"].load_digits = None          # replaced in run()
    stand_ins["sklearn.linear_model"].SGDClassifier = None    # replaced in run()
    module = types.ModuleType(name)
    with mock.patch.dict(sys.modules, stand_ins):
        exec(compile(source, f"{name}.py", "exec"), module.__dict__)
    return module


def run(module, folder, seconds, events):
    """
    Run the worker's main loop for `seconds` fake seconds, with its load file
    in `folder`. events: {slot: function}, for example to change the load
    file; slot 0 is run before the worker starts. Returns the printed lines.
    """
    clock = FakeClock(seconds, events)
    module.time = clock
    module.load_digits = lambda return_X_y: (np.ones((20, 64)), np.arange(20) % 10)
    module.SGDClassifier = lambda **options: FakeModel(clock)
    module.LOAD_FILE = os.path.join(folder, "fl-worker-1.json")
    module.SPIKE_FILE = os.path.join(folder, "fl-worker-1.spike.json")  # new version only
    if 0 in events:
        events[0]()
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        try:
            module.main()
        except StopRun:
            pass
    return output.getvalue().splitlines()


def write(path, data):
    with open(path, "w") as f:
        f.write(data if isinstance(data, str) else json.dumps(data))


def load_values(lines):
    """[(t, mode, intensity), ...] from the 'load t=... mode=... intensity=...' lines."""
    values = []
    for line in lines:
        if line.startswith("load t="):
            t, mode, intensity = (part.split("=")[1] for part in line.split()[1:])
            values.append((int(t), mode, intensity))
    return values


# ----------------------------------------------------------------------
# 1. Every existing profile behaves exactly as before
# ----------------------------------------------------------------------
def profile_changes(folder):
    """
    The load-file changes of one long test run: ({slot: function}, its length
    in seconds, the number of profiles it sets).
    No file at the start (default sine), broken files, every named profile of
    both workers for 150 s each, set_load.py's defaults of every mode,
    the same profile again (a replay) and a deleted file.
    """
    load = os.path.join(folder, "fl-worker-1.json")
    events = {
        20: lambda: write(load, "{ not json"),
        30: lambda: write(load, {"mode": "wobble"}),
        40: lambda: write(load, {"mode": "bursts", "gap": 0.5}),
    }
    profiles = []
    for name in sorted(os.listdir(PROFILES_DIR)):
        with open(os.path.join(PROFILES_DIR, name)) as f:
            profiles += json.load(f).values()
    for mode in ("sine", "noisy_sine", "bursts", "steps", "constant"):
        defaults = vars(build_parser().parse_args(["fl-worker-1", mode]))
        profiles.append({k: v for k, v in defaults.items() if k != "worker"})
    slot = 60
    for number, profile in enumerate(profiles):
        events[slot] = lambda p=dict(profile, set_at=f"change {number}"): write(load, p)
        slot += 150
    events[slot] = lambda: write(load, dict(profiles[0], set_at="replay"))
    events[slot + 100] = lambda: os.remove(load)
    return events, slot + 200, len(profiles)


class SameAsBefore(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        try:
            before = subprocess.run(["git", "show", f"{BEFORE}:workload/workload.py"], cwd=ROOT,
                                    capture_output=True, text=True, check=True).stdout
        except (OSError, subprocess.CalledProcessError):
            raise unittest.SkipTest(f"git commit {BEFORE} is not available")
        with open(os.path.join(ROOT, "workload", "workload.py")) as f:
            now = f.read()
        cls.before = load_worker(before, "workload_before")
        cls.now = load_worker(now, "workload_now")

    def compare(self, old_spike_file):
        """Run both versions through the same changes; their output must be identical."""
        outputs = []
        with tempfile.TemporaryDirectory() as base:
            # The same folder for both versions: problem lines contain its path.
            folder = os.path.join(base, "load")
            for module in (self.before, self.now):
                shutil.rmtree(folder, ignore_errors=True)
                os.mkdir(folder)
                events, seconds, profiles = profile_changes(folder)
                if old_spike_file:   # a spike file from before the start must be ignored
                    spike = os.path.join(folder, "fl-worker-1.spike.json")
                    events[0] = lambda: write(spike, {"height": 0.5, "duration": 30})
                outputs.append(run(module, folder, seconds, events))
        before, now = outputs

        # The test must really cover every mode and the profile changes.
        self.assertEqual({mode for _, mode, _ in load_values(before)},
                         {"sine", "noisy_sine", "bursts", "steps", "constant"})
        # the default at the start, every profile, and the replay
        self.assertEqual(sum(line.startswith("load profile:") for line in before), profiles + 2)
        self.assertEqual(sum(line.startswith("load file problem") for line in before), 3)
        self.assertGreater(sum("steps/s=" in line for line in before), 200)

        for number, (line_before, line_now) in enumerate(zip(before, now)):
            self.assertEqual(line_before, line_now, f"first difference in line {number}")
        self.assertEqual(len(before), len(now))

    def test_profiles_unchanged(self):
        self.compare(old_spike_file=False)

    def test_spike_file_from_before_the_start_is_ignored(self):
        self.compare(old_spike_file=True)


# ----------------------------------------------------------------------
# 2. "Spike now"
# ----------------------------------------------------------------------
class SpikeNow(unittest.TestCase):

    def setUp(self):
        with open(os.path.join(ROOT, "workload", "workload.py")) as f:
            self.worker = load_worker(f.read(), "workload_now")

    def test_spike_file_lives_next_to_the_load_file(self):
        with mock.patch.dict(os.environ, {"LOAD_FILE": "/load/fl-worker-2.json"}):
            with open(os.path.join(ROOT, "workload", "workload.py")) as f:
                worker = load_worker(f.read(), "workload_env")
        self.assertEqual(worker.SPIKE_FILE, "/load/fl-worker-2.spike.json")

    def test_spike_on_top_of_the_running_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            load = os.path.join(folder, "fl-worker-1.json")
            spike = os.path.join(folder, "fl-worker-1.spike.json")
            events = {
                0: lambda: write(load, {"mode": "constant", "level": 0.3}),
                10: lambda: write(spike, {"height": 0.5, "duration": 5, "set_at": "a"}),
                30: lambda: write(spike, {"height": 1.0, "duration": 20, "set_at": "b"}),
                35: lambda: write(load, {"mode": "constant", "level": 0.4}),  # ends the spike
                50: lambda: write(spike, "{ not json"),
                55: lambda: write(spike, {"height": 0.2, "duration": 3, "set_at": "c"}),
            }
            lines = run(self.worker, folder, 70, events)
        values = load_values(lines)

        # The profile kept running through both spikes: t never started again before 35.
        self.assertEqual([t for t, _, _ in values[:35]], list(range(35)))
        self.assertEqual([t for t, _, _ in values[35:]], list(range(35)))
        # 0.3, spike +0.5 for 5 s, 0.3, spike +1.0 (at most 1.0) until the new
        # profile ends it at 35, then 0.4 with a short spike +0.2 at 55-57.
        expected = (["0.300"] * 10 + ["0.800"] * 5 + ["0.300"] * 15 + ["1.000"] * 5
                    + ["0.400"] * 20 + ["0.600"] * 3 + ["0.400"] * 12)
        self.assertEqual([intensity for _, _, intensity in values], expected)
        self.assertEqual([line for line in lines if line.startswith("spike")], [
            "spike: +0.50 for 5 s",
            "spike: +1.00 for 20 s",
            f"spike file problem, ignored: {spike}: Expecting property name enclosed in "
            "double quotes: line 1 column 3 (char 2)",
            "spike: +0.20 for 3 s",
        ])

    def test_bad_spike_values_are_refused(self):
        for bad in ({"height": 1.5, "duration": 10}, {"height": 0.5, "duration": 0},
                    {"height": 0.5}, {"height": "high", "duration": 10}):
            with self.subTest(spike=bad):
                with self.assertRaises(Exception):
                    self.worker.check_spike(bad)


# ----------------------------------------------------------------------
# 3. "offset": a profile that starts at a later t (random windows)
# ----------------------------------------------------------------------
class Offset(unittest.TestCase):

    def setUp(self):
        with open(os.path.join(ROOT, "workload", "workload.py")) as f:
            self.worker = load_worker(f.read(), "workload_now")

    def values(self, profile, seconds):
        with tempfile.TemporaryDirectory() as folder:
            load = os.path.join(folder, "fl-worker-1.json")
            lines = run(self.worker, folder, seconds, {0: lambda: write(load, profile)})
        return load_values(lines)

    def test_offset_plays_the_later_part_of_the_profile(self):
        # 0.2 until t = 500, 0.9 until 530, then 0.4. With offset 500 the
        # worker starts at t = 500, so it never plays the 0.2 part.
        profile = {"mode": "steps", "steps": [[0, 0.2], [500, 0.9], [530, 0.4]], "offset": 500}
        values = self.values(profile, 60)
        self.assertEqual(values[0][0], 500)
        self.assertGreaterEqual(values[-1][0], 555)
        # (the fake clock's t can be a fraction of a second off at the step itself)
        self.assertTrue(all(i == "0.900" for t, _, i in values if t < 529))
        self.assertTrue(all(i == "0.400" for t, _, i in values if t > 530))

    def test_negative_offset_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            load = os.path.join(folder, "fl-worker-1.json")
            lines = run(self.worker, folder, 3,
                        {0: lambda: write(load, {"mode": "constant", "level": 0.3, "offset": -5})})
        self.assertIn("offset must not be negative", lines[0])
        self.assertEqual(load_values(lines)[0][1], "sine")   # kept the default profile


if __name__ == "__main__":
    unittest.main()
