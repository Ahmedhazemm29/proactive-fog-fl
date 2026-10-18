"""
Ways to compute MAPE (paper Eq. 13: the mean of |forecast - real| / |real|, in %).

Dogani gives the formula but not which values it was applied to. These are the
readings we compare in decision 3.12. Each one takes real-unit forecasts and
real values of one horizon step. `nodes` is a list of (predicted, real) array
pairs, one per node; all nodes cover the same test minutes.
"""
import numpy as np


def mape(predicted, real, floor=0.0):
    """
    MAPE in % over the minutes whose real value is not 0 and at least `floor`.
    floor 0 skips only exact zeros: our Table 8.
    """
    keep = (real != 0) & (real >= floor)
    return float(np.mean(np.abs((predicted[keep] - real[keep]) / real[keep])) * 100)


def pooled(nodes, floor_share=0.0):
    """One MAPE over all nodes' minutes. A minute is skipped when its real value is below floor_share x its node's mean."""
    p = np.concatenate([pr for pr, _ in nodes])
    r = np.concatenate([re for _, re in nodes])
    floor = np.concatenate([np.full(len(re), floor_share * re.mean()) for _, re in nodes])
    keep = (r != 0) & (r >= floor)
    return float(np.mean(np.abs((p[keep] - r[keep]) / r[keep])) * 100)


def per_node(nodes, floor_share=0.0):
    """The mean of the nodes' own MAPEs (each node counts once, whatever its number of minutes)."""
    return float(np.mean([mape(pr, re, floor_share * re.mean()) for pr, re in nodes]))


def of_total(nodes):
    """MAPE of one total trace: all nodes' forecasts and real values added minute by minute."""
    return mape(sum(pr for pr, _ in nodes), sum(re for _, re in nodes))


def scale(values, low, span, a, b):
    """Min-max scaling to [a, b]: x' = a + (b - a)(x - low) / span."""
    return a + (b - a) * (values - low) / span


def scaled(predicted, real, low, span, a, b):
    """MAPE of the min-max scaled values (minutes whose scaled real value is exactly 0 are skipped)."""
    return mape(scale(predicted, low, span, a, b), scale(real, low, span, a, b), floor=-np.inf)


def implied_mean_traffic(mae_paper, mape_paper, mae_ours, mean_ours, mape_ours):
    """
    The mean traffic that makes the paper's MAE and MAPE fit together, if its
    errors have the same shape as ours: MAE / mean traffic is the same
    multiple of MAPE for both. So mean = MAE_paper / (MAPE_paper x (MAE_ours / mean_ours) / MAPE_ours).
    """
    return mae_paper / (mape_paper * (mae_ours / mean_ours) / mape_ours)
