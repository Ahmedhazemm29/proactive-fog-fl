"""
Tests for the extra live windows of step 4B (no Docker, no model needed). Run
all tests with:

    .venv/bin/python -m unittest discover -s tests -v

1. live_prepare.first_minute: the default window around the busiest half
   hour, and --start.
2. live_windows: the guard and the calm, rise and spiky rules on made-up
   traffic, and the shape numbers of one window.
3. live_windows_report: the claim check and the wording of the answers.
"""
import os
import sys
import unittest

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import live_prepare  # noqa: E402
import live_windows  # noqa: E402
import live_windows_report  # noqa: E402


# ----------------------------------------------------------------------
# 1. The first minute of a window
# ----------------------------------------------------------------------
class FirstMinute(unittest.TestCase):
    def setUp(self):
        self.stamps = np.arange("1998-07-20T00:00", "1998-07-20T10:00", dtype="datetime64[m]")   # 600 minutes
        self.traffic = np.full(600, 100.0)
        self.traffic[400:430] = 500.0                    # the busiest half hour: minutes 400 to 429

    def test_default_is_centred_on_the_busiest_half_hour(self):
        self.assertEqual(live_prepare.first_minute(self.stamps, self.traffic, None, 180), 415 - 90)

    def test_start(self):
        self.assertEqual(live_prepare.first_minute(self.stamps, self.traffic, "1998-07-20 02:05", 180), 125)

    def test_start_outside_the_test_minutes(self):
        with self.assertRaises(AssertionError):
            live_prepare.first_minute(self.stamps, self.traffic, "1998-07-21 02:05", 180)


# ----------------------------------------------------------------------
# 2. The window rule
# ----------------------------------------------------------------------
def made_up():
    """
    3,000 minutes: 1,400 busy ones with small noise, a slow fall, then 1,400
    quiet ones. The busy part has a flat stretch, a rise of 600 and a drop of
    700. The quiet part has a jump of about 30 times its mean: noise that the
    guard must skip.
    """
    rng = np.random.default_rng(0)
    x = 1000 + 10 * rng.random(3000)
    x[100:300] = 1100                                    # perfectly flat
    x[500:530] += 600                                    # a rise from minute 499 to 500, then slowly back
    x[530:560] += np.linspace(600, 0, 30)
    x[800:830] -= 700                                    # a drop from minute 799 to 800, then slowly back
    x[830:860] -= np.linspace(700, 0, 30)
    x[1400:1600] = np.linspace(1000, 5, 200)             # slowly quiet
    x[1600:] = 5 + rng.random(1400)
    x[2300] = 200
    return x


class Rule(unittest.TestCase):
    def test_guard(self):
        mean, _, _, busy = live_windows.scores(made_up(), 180, 3)
        self.assertTrue(busy[0])                         # busy minutes pass
        self.assertFalse(busy[2300 - 90 - 3])            # the quiet jump does not
        self.assertTrue(np.all(mean[~busy] < mean[busy].min()))

    def test_calm_rise_and_spiky(self):
        best = live_windows.best(made_up(), 180, 3)
        self.assertEqual(best["calm"], (100, 1.0))      # the flat stretch: peak/mean 1
        self.assertEqual(best["rise"][0], 500 - 90)      # centred: the rise goes from window minute 89 to 90
        self.assertEqual(best["spiky"][0], 800 - 90)     # the drop is bigger, relative to its window's mean
        self.assertGreater(best["rise"][1], 0)

    def test_warmup_fits(self):
        x = 1000 + 10 * np.random.default_rng(1).random(400)
        x[92] += 2000                                    # one busy minute: a rise into minute 92, a drop after it
        best = live_windows.best(x, 180, 3)
        self.assertEqual(best["spiky"][0], 3)            # the drop, centred: the earliest window with 3 warm-up minutes
        self.assertGreaterEqual(best["rise"][0], 3)      # the rise would need a window from minute 2: too early

    def test_describe(self):
        shape = live_windows.describe(np.array([10.0, 20.0, 5.0, 5.0]))
        self.assertEqual((shape["mean"], shape["peak"], shape["peak_mean"]), (10.0, 20.0, 2.0))
        self.assertEqual((shape["biggest_jump"], shape["biggest_jump_pct"], shape["biggest_jump_to_minute"]),
                         (-15.0, 150.0, 2))


# ----------------------------------------------------------------------
# 3. The answers of the windows report
# ----------------------------------------------------------------------
def rows(planner_u, khpa_u, none_zero=()):
    """Table 11 rows of one window. none_zero: the metrics where no autoscaling has 0."""
    same = {"theta_o": 5.0, "t_o": 20.0, "actions": 10, "speedup_zero": []}
    return {"none": dict(same, theta_u=8.0, t_u=10.0, speedup=1.0, speedup_zero=list(none_zero)),
            "khpa": dict(same, theta_u=khpa_u, t_u=30.0, speedup=2.0),
            "planner": dict(same, theta_u=planner_u, t_u=3.0, speedup=3.0)}


class Answers(unittest.TestCase):
    def test_claim_holds_per_window(self):
        results = {"original": {"rows": rows(0.3, 4.8)}, "calm": {"rows": rows(5.0, 4.8)},
                   "spiky": {"rows": rows(0.3, 4.8, none_zero=["theta_o"])},
                   "rise": {"rows": {"none": {}, "planner": {}}}}   # a skipped run: not counted
        fewer, higher = live_windows_report.CLAIMS[0][1], live_windows_report.CLAIMS[1][1]
        self.assertEqual(live_windows_report.holds(results, fewer), (["original", "spiky"], ["calm"], []))
        self.assertEqual(live_windows_report.holds(results, higher), (["original", "calm"], [], ["spiky"]))

    def test_winner(self):
        winner = live_windows_report.winner
        self.assertEqual([winner(3.9, 2.6, []), winner(1.0, 1.3, []), winner(2.0, 2.0, []),
                          winner(0.0, 0.0, ["theta_o", "t_o"])], ["planner", "KHPA", "tie", "not defined"])

    def test_wording(self):
        listing, sentence = live_windows_report.listing, live_windows_report.winner_sentence
        self.assertEqual([listing([]), listing(["calm"]), listing(["original", "calm", "rise"])],
                         ["none", "calm", "original, calm and rise"])
        self.assertEqual(sentence({"original": "planner", "calm": "planner"}, 2),
                         "The planner has the higher εn in all 2 windows.")
        self.assertEqual(sentence({"original": "planner", "calm": "KHPA", "rise": "planner"}, 3),
                         "KHPA wins in calm. The planner wins in original and rise.")
        self.assertEqual(sentence({"original": "planner", "calm": "not defined"}, 2),
                         "The planner wins in original. In calm εn is not defined, because no autoscaling has "
                         "a θ or T of 0 there.")
        self.assertEqual(live_windows_report.when("1998-07-20T22:45", "1998-07-21T01:44"),
                         "20 Jul 22:45 to 21 Jul 01:44")
        self.assertEqual(live_windows_report.when("1998-07-23T07:30", "1998-07-23T10:29"), "23 Jul 07:30 to 10:29")


if __name__ == "__main__":
    unittest.main()
