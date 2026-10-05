"""
Tests for controller/proactive.py. Run all tests with:

    .venv/bin/python -m unittest discover -s tests -v

1. Without --predict-ahead the controller does exactly what it did before
   the option was added. The version from git commit dbd7e91 and the current
   one control the same simulated workers side by side. They must set the
   same limits, print the same lines and write the same CSV.
2. --predict-ahead 0: the budget is split by each line's value now, still
   never below MIN_LIMIT.
3. The command line: 10 s by default, negative values are refused.

Nothing real is touched: the clock, Prometheus and Docker are stand-ins.
"""
import contextlib
import io
import math
import os
import subprocess
import sys
import tempfile
import types
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BEFORE = "dbd7e91"   # the last commit that changed proactive.py before --predict-ahead

sys.path.insert(0, os.path.join(ROOT, "controller"))
import proactive  # noqa: E402  (controller/proactive.py)


# ----------------------------------------------------------------------
# Simulated workers, Prometheus, Docker and clock
# ----------------------------------------------------------------------
class StopRun(Exception):
    """Raised by the fake clock to end the controller's endless loop."""


class FakeWorld:
    """
    Two workers whose demand follows waves half a period apart, as in the
    sine profile. A worker uses at most its limit; the rest of its demand
    shows up as throttled time. Prometheus is away for a moment twice.
    """

    def __init__(self, cycles):
        self.now = 1_790_000_000.0   # the clock, in seconds
        self.cycle = 0
        self.cycles = cycles         # stop after this many cycles
        self.limits = {"fl-worker-1": 0.5, "fl-worker-2": 0.5}
        self.applied = []            # every set_cpus call: (cycle, worker, CPUs)

    def wanted(self, name):
        shift = 0 if name == "fl-worker-1" else math.pi
        return 0.55 + 0.45 * math.sin(2 * math.pi * self.cycle / 24 + shift)

    # Takes the place of the time module.
    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds
        self.cycle += 1
        if self.cycle == self.cycles:
            raise StopRun

    # Takes the place of the Prometheus queries.
    def get_cpu_usage(self):
        if self.cycle in (40, 41):
            raise ConnectionError("Prometheus not reachable")
        usage = {name: 0.9 * min(self.wanted(name), self.limits[name]) for name in self.limits}
        if self.cycle == 70:
            del usage["fl-worker-2"]   # one worker missing from the answer
        return usage

    def get_throttled_seconds_rate(self):
        return {name: max(0.0, self.wanted(name) - self.limits[name]) for name in self.limits}

    # Takes the place of Docker.
    def get_current_limit(self, client, name):
        return self.limits[name]

    def set_cpus(self, name, cpus):
        self.applied.append((self.cycle, name, cpus))
        self.limits[name] = cpus


def load_controller(source, name):
    """Make a module from the text of a proactive.py."""
    module = types.ModuleType(name)
    module.__file__ = proactive.__file__
    exec(compile(source, f"{name}.py", "exec"), module.__dict__)
    return module


def run(module, log_file, cycles=200, **options):
    """Run the controller's main loop in a FakeWorld. Returns (world, printed lines, CSV text)."""
    world = FakeWorld(cycles)
    module.time = world
    module.docker = types.SimpleNamespace(from_env=lambda: None)
    module.get_cpu_usage = world.get_cpu_usage
    module.get_throttled_seconds_rate = world.get_throttled_seconds_rate
    module.get_current_limit = world.get_current_limit
    module.set_cpus = world.set_cpus
    module.LOG_FILE = log_file
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        try:
            module.main(**options)
        except StopRun:
            pass
    with open(log_file) as f:
        csv_text = f.read()
    os.remove(log_file)
    return world, output.getvalue().splitlines(), csv_text


