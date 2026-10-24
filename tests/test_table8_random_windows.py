"""
Tests for scripts/table8_random_windows.py. Run all tests with:

    .venv/bin/python -m unittest discover -s tests -v

The window starts, the errors of one window (pooled over the nodes, as in
table8.md) and the counts over the windows, on made-up forecasts. No
trained models needed.
"""
import os
import sys
import unittest

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import table8_random_windows as t8  # noqa: E402  (scripts/table8_random_windows.py)
from predictors.evaluate import metrics  # noqa: E402


class Windows(unittest.TestCase):

    def test_starts_are_reproducible_and_fit(self):
        starts = t8.sample_starts(200, 1440, 25022, seed=1)
        self.assertEqual(starts, t8.sample_starts(200, 1440, 25022, seed=1))
        self.assertNotEqual(starts, t8.sample_starts(200, 1440, 25022, seed=2))
        self.assertTrue(all(0 <= s <= 25022 - 1440 for s in starts))

    def test_window_errors_are_pooled_over_the_nodes(self):
        rng = np.random.default_rng(0)
        real = rng.integers(0, 50, size=(3, 100, 5)).astype(float)    # some minutes are 0
        predicted = real + rng.normal(0, 3, size=real.shape)
        scores = t8.window_metrics(predicted, real, 40, 20)
        # t+4 is column 3; the window is forecasts 40..59 of all 3 nodes
        expected = metrics(predicted[:, 40:60, 3].ravel(), real[:, 40:60, 3].ravel())
        for metric in ("mape", "mae", "rmse"):
            self.assertAlmostEqual(scores[("t+4", metric)], expected[metric])
        self.assertEqual(t8.full_test_metrics(predicted, real),
                         t8.window_metrics(predicted, real, 0, 100))


def made_up(errors):
    """Per window {model: {(step, metric): error}}; errors = [{model: error}, ...] for every cell."""
    return [{name: {(step, metric): e[name] for step in t8.STEPS for metric, _ in t8.METRICS}
             for name in t8.MODELS} for e in errors]


class Counts(unittest.TestCase):

    def setUp(self):
        self.windows = made_up([
            {"FedAvg-BiGRU": 1, "FedAvg-LSTM": 2, "CentralBiGRU": 3, "CentralLSTM": 4},
            {"FedAvg-BiGRU": 5, "FedAvg-LSTM": 2, "CentralBiGRU": 3, "CentralLSTM": 4},
            {"FedAvg-BiGRU": 5, "FedAvg-LSTM": 6, "CentralBiGRU": 7, "CentralLSTM": 0.5},
        ])

    def test_first_places(self):
        self.assertEqual(t8.first_places(self.windows, "t+3", "mae"),
                         {"FedAvg-BiGRU": 1, "FedAvg-LSTM": 1, "CentralBiGRU": 0, "CentralLSTM": 1})

    def test_bigru_wins(self):
        self.assertEqual(t8.bigru_wins(self.windows, "FedAvg-BiGRU", "FedAvg-LSTM", "t+5", "rmse"), 2)
        self.assertEqual(t8.bigru_wins(self.windows, "CentralBiGRU", "CentralLSTM", "t+5", "rmse"), 2)

    def test_share_below(self):
        self.assertEqual(t8.share_below([1, 2, 3, 4], 2.5), 50)
        self.assertEqual(t8.share_below([1, 2, 3, 4], 0), 0)


if __name__ == "__main__":
    unittest.main()
