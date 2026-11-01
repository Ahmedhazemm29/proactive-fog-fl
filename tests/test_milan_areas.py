"""
Tests for scripts/milan_areas.py. Run all tests with:

    .venv/bin/python -m unittest discover -s tests -v

Hourly profiles, the low-activity cut-off, k-means, the block choice and the
area descriptions, on made-up numbers. No Milan data needed.
"""
import os
import sys
import unittest

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import milan_areas as ma  # noqa: E402  (scripts/milan_areas.py)


class Profiles(unittest.TestCase):

    def test_hourly_both_ways(self):
        values = np.ones((2, ma.SLOTS))
        values[0, :3] = np.nan                     # 3 of the 6 slots of hour 0 unknown
        values[1, :6] = np.nan                     # all of hour 0 unknown
        zero = ma.hourly(values, "zero")
        missing = ma.hourly(values, "missing")
        self.assertEqual(zero[0, 0], 3)
        self.assertEqual(zero[1, 0], 0)
        self.assertEqual(missing[0, 0], 6)         # mean of the known slots x 6
        self.assertTrue(np.isnan(missing[1, 0]))
        self.assertTrue(np.all(zero[:, 1:] == 6))

    def test_low_activity_cut_drops_at_most_the_share(self):
        totals = np.array([1.0, 2.0, 3.0, 94.0])   # sum 100
        dropped, cut = ma.low_activity_cut(totals, 0.03)
        self.assertEqual(sorted(dropped.tolist()), [0, 1])   # 1 + 2 = 3% of 100
        self.assertEqual(cut, 2.0)
        self.assertEqual(len(ma.low_activity_cut(totals, 0.005)[0]), 0)

    def test_zscore_ignores_level_and_size(self):
        shape = np.sin(np.linspace(0, 2 * np.pi, 24))
        profiles = np.array([shape + 5, 10 * shape + 50])
        z = ma.zscore(profiles)
        np.testing.assert_allclose(z[0], z[1])


class Clustering(unittest.TestCase):

    def test_kmeans_finds_separated_groups(self):
        rng = np.random.default_rng(1)
        centres = np.eye(4) * 10
        X = np.vstack([c + rng.normal(0, 0.1, size=(30, 4)) for c in centres])
        labels, _ = ma.kmeans(X, 4, restarts=5, seed=0)
        for g in range(4):
            self.assertEqual(len(set(labels[g * 30:(g + 1) * 30])), 1)
        self.assertEqual(len(set(labels)), 4)


class Blocks(unittest.TestCase):

    def test_blocks_tile_the_grid(self):
        rows, cols = np.divmod(np.arange(ma.N_SQUARES), ma.SIDE)
        tiles = ma.blocks(rows, cols, 10)
        self.assertEqual(len(tiles), 100)
        self.assertEqual(sorted(np.concatenate(list(tiles.values())).tolist()), list(range(ma.N_SQUARES)))
        self.assertEqual(sorted(tiles[(0, 0)].tolist())[:3], [0, 1, 2])
        self.assertIn(ma.SIDE, tiles[(0, 0)])     # the square north of id 1 is in the same block

    def test_circular_gap(self):
        self.assertEqual(ma.circular_gap([0, 6, 12, 18]), 6)
        self.assertEqual(ma.circular_gap([1, 23, 12, 8]), 2)   # 23 -> 1 is 2 hours

    def test_closest_demands_takes_one_per_group(self):
        demand = np.array([10.0, 100.0, 12.0, 50.0, 11.0, 13.0])
        groups = [[0, 1], [2, 3], [4], [5]]
        choice, ratio = ma.closest_demands(groups, demand)
        self.assertEqual(sorted(choice), [0, 2, 4, 5])
        self.assertAlmostEqual(ratio, 13.0 / 10.0)


class Describe(unittest.TestCase):

    def test_components(self):
        rows, cols = np.divmod(np.arange(ma.N_SQUARES), ma.SIDE)
        # squares 0, 1 share a side; 102 (row 1, col 2) only touches 1 at a corner; 500 is far away
        n, largest = ma.components(np.array([0, 1, 102, 500]), rows, cols)
        self.assertEqual(n, 3)
        self.assertAlmostEqual(largest, 0.5)

    def test_peak_hours_together(self):
        a = np.zeros(24)
        a[8] = 10
        a[9] = 9.5
        b = np.zeros(24)
        b[9] = 10
        c = np.zeros(24)
        c[20] = 10
        self.assertEqual(ma.peak_hours_together([a, b, c]), [9])


if __name__ == "__main__":
    unittest.main()
