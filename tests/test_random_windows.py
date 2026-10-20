"""
Tests for scripts/run_random_windows.py and analysis/random_windows.py.
Run all tests with:

    .venv/bin/python -m unittest discover -s tests -v

1. The windows: the same seed gives the same offsets, each profile its own,
   all inside the range; the run order alternates from window to window.
2. The analysis: training speed from saved worker logs (only inside the
   run), pairing by window, gain, wins, and the files it writes.
No Docker and no Prometheus needed.
"""
import csv
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "analysis"))
import random_windows  # noqa: E402  (analysis/random_windows.py)
import run_random_windows  # noqa: E402  (scripts/run_random_windows.py)


# ----------------------------------------------------------------------
# 1. The windows
# ----------------------------------------------------------------------
class Windows(unittest.TestCase):

    def test_same_seed_same_offsets(self):
        first = run_random_windows.draw_offsets(1, "bursts", 10, 3600)
        self.assertEqual(first, run_random_windows.draw_offsets(1, "bursts", 10, 3600))
        self.assertNotEqual(first, run_random_windows.draw_offsets(2, "bursts", 10, 3600))
        self.assertNotEqual(first, run_random_windows.draw_offsets(1, "sine", 10, 3600))

    def test_offsets_inside_the_range(self):
        offsets = run_random_windows.draw_offsets(7, "sine", 500, 100)
        self.assertTrue(all(isinstance(o, int) and 0 <= o < 100 for o in offsets))

    def test_order_alternates(self):
        self.assertEqual([run_random_windows.window_order(w)[0] for w in range(1, 5)],
                         ["reactive", "proactive", "reactive", "proactive"])
        for window in range(1, 5):
            self.assertEqual(sorted(run_random_windows.window_order(window)),
                             ["proactive", "reactive"])

    def test_windows_csv(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "windows.csv")
            run_random_windows.write_windows(path, "sine", [12, 345], seed=3)
            with open(path) as f:
                rows = list(csv.DictReader(f))
        self.assertEqual(rows, [
            {"profile": "sine", "window": "1", "offset_s": "12", "seed": "3", "first": "reactive"},
            {"profile": "sine", "window": "2", "offset_s": "345", "seed": "3", "first": "proactive"},
        ])


# ----------------------------------------------------------------------
# 2. The analysis, on a made-up profile folder
# ----------------------------------------------------------------------
START = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)


def stamp(seconds):
    """A docker log time stamp, `seconds` after START (nanoseconds, like docker)."""
    return (START + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%S.%f") + "123Z"


def write_run(folder, controller, window, begin, speeds):
    """
    Logs of one run that starts `begin` s after START and lasts 100 s.
    speeds = {worker: steps/s inside the run}; a line before and after the
    run has 999 steps/s, which must not count.
    """
    for worker, speed in speeds.items():
        with open(os.path.join(folder, f"{controller}_{window}_{worker}.log"), "w") as f:
            f.write(f"{stamp(begin - 30)} load t=1 mode=sine intensity=0.500\n")
            f.write(f"{stamp(begin - 5)} t=  10s intensity=0.50 steps/s=  999.0 acc=0.9\n")
            for t in range(10, 100, 10):
                f.write(f"{stamp(begin + t)} t={t:4d}s intensity=0.50 steps/s={speed:7.1f} acc=0.9\n")
            f.write(f"{stamp(begin + 130)} t= 130s intensity=0.50 steps/s=  999.0 acc=0.9\n")
    start = (START + timedelta(seconds=begin)).isoformat(timespec="seconds")
    end = (START + timedelta(seconds=begin + 100)).isoformat(timespec="seconds")
    return {"controller": controller, "repeat": window, "start": start, "end": end, "status": "ok"}


class Analysis(unittest.TestCase):

    def make_profile(self, folder):
        """Three windows; window 3's proactive run failed."""
        run_random_windows.write_windows(os.path.join(folder, "windows.csv"), "bursts",
                                         [100, 2000, 3000], seed=1)
        rows = [
            write_run(folder, "reactive", 1, 0, {"fl-worker-1": 50, "fl-worker-2": 50}),
            write_run(folder, "proactive", 1, 200, {"fl-worker-1": 80, "fl-worker-2": 70}),
            write_run(folder, "proactive", 2, 400, {"fl-worker-1": 40, "fl-worker-2": 50}),
            write_run(folder, "reactive", 2, 600, {"fl-worker-1": 50, "fl-worker-2": 50}),
            write_run(folder, "reactive", 3, 800, {"fl-worker-1": 50, "fl-worker-2": 50}),
            dict(write_run(folder, "proactive", 3, 1000, {"fl-worker-1": 1, "fl-worker-2": 1}),
                 status="exited early with code 1"),
        ]
        with open(os.path.join(folder, "runs.csv"), "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def test_paired_windows_and_summary(self):
        with tempfile.TemporaryDirectory() as folder:
            self.make_profile(folder)
            windows = random_windows.read_profile(folder)
        # window 3 is left out: its proactive run was not ok
        self.assertEqual([(w["window"], w["offset_s"]) for w in windows], [(1, 100), (2, 2000)])
        self.assertEqual([(w["reactive"], w["proactive"]) for w in windows],
                         [(100.0, 150.0), (100.0, 90.0)])
        self.assertEqual([round(w["gain"], 6) for w in windows], [50.0, -10.0])

        s = random_windows.summarize(windows)
        self.assertEqual(s["n"], 2)
        self.assertEqual(s["reactive"][0], 100.0)
        self.assertEqual(s["proactive"][0], 120.0)
        self.assertAlmostEqual(s["gain_mean"], 20.0)
        self.assertEqual((s["gain_min"], s["gain_max"]), (-10.0, 50.0))
        self.assertEqual(s["wins"], 1)

    def test_writes_summary_csv_and_figures(self):
        with tempfile.TemporaryDirectory() as runs, tempfile.TemporaryDirectory() as results:
            os.mkdir(os.path.join(runs, "bursts"))
            self.make_profile(os.path.join(runs, "bursts"))
            argv = ["random_windows.py", "--runs-dir", runs, "--results-dir", results]
            with mock.patch.object(sys, "argv", argv), \
                    mock.patch("builtins.print"):
                random_windows.main()
            with open(os.path.join(results, "summary.md")) as f:
                summary = f.read()
            with open(os.path.join(results, "bursts_windows.csv")) as f:
                rows = list(csv.DictReader(f))
            figures = sorted(os.listdir(os.path.join(results, "figures")))
        # (the last column, the fixed-window gain, comes from results/bursts/comparison.md)
        self.assertIn("| bursts | 2 | 100.0 ± 0.0 | 120.0 ± 42.4 | +20.0% | -10.0% | +50.0% | "
                      "1 of 2 | +20.0% |", summary)
        self.assertEqual([(r["window"], r["seed"], r["gain_pct"]) for r in rows],
                         [("1", "1", "50.00"), ("2", "1", "-10.00")])
        self.assertEqual(figures, ["bursts_boxplot.pdf", "bursts_boxplot.png"])


if __name__ == "__main__":
    unittest.main()
