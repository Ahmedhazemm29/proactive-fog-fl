"""
Tests for predictors/mape.py: every MAPE reading of decision 3.12 on a few
hand-made minutes with a known answer. Run all tests with:

    .venv/bin/python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from predictors import mape  # noqa: E402

# Real requests 0, 1, 10, 100 with forecasts 5, 2, 11, 90:
# the zero is skipped, the others are off by 100%, 10% and 10%.
REAL = np.array([0.0, 1.0, 10.0, 100.0])
PRED = np.array([5.0, 2.0, 11.0, 90.0])


class Readings(unittest.TestCase):

    def test_skip_only_zeros(self):
        self.assertAlmostEqual(mape.mape(PRED, REAL), 40.0)                    # (100 + 10 + 10) / 3

    def test_skip_below_a_floor(self):
        self.assertAlmostEqual(mape.mape(PRED, REAL, floor=5), 10.0)           # only 10 and 100 count

    def test_floor_is_a_share_of_each_nodes_mean(self):
        # Node mean 27.75: 5% is 1.39, so the minute with 1 request is skipped
        self.assertAlmostEqual(mape.pooled([(PRED, REAL)], floor_share=0.05), 10.0)
        self.assertAlmostEqual(mape.pooled([(PRED, REAL)], floor_share=0.0), 40.0)

    def test_pooled_against_per_node(self):
        a = (np.array([2.0]), np.array([1.0]))                # one minute, 100% off
        b = (np.array([9.0, 11.0]), np.array([10.0, 10.0]))   # two minutes, 10% off each
        self.assertAlmostEqual(mape.pooled([a, b]), 40.0)     # (100 + 10 + 10) / 3 minutes
        self.assertAlmostEqual(mape.per_node([a, b]), 55.0)   # (100 + 10) / 2 nodes

    def test_total_trace(self):
        a = (np.array([1.0, 2.0]), np.array([2.0, 2.0]))
        b = (np.array([3.0, 4.0]), np.array([2.0, 2.0]))
        # Sum: forecasts 4 and 6 against 4 and 4, so 0% and 50%
        self.assertAlmostEqual(mape.of_total([a, b]), 25.0)
        self.assertAlmostEqual(mape.pooled([a, b]), 50.0)     # 50, 0, 50, 100 per minute

    def test_scaled_zero_to_one(self):
        # low 0, span 10: real 5 -> 0.5, forecast 6 -> 0.6, so 20%
        self.assertAlmostEqual(mape.scaled(np.array([6.0]), np.array([5.0]), 0, 10, 0, 1), 20.0)

    def test_scaled_minus_one_to_one(self):
        # A quiet minute lands near -1: real 0 (skipped in real requests) becomes -1, and its
        # forecast 1 becomes -0.8, so it counts as only 20% off. The middle minute (real 5)
        # becomes 0 and is skipped. Real 10 becomes 1 and forecast 9 becomes 0.8: 20%.
        real, pred = np.array([0.0, 5.0, 10.0]), np.array([1.0, 6.0, 9.0])
        self.assertAlmostEqual(mape.scaled(pred, real, 0, 10, -1, 1), 20.0)
        np.testing.assert_allclose(mape.scale(real, 0, 10, -1, 1), [-1.0, 0.0, 1.0])

    def test_implied_mean_traffic(self):
        # A paper with our errors on traffic 3 times as large: MAE x 3, same MAPE -> mean x 3
        self.assertAlmostEqual(mape.implied_mean_traffic(3 * 500, 14, 500, 10000, 14), 30000)
        # Half our MAPE with the same MAE means the traffic must be twice as large
        self.assertAlmostEqual(mape.implied_mean_traffic(500, 7, 500, 10000, 14), 20000)


if __name__ == "__main__":
    unittest.main()
