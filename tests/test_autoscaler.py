"""
Tests for autoscaler/ (the simulated scalers of step 4A). Run all tests with:

    .venv/bin/python -m unittest discover -s tests -v

1. Planner (Algorithm 3): cooldowns after a scale-up and a scale-down,
   scale-up with the max of 3 forecasts, the SDR rule, Pods_min, and no
   scale-up from the scale-down branch.
2. KHPA: pods for the last observed minute, at least Pods_min.
3. Metrics (Eqs. 14 to 18) on a tiny hand-made example, and εn when a
   metric is 0.
"""
import math
import os
import sys
import unittest

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from autoscaler import metrics, scalers  # noqa: E402

S = scalers.Settings()          # Table 3: 500 requests per pod, min 5, CDT 3 and 5, SDR 0.3


def flat(load, minutes):
    """A forecast that says `load` for all 5 future minutes, every minute."""
    return np.full((minutes, 5), float(load))


class Planner(unittest.TestCase):

    def test_scale_up_uses_max_of_three(self):
        # t+1 needs 6 pods (> 5), so scale up with the max of t+1 .. t+3 = 6000 -> 12 pods, not 9000 -> 18
        forecast = np.array([3000.0, 4000.0, 6000.0, 9000.0, 9000.0])
        self.assertEqual(scalers.planner_step(forecast, 5, S), 12)

    def test_cooldown_after_scale_up(self):
        # Minute 0: up to 20 pods. Minutes 1 and 2: locked although demand falls. Minute 3: free again.
        forecasts = np.vstack([flat(10000, 1), flat(0, 5)])
        pods, ups, downs = scalers.planner(forecasts, S, start_pods=10)
        self.assertEqual(list(pods), [20, 20, 20, 6, 6, 6])
        self.assertEqual((ups, downs), (1, 1))

    def test_cooldown_after_scale_down(self):
        # Minute 0: need 4, so 15 - floor(11 * 0.7) = 8. Minutes 1 to 4: locked although demand rises.
        # Minute 5: free again.
        forecasts = np.vstack([flat(2000, 1), flat(10000, 6)])
        pods, ups, downs = scalers.planner(forecasts, S, start_pods=15)
        self.assertEqual(list(pods), [8, 8, 8, 8, 8, 20, 20])
        self.assertEqual((ups, downs), (1, 1))

    def test_sdr_rule(self):
        # 20 pods, max of the next 5 needs 4: remove floor(16 * 0.7) = 11 -> 9
        self.assertEqual(scalers.planner_step(np.full(5, 2000.0), 20, S), 9)
        # 10 pods, need 9: floor(1 * 0.7) = 0, so nothing changes and no cooldown starts
        pods, ups, downs = scalers.planner(flat(4500, 3), S, start_pods=10)
        self.assertEqual(list(pods), [10, 10, 10])
        self.assertEqual((ups, downs), (0, 0))

    def test_pods_min(self):
        # 8 pods, no traffic: 8 - floor(8 * 0.7) = 3, raised to Pods_min = 5
        self.assertEqual(scalers.planner_step(np.zeros(5), 8, S), 5)
        # a negative forecast is treated the same way
        self.assertEqual(scalers.planner_step(np.full(5, -700.0), 8, S), 5)

    def test_no_scale_up_from_the_scale_down_branch(self):
        # t+1 needs 2 pods (< 10), but t+5 needs 16: keep 10 pods
        forecast = np.array([1000.0, 1000.0, 1000.0, 1000.0, 8000.0])
        self.assertEqual(scalers.planner_step(forecast, 10, S), 10)


class Khpa(unittest.TestCase):

    def test_last_minute_and_pods_min(self):
        # last_minute[t] = traffic of minute t-1
        pods, ups, downs = scalers.khpa(np.array([5200.0, 9000.0, 100.0, 100.0, 100.0, 100.0]), S, start_pods=5)
        # 11 pods; locked 3 minutes; then 1 pod wanted, but at least 5
        self.assertEqual(list(pods), [11, 11, 11, 5, 5, 5])
        self.assertEqual((ups, downs), (1, 1))

    def test_requested_pods(self):
        np.testing.assert_array_equal(scalers.requested_pods([0, 1, 500, 501], 500), [1, 1, 1, 2])


class Metrics(unittest.TestCase):

    def test_hand_example(self):
        requested = [2, 4, 5, 10]
        provisioned = [4, 4, 4, 5]      # 2 extra, right, 1 missing, 5 missing
        m = metrics.elasticity(requested, provisioned)
        self.assertAlmostEqual(m["theta_u"], 100 * (1 / 5 + 5 / 10) / 4)      # 17.5
        self.assertAlmostEqual(m["theta_o"], 100 * (2 / 2) / 4)               # 25
        self.assertAlmostEqual(m["t_u"], 50.0)
        self.assertAlmostEqual(m["t_o"], 25.0)

    def test_elastic_speedup(self):
        fixed = {"theta_u": 4.0, "theta_o": 9.0, "t_u": 1.0, "t_o": 1.0}
        auto = {"theta_u": 1.0, "theta_o": 1.0, "t_u": 1.0, "t_o": 1.0}
        value, zero = metrics.elastic_speedup(auto, fixed)
        self.assertAlmostEqual(value, math.sqrt(6))          # (4 * 9)^(1/4)
        self.assertEqual(zero, [])
        self.assertEqual(metrics.elastic_speedup(fixed, fixed)[0], 1.0)

    def test_elastic_speedup_with_a_zero(self):
        fixed = {"theta_u": 4.0, "theta_o": 9.0, "t_u": 1.0, "t_o": 1.0}
        never_under = {"theta_u": 0.0, "theta_o": 1.0, "t_u": 0.0, "t_o": 1.0}
        value, zero = metrics.elastic_speedup(never_under, fixed)
        self.assertEqual(value, math.inf)
        self.assertEqual(zero, ["theta_u", "t_u"])


if __name__ == "__main__":
    unittest.main()
