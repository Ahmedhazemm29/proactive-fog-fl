"""
Tests for scripts/predictor_seeds.py (the Table 8 seed check). Run all tests with:

    .venv/bin/python -m unittest discover -s tests -v

The winner of each cell, the counts per seed, and Dogani's Table 8 read the
right way round (MAPE, MAE, RMSE, each at t+3, t+4, t+5). No training needed.
"""
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import predictor_seeds as ps  # noqa: E402  (scripts/predictor_seeds.py)


def values(bigru_error, lstm_error):
    """Made-up metrics: every BiGRU cell has bigru_error, every LSTM cell lstm_error."""
    out = {}
    for model in ps.MODELS:
        error = bigru_error if "BiGRU" in model else lstm_error
        for metric, step in ps.CELLS:
            out[(model, step, metric)] = error
    return out


class Winners(unittest.TestCase):

    def test_lower_error_wins(self):
        self.assertEqual(ps.winners(values(1.0, 2.0), "FedAvg-BiGRU", "FedAvg-LSTM"), ["BiGRU"] * 9)
        self.assertEqual(ps.winners(values(3.0, 2.0), "CentralBiGRU", "CentralLSTM"), ["LSTM"] * 9)

    def test_dogani_table8(self):
        paper = ps.dogani_values()
        self.assertEqual(paper[("FedAvg-BiGRU", "t+3", "mape")], 9.04)
        self.assertEqual(paper[("FedAvg-BiGRU", "t+5", "rmse")], 437.7)
        self.assertEqual(paper[("CentralLSTM", "t+4", "mae")], 208.8)
        # In both pairs BiGRU is lower everywhere except MAE t+4
        for _, bigru, lstm in ps.PAIRS:
            wins = ps.winners(paper, bigru, lstm)
            self.assertEqual([cell for cell, w in zip(ps.CELLS, wins) if w == "LSTM"],
                             [("mae", "t+4")])

    def test_ranking_rows_compare_with_seed_0(self):
        runs = {0: values(1.0, 2.0), 1: values(3.0, 2.0)}
        rows = ps.ranking_rows(runs)
        self.assertEqual([(r["seed"], r["pair"]) for r in rows],
                         [(0, "FedAvg"), (0, "Central"), (1, "FedAvg"), (1, "Central")])
        self.assertEqual([r["bigru_wins"] for r in rows], [9, 9, 0, 0])
        self.assertEqual([r["same_as_seed0"] for r in rows], [9, 9, 0, 0])
        self.assertEqual([r["same_as_dogani"] for r in rows], [8, 8, 1, 1])


if __name__ == "__main__":
    unittest.main()
