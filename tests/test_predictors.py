"""
Tests for predictors/ (FedAvg and central workload predictors). Run all tests with:

    .venv/bin/python -m unittest discover -s tests -v

1. Features: day of week, hour, minute and holiday are right for known minutes.
2. Windows never cross a split border, each target is the next 5 minutes, and
   real values come back as exact whole requests (zeros included, for MAPE).
3. The min-max scaler is fitted on the training part only.
4. The server averages weights by number of training windows.
5. The Diebold-Mariano test: 0 for equal errors, clearly positive when a is worse.
6. Model sizes: the BiGRU and LSTM of Table 2 have the expected number of weights.
"""
import os
import sys
import tempfile
import unittest

import numpy as np
import torch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from predictors import data, evaluate, federated, models, training  # noqa: E402


def write_trace(folder, n=1000):
    """A made-up node trace: minute i has i requests, starting Friday 1998-05-01 00:00."""
    path = os.path.join(folder, "node_00.csv")
    minutes = np.datetime64("1998-05-01T00:00") + np.arange(n).astype("timedelta64[m]")
    with open(path, "w") as f:
        f.write("minute_paris,requests\n")
        for m, r in zip(np.datetime_as_string(minutes, unit="m"), range(n)):
            f.write(f"{m},{r}\n")
    return path


class Features(unittest.TestCase):

    def test_known_minutes(self):
        minutes = np.array(["1998-05-01T00:00", "1998-05-01T13:45", "1998-05-04T23:59"], dtype="datetime64[m]")
        table = data.feature_table(minutes, np.array([5.0, 6.0, 7.0]), [np.datetime64("1998-05-01")])
        # Friday = 4 (Monday = 0), Monday = 0; holiday only on 1 May
        np.testing.assert_array_equal(table, [[5, 4, 0, 0, 1], [6, 4, 13, 45, 1], [7, 0, 23, 59, 0]])

    def test_holidays_of_the_trace(self):
        minutes = np.arange(np.datetime64("1998-05-01T00:00"), np.datetime64("1998-07-27T00:00"))
        self.assertEqual([str(d) for d in data.french_holidays(minutes)],
                         ["1998-05-01", "1998-05-08", "1998-05-21", "1998-06-01", "1998-07-14"])


class Windows(unittest.TestCase):

    def setUp(self):
        folder = tempfile.mkdtemp()
        self.node = data.NodeData(write_trace(folder), window=30, holiday_days=[], device="cpu")

    def test_inside_the_split(self):
        for split, (first, end) in self.node.bounds.items():
            starts = self.node.starts[split]
            self.assertEqual(int(starts.min()), first)
            self.assertEqual(int(starts.max()) + 30 + data.HORIZON, end)   # last target minute = end - 1

    def test_target_is_the_next_five_minutes(self):
        x, y = self.node.batch(torch.tensor([100]))
        real = lambda v: self.node.scaler.unscale_requests(v.numpy())    # minute i has i requests
        np.testing.assert_allclose(real(x[0, :, 0]), np.arange(100, 130), atol=1e-3)
        np.testing.assert_allclose(real(y[0]), np.arange(130, 135), atol=1e-3)

    def test_real_values_come_back_exact(self):
        # Requests i % 7 in a fresh trace: the test part has many minutes with 0 requests.
        folder = tempfile.mkdtemp()
        path = write_trace(folder)
        rows = open(path).read().splitlines()
        with open(path, "w") as f:
            f.write("\n".join([rows[0]] + [f"{r.split(',')[0]},{i % 7}" for i, r in enumerate(rows[1:])]) + "\n")
        node = data.NodeData(path, window=30, holiday_days=[], device="cpu")
        _, real = training.predict(models.BiGRU(), node)
        starts = node.starts["test"].numpy()
        expected = (starts[:, None] + 30 + np.arange(data.HORIZON)) % 7
        np.testing.assert_array_equal(real, expected)          # exact, zeros included

    def test_scaler_fitted_on_training_part(self):
        first, end = self.node.bounds["train"]
        self.assertEqual(self.node.scaler.low[0], first)
        self.assertEqual(self.node.scaler.span[0], end - 1 - first)
        self.assertGreater(float(self.node.series[-1, 0]), 1.0)          # test values may go above 1


class FedAvg(unittest.TestCase):

    def test_weighted_average(self):
        a = [np.array([0.0, 0.0]), np.array([1.0])]
        b = [np.array([4.0, 8.0]), np.array([5.0])]
        mean = federated.Server.average([(a, 300), (b, 100)])
        np.testing.assert_allclose(mean[0], [1.0, 2.0])
        np.testing.assert_allclose(mean[1], [2.0])

    def test_weights_round_trip(self):
        model = models.BiGRU()
        copy = models.BiGRU()
        models.set_weights(copy, models.get_weights(model))
        x = torch.randn(3, 30, 5)
        model.eval(), copy.eval()
        torch.testing.assert_close(model(x), copy(x))


class DieboldMariano(unittest.TestCase):

    def test_equal_errors(self):
        e = np.random.default_rng(0).normal(size=500)
        self.assertEqual(evaluate.diebold_mariano(e, e, 3), (0.0, 1.0))

    def test_worse_forecast(self):
        rng = np.random.default_rng(1)
        good = rng.normal(size=2000)
        dm, p = evaluate.diebold_mariano(3 * good, good, 3)
        self.assertGreater(dm, 5)
        self.assertLess(p, 1e-6)

    def test_mape_skips_zeros(self):
        m = evaluate.metrics(np.array([1.0, 2.0, 5.0]), np.array([0.0, 4.0, 5.0]))
        self.assertAlmostEqual(m["mape"], 25.0)           # (50% + 0%) / 2
        self.assertEqual(m["mape_skipped"], 1)
        self.assertAlmostEqual(m["mae"], (1 + 2 + 0) / 3)


class ModelSizes(unittest.TestCase):

    def test_parameter_counts(self):
        # GRU: 3 gates x (5 inputs + 64 recurrent + 2 biases) x 64 units, two directions; LSTM: 4 gates, one
        gru = 2 * 3 * (5 * 64 + 64 * 64 + 2 * 64)
        lstm = 4 * (5 * 64 + 64 * 64 + 2 * 64)
        dense = 64 * 5 + 5
        self.assertEqual(models.parameter_count(models.BiGRU()), gru + dense)
        self.assertEqual(models.parameter_count(models.LSTM()), lstm + dense)
        self.assertEqual(models.model_bytes(models.BiGRU()), 4 * (gru + dense))


if __name__ == "__main__":
    unittest.main()
