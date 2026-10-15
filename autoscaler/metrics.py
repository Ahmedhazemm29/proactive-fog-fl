"""
Elasticity metrics of the planner (paper Section 6.3, Eqs. 14 to 18, p. 10 and 11).
requested and provisioned are pods per minute. One step is Δt = 1 minute.
"""
import numpy as np

METRICS = ["theta_u", "theta_o", "t_u", "t_o"]


def elasticity(requested, provisioned, dt=1.0):
    """
    θU, θO (Eqs. 14, 15): mean share of missing or extra pods, relative to the
    requested pods, in %. TU, TO (Eqs. 16, 17): share of time under- or
    over-provisioned, in %. requested is at least 1, so nothing divides by 0.
    """
    requested = np.asarray(requested, dtype=np.float64)
    provisioned = np.asarray(provisioned, dtype=np.float64)
    total = len(requested) * dt
    gap = requested - provisioned                    # > 0: too few pods, < 0: too many
    return {
        "theta_u": float(100 * np.sum(np.maximum(gap, 0) / requested * dt) / total),
        "theta_o": float(100 * np.sum(np.maximum(-gap, 0) / requested * dt) / total),
        # max(sgn(x), 0) is 1 when x > 0, else 0
        "t_u": float(100 * np.sum((gap > 0) * dt) / total),
        "t_o": float(100 * np.sum((gap < 0) * dt) / total),
    }


def elastic_speedup(auto, fixed):
    """
    Eq. 18: εn = (θU,n/θU,a · θO,n/θO,a · TU,n/TU,a · TO,n/TO,a)^(1/4),
    a = the autoscaler, n = no autoscaling. Above 1: better than no autoscaling.
    Returns (εn, the autoscaler's metrics that are 0). A 0 below a fraction
    gives inf, or nan if the top is 0 too. They are returned, not hidden.
    """
    zero = [m for m in METRICS if auto[m] == 0]
    with np.errstate(divide="ignore", invalid="ignore"):
        ratios = np.array([fixed[m] for m in METRICS]) / np.array([auto[m] for m in METRICS])
        return float(np.prod(ratios) ** 0.25), zero
