"""
Tests for scripts/synthetic_traces.py. Run all tests with:

    .venv/bin/python -m unittest discover -s tests -v

1. The fast ACF update in match_acf() gives the same ACF error as computing
   the whole ACF again with the FFT.
2. Step 2 only reorders values: the synthetic trace has exactly the values
   of X_init, so the distribution from step 1 is kept.
3. --cdf empirical draws real values with replacement, a different mix per seed.
4. The 1/lag weights sum to 1 and count short lags most.
5. --resume continues a saved trace: same values, iterations add up, and a
   trace with other values is refused.
"""
import contextlib
import io
import os
import sys
import types
import unittest

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import synthetic_traces as st  # noqa: E402  (scripts/synthetic_traces.py)


def settings(**changes):
    """The command-line settings match_acf() reads, small enough for a quick test."""
    values = dict(S=2, weights="lag", eps=0.0, lags=50, short_lags=10, short_tol=0.0,
                  day_lag=50, day_tol=0.0, max_iter=20_000)
    values.update(changes)
    return types.SimpleNamespace(**values)


def smooth_trace(n=2000, seed=0):
    """A made-up trace with a strong ACF: a slow wave plus noise, as whole requests."""
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    return np.round(1000 + 500 * np.sin(2 * np.pi * t / 300) + rng.normal(0, 50, n)).astype(np.int64)


class MatchAcf(unittest.TestCase):

    def test_fast_update_equals_fft(self):
        x = smooth_trace()
        for S in (2, 5):
            with self.subTest(S=S):
                rng = np.random.default_rng(1)
                x_init = rng.choice(x, len(x))
                y, info = st.match_acf(x, x_init, settings(S=S), rng)
                self.assertGreater(info["accepted"], 100)          # it really changed the trace
                self.assertAlmostEqual(info["acf_error_tracked"], info["acf_error_final"], places=12)

    def test_only_reorders_values(self):
        x = smooth_trace()
        rng = np.random.default_rng(2)
        x_init = rng.choice(x, len(x))
        y, info = st.match_acf(x, x_init, settings(), rng)
        self.assertEqual(sorted(y.tolist()), sorted(x_init.tolist()))
        self.assertLess(info["acf_error_final"], info["acf_error_init"])

    def test_stops_at_the_target(self):
        x = smooth_trace()
        rng = np.random.default_rng(3)
        y, info = st.match_acf(x, rng.choice(x, len(x)),
                               settings(eps=1.0, short_tol=1.0, day_tol=1.0, max_iter=10**6), rng)
        self.assertEqual(info["iterations"], 0)   # an easy target is met before the first try


class Resume(unittest.TestCase):

    def test_continue_a_saved_trace(self):
        x = smooth_trace()
        cdf = {"name": "empirical"}
        with contextlib.redirect_stdout(io.StringIO()):
            x_init, first, info1 = st.make_node(3, x, cdf, settings(max_iter=5_000))
            again, second, info2 = st.make_node(3, x, cdf, settings(max_iter=5_000), resume=(first, info1))
        self.assertTrue(np.array_equal(again, x_init))        # X_init is drawn again, the same
        self.assertEqual(sorted(second.tolist()), sorted(x_init.tolist()))
        self.assertEqual(info2["iterations"], 10_000)          # 5,000 + 5,000
        self.assertEqual(info2["acf_error_x_init"], info1["acf_error_x_init"])
        self.assertAlmostEqual(info2["acf_error_at_start"], info1["acf_error_final"], places=12)
        self.assertLess(info2["acf_error_final"], info1["acf_error_final"])

    def test_refuses_other_values(self):
        x = smooth_trace()
        with contextlib.redirect_stdout(io.StringIO()):
            _, first, info = st.make_node(3, x, {"name": "empirical"}, settings(max_iter=100))
        first = first.copy()
        first[0] += 1                                          # no longer a reordering of X_init
        with self.assertRaises(SystemExit):
            st.make_node(3, x, {"name": "empirical"}, settings(), resume=(first, info))


class EmpiricalDraw(unittest.TestCase):

    def test_with_replacement_and_per_seed(self):
        x = np.arange(1000)                       # every real value different
        cdf = {"name": "empirical"}
        node0 = st.draw_initial(x, cdf, np.random.default_rng(0))
        node1 = st.draw_initial(x, cdf, np.random.default_rng(1))
        self.assertTrue(set(node0.tolist()) <= set(x.tolist()))   # only real values
        self.assertLess(len(set(node0.tolist())), len(x))         # some drawn twice, some never
        self.assertNotEqual(sorted(node0.tolist()), sorted(node1.tolist()))


class Weights(unittest.TestCase):

    def test_lag_weights(self):
        w = st.lag_weights("lag", 1440)
        self.assertAlmostEqual(w.sum(), 1.0)
        self.assertTrue(np.all(np.diff(w) < 0))   # each lag counts less than the one before
        self.assertAlmostEqual(w[0] / w[9], 10.0)
        self.assertTrue(np.allclose(st.lag_weights("uniform", 4), 0.25))


if __name__ == "__main__":
    unittest.main()