# ----------------------------------------------------------------------
# 1. The default is unchanged
# ----------------------------------------------------------------------
class DefaultUnchanged(unittest.TestCase):

    def test_same_limits_lines_and_csv_as_before(self):
        try:
            before = subprocess.run(["git", "show", f"{BEFORE}:controller/proactive.py"], cwd=ROOT,
                                    capture_output=True, text=True, check=True).stdout
        except (OSError, subprocess.CalledProcessError):
            self.skipTest(f"git commit {BEFORE} is not available")
        with open(proactive.__file__) as f:
            now = f.read()

        with tempfile.TemporaryDirectory() as folder:
            log_file = os.path.join(folder, "proactive_log.csv")   # the same path for both
            world_before, lines_before, csv_before = run(load_controller(before, "before"), log_file)
            world_now, lines_now, csv_now = run(load_controller(now, "now"), log_file)

        # The simulation must really exercise the controller: many changes,
        # limits from MIN_LIMIT (0.1) up to 0.9, and three lost observations.
        applied = [cpus for _, _, cpus in world_before.applied]
        self.assertGreater(len(applied), 100)
        self.assertEqual((min(applied), max(applied)), (proactive.MIN_LIMIT, 0.9))
        self.assertEqual(sum("Restarting history" in line for line in lines_before), 3)

        self.assertEqual(world_before.applied, world_now.applied)
        self.assertEqual(lines_before, lines_now)
        self.assertEqual(csv_before, csv_now)


# ----------------------------------------------------------------------
# 2. --predict-ahead 0
# ----------------------------------------------------------------------
class NoPrediction(unittest.TestCase):

    def test_line_value_now(self):
        # Demand rising by 0.1 every 5 s: the line is exact, 0.7 now and 0.9 in 10 s.
        rising = [(t, 0.2 + 0.02 * t) for t in range(0, 30, 5)]
        self.assertAlmostEqual(proactive.predict(rising), 0.9)
        self.assertAlmostEqual(proactive.predict(rising, 0), 0.7)
        self.assertAlmostEqual(proactive.predict(rising, 5), 0.8)

    def test_still_clipped_at_min_limit(self):
        # Falling to 0.05: below MIN_LIMIT now, and further below in 10 s.
        falling = [(t, 0.55 - 0.02 * t) for t in range(0, 30, 5)]
        self.assertEqual(proactive.predict(falling, 0), proactive.MIN_LIMIT)
        self.assertEqual(proactive.predict(falling), proactive.MIN_LIMIT)

    def test_too_little_history(self):
        self.assertIsNone(proactive.predict([(0, 0.5)] * 5, 0))

    def test_main_loop_uses_the_setting(self):
        """main(0) asks predict() for 0 s ahead every time, main() for 10 s."""
        for options, expected in (({}, 10), ({"predict_ahead": 0}, 0)):
            with self.subTest(options=options):
                with open(proactive.__file__) as f:
                    module = load_controller(f.read(), "now")
                asked = []                    # the `ahead` of every predict() call
                real_predict = module.predict

                def recording_predict(history, ahead):
                    asked.append(ahead)
                    return real_predict(history, ahead)

                module.predict = recording_predict
                with tempfile.TemporaryDirectory() as folder:
                    world, lines, _ = run(module, os.path.join(folder, "log.csv"), cycles=30,
                                          **options)
                self.assertEqual(set(asked), {expected})
                self.assertGreater(len(world.applied), 0)
                self.assertEqual(any("--predict-ahead" in line for line in lines), expected == 0)


# ----------------------------------------------------------------------
# 3. The command line
# ----------------------------------------------------------------------
class CommandLine(unittest.TestCase):

    def test_default_is_10_seconds(self):
        self.assertEqual(proactive.parse_args([]).predict_ahead, 10)

    def test_zero(self):
        self.assertEqual(proactive.parse_args(["--predict-ahead", "0"]).predict_ahead, 0)

    def test_bad_values_are_refused(self):
        for value in ("-1", "nan", "inf", "soon"):
            with self.subTest(value=value):
                with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                    proactive.parse_args(["--predict-ahead", value])


if __name__ == "__main__":
    unittest.main()
