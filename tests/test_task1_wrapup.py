"""
Tests for scripts/task1_wrapup.py. Run all tests with:

    .venv/bin/python -m unittest discover -s tests -v

The ranking, the counts against Table 8 and the window minutes, on made-up
scores. No results files or trained models needed.
"""
import os
import sys
import unittest

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import task1_wrapup as t1  # noqa: E402  (scripts/task1_wrapup.py)

FB, FL, CB, CL = t1.MODELS   # FedAvg-BiGRU, FedAvg-LSTM, CentralBiGRU, CentralLSTM


def scores(order_values):
    """One run where every step and metric has the given {model: value}."""
    return {(name, step, metric): value for name, value in order_values.items()
            for step in t1.STEPS for metric, _ in t1.METRICS}


class Ranking(unittest.TestCase):

    def test_order_is_lowest_error_first(self):
        run = scores({FB: 3.0, FL: 1.0, CB: 4.0, CL: 2.0})
        self.assertEqual(t1.ranking(run, "t+3", "mae"), (FL, CL, FB, CB))

    def test_stability_counts_whole_order_and_best_model(self):
        reference = scores({FB: 1.0, FL: 2.0, CB: 3.0, CL: 4.0})
        runs = {1: scores({FB: 1.0, FL: 2.0, CB: 3.0, CL: 4.0}),   # same order
                2: scores({FB: 1.0, FL: 3.0, CB: 2.0, CL: 4.0}),   # same best only
                3: scores({FB: 9.0, FL: 2.0, CB: 3.0, CL: 4.0})}   # neither
        self.assertEqual(t1.stability(runs, reference, "t+4", "rmse"),
                         {"same_order": 1, "same_best": 2, "n": 3})

    def test_rank_counts_cover_every_run_and_step(self):
        runs = {1: scores({FB: 1.0, FL: 2.0, CB: 3.0, CL: 4.0}),
                2: scores({FB: 4.0, FL: 2.0, CB: 3.0, CL: 1.0})}
        counts = t1.rank_counts(runs, "mape")
        self.assertEqual(counts[FB], [3, 0, 0, 3])      # 1st in run 1, last in run 2, 3 steps each
        self.assertEqual(sum(map(sum, counts.values())), 2 * 3 * 4)

    def test_gap_and_spread(self):
        runs = {1: scores({FB: 9.0, FL: 10.0, CB: 10.0, CL: 11.0}),
                2: scores({FB: 18.0, FL: 20.0, CB: 20.0, CL: 22.0})}
        gap, spread = t1.gap_vs_spread(runs, "t+5", "mae")
        self.assertAlmostEqual(gap, 20.0)     # (11 - 9) / 10 and (22 - 18) / 20
        # every model doubles: sd / mean = 0.7071 x / 1.5 x
        self.assertAlmostEqual(spread, 100 * np.std([1, 2], ddof=1) / 1.5)


class Windows(unittest.TestCase):

    def test_window_minutes_match_windows_csv(self):
        minutes = np.arange("1998-05-01T00:00", "1998-05-02T00:00", dtype="datetime64[m]")
        report = {"split_minutes": {"test": [1000, 1440]}, "chosen_window": 30}
        rows = [{"window": "1", "first_forecast": "5", "length": "60",
                 "first_minute": str(minutes[1035])}]
        self.assertEqual(t1.window_spans(report, rows, minutes), [(1, 1035, 1094)])
        rows[0]["first_minute"] = str(minutes[1036])
        with self.assertRaises(SystemExit):
            t1.window_spans(report, rows, minutes)

    def test_coverage(self):
        spans = [(1, 10, 19), (2, 15, 24)]
        self.assertEqual(t1.coverage(spans, 10, 39), (15, 30, 2))


if __name__ == "__main__":
    unittest.main()
