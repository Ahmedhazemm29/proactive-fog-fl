"""Error metrics per horizon (paper Section 6.3) and the Diebold-Mariano test."""
import numpy as np
from scipy import stats


def metrics(predicted, real):
    """
    MAPE (%), MAE and RMSE of 1-D arrays in real request units. MAPE skips
    minutes whose real value is 0 (division by zero); "mape_skipped" says how many.
    """
    error = predicted - real
    nonzero = real != 0
    return {"mape": float(np.mean(np.abs(error[nonzero] / real[nonzero])) * 100),
            "mae": float(np.mean(np.abs(error))),
            "rmse": float(np.sqrt(np.mean(error ** 2))),
            "mape_skipped": int((~nonzero).sum()), "n": int(len(real))}


def diebold_mariano(error_a, error_b, horizon):
    """
    Do forecasts a and b differ in accuracy? Loss = absolute error, d = |a| - |b|.
    Forecasts h steps ahead overlap, so the variance of mean(d) counts the
    autocovariances up to lag h-1. Harvey, Leybourne & Newbold (1997)
    small-sample correction, t distribution with n-1 degrees of freedom.
    Returns (DM statistic, two-sided p-value). DM > 0: a has larger errors.
    """
    d = np.abs(error_a) - np.abs(error_b)
    n = len(d)
    centred = d - d.mean()
    gamma = [np.dot(centred[k:], centred[:n - k]) / n for k in range(horizon)]
    variance = (gamma[0] + 2 * sum(gamma[1:])) / n
    if variance <= 0:
        variance = gamma[0] / n
    if variance <= 0:                      # the two forecasts have identical errors
        return 0.0, 1.0
    dm = d.mean() / np.sqrt(variance)
    dm *= np.sqrt((n + 1 - 2 * horizon + horizon * (horizon - 1) / n) / n)
    return float(dm), float(2 * stats.t.sf(abs(dm), df=n - 1))
