"""
Make synthetic workload traces from the FIFA trace, one per edge node.

This follows Dogani & Khunjush (2024), who use the method of Koltuk & Schmidt
(ISCC 2020): every synthetic trace has the same distribution (CDF) and the
same autocorrelation (ACF) as the real trace X, but different values.

Usage:
    .venv/bin/python scripts/synthetic_traces.py --start 1998-06-15 --end 1998-06-21 \\
        --nodes 1 --out-dir data/synthetic/test_week                    (one week, one node)
    .venv/bin/python scripts/synthetic_traces.py                          (all days, 16 nodes)
    .venv/bin/python scripts/synthetic_traces.py --cdf empirical --resume data/synthetic
                                       (continue saved traces that hit --max-iter)

STEP 1, CDF matching: fit candidate distributions to X, pick one with
Koltuk's criteria, and draw X_init: n independent values from it. X_init has
the right distribution but no autocorrelation at all (every minute is random).

STEP 2, ACF matching (Koltuk's Algorithm 1): repeatedly pick S random
positions of the trace, shuffle the values there, and keep the change only if
the ACF got closer to the real one. Shuffling never changes the values
themselves, so the distribution from step 1 stays exactly the same.
"Closer" is a weighted error with weight 1/lag (--weights), because our
predictor looks only a few minutes ahead, so the short lags matter most.

Outputs in --out-dir (default data/synthetic/):
    node_00.csv ...   minute_paris, requests (same minutes as the real trace)
    report.json       chosen distribution, test results, ACF error per node
    node_00.png ...   plots for the nodes in --plot-nodes (default 0 and 1)
"""
import argparse
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
from scipy import stats

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
INPUT = os.path.join(ROOT, "data", "fifa_requests_per_minute_days5-92.csv")
OUT_DIR = os.path.join(ROOT, "data", "synthetic")

# Day 5 has only its last 30 minutes, so the trace starts on day 6.
FIRST_DAY, LAST_DAY = "1998-05-01", "1998-07-26"

CANDIDATES = ["genextreme", "burr12", "lognorm", "gamma", "weibull_min", "fisk"]
AD_CRITICAL = 2.492   # Anderson-Darling critical value at the 5% level
P_MIN = 0.05
C_RATIO_MAX = 2       # "similar dispersion": the fit's C at most 2x bigger or smaller


# ----------------------------------------------------------------------
# The real trace
# ----------------------------------------------------------------------
def load_trace(path, start, end):
    """Minutes (Paris time, as text) and requests from `start` to `end`, both days included."""
    data = np.genfromtxt(path, delimiter=",", names=True, dtype=None, encoding="utf-8",
                         usecols=("minute_paris", "requests"))
    minutes = data["minute_paris"].astype("datetime64[m]")
    keep = (minutes >= np.datetime64(start)) & (minutes < np.datetime64(end) + np.timedelta64(1, "D"))
    return data["minute_paris"][keep], data["requests"][keep].astype(np.int64)


# ----------------------------------------------------------------------
# STEP 1: CDF matching
# ----------------------------------------------------------------------
def anderson_darling(x, dist):
    """
    The Anderson-Darling statistic A²: how far the data's CDF is from the
    fitted CDF, with extra weight on the tails. 0 = perfect fit.
    """
    x = np.sort(x)
    n = len(x)
    i = np.arange(1, n + 1)
    return float(-n - np.mean((2 * i - 1) * (dist.logcdf(x) + dist.logsf(x[::-1]))))


def anderson_darling_p(a2):
    """
    p-value of A² (Marsaglia & Marsaglia 2004, for large n). It treats the
    fitted parameters as known, which makes the test too lenient, so a
    rejection here is a safe rejection.
    """
    z = a2
    if z < 2:
        cdf = (np.exp(-1.2337141 / z) / np.sqrt(z)
               * (2.00012 + (.247105 - (.0649821 - (.0347962 - (.0116720 - .00168691 * z) * z) * z) * z) * z))
    else:
        cdf = np.exp(-np.exp(1.0776 - (2.30695 - (.43424 - (.082433 - (.008056 - .0003146 * z) * z) * z) * z) * z))
    return float(max(0.0, 1 - cdf))


def dispersion(mean, variance):
    """C = variance / mean. None if the variance is infinite (very heavy tail)."""
    return float(variance / mean) if np.isfinite(variance) and mean > 0 else None


def fit_candidates(x):
    """
    Fit every candidate distribution. Each is fitted twice, with its start
    point (loc) free and with loc fixed 1 below the smallest value, because
    scipy's free fit sometimes ends in a poor place. The better fit is kept.
    """
    results = []
    for name in CANDIDATES:
        family = getattr(stats, name)
        best = None
        for options in ({}, {"floc": float(x.min()) - 1}):
            params = family.fit(x, **options)
            a2 = anderson_darling(x, family(*params))
            if best is None or a2 < best[0]:
                best = (a2, params)
        a2, params = best
        mean, variance = family(*params).stats("mv")
        results.append({"name": name, "params": [float(p) for p in params], "ad": a2,
                        "p": anderson_darling_p(a2),
                        "C": dispersion(float(mean), float(variance))})
        c = results[-1]["C"]
        print(f"  {name:12s} A² = {a2:10.2f}   p = {results[-1]['p']:.3g}   "
              f"C = {'infinite' if c is None else f'{c:.0f}'}")
    return results


def choose(candidates, c_real):
    """
    Koltuk's rule: among the fits that pass the test (A² below the critical
    value and p > 0.05), take the one whose C is closest to the real C.
    If none passes, take the lowest A² among the fits whose C is "similar":
    within a factor C_RATIO_MAX of the real C.

    Why C must be similar here: a fit with a much heavier tail (C far too
    big, or infinite) draws a few gigantic values. One week of fisk draws
    (C infinite) reached 7.8 million requests per minute, the real maximum is
    154 thousand. Those few values dominate the ACF, and step 2 gets stuck:
    ACF MSE 0.089 with fisk and 0.076 with burr12 (C 10x the real one) after
    millions of iterations, against 0.0000004 when drawing real values.
    """
    similar = [c for c in candidates
               if c["C"] is not None and 1 / C_RATIO_MAX <= c["C"] / c_real <= C_RATIO_MAX]
    passing = [c for c in similar if c["ad"] < AD_CRITICAL and c["p"] > P_MIN]
    if passing:
        chosen = min(passing, key=lambda c: abs(c["C"] - c_real))
        return chosen, "passed the Anderson-Darling test; closest C to the real trace"
    if not similar:
        raise SystemExit(f"no fit has a C within {C_RATIO_MAX}x of the real one; use --cdf empirical")
    chosen = min(similar, key=lambda c: c["ad"])
    return chosen, ("no candidate passed the Anderson-Darling test "
                    f"(A² < {AD_CRITICAL} and p > {P_MIN}); picked the lowest A² among the "
                    f"fits whose C = variance / mean is within {C_RATIO_MAX}x of the real C")


def draw_initial(x, cdf, rng):
    """X_init: len(x) independent values, rounded to whole requests and at least 0."""
    if cdf["name"] == "empirical":
        # Inverse of the real trace's own CDF = drawing real values at random,
        # with replacement: a real minute can appear several times or not at
        # all, so every node (seed) gets its own mix of values.
        return rng.choice(x, len(x), replace=True)
    dist = getattr(stats, cdf["name"])(*cdf["params"])
    values = dist.ppf(rng.random(len(x)))
    return np.round(np.clip(values, 0, None)).astype(np.int64)


# ----------------------------------------------------------------------
# STEP 2: ACF matching
# ----------------------------------------------------------------------
def autocovariance(y, lags):
    """
    Sums of z_t * z_(t+k) for k = 0..lags, with z = y - mean, using the FFT
    (fast: n log n instead of n * lags). The ACF is this divided by its k = 0 value.
    """
    z = y - y.mean()
    size = 1 << (2 * len(y) - 1).bit_length()   # zero padding: no wrap-around
    spectrum = np.fft.rfft(z, size)
    return np.fft.irfft(spectrum * np.conj(spectrum), size)[:lags + 1]


def acf(y, lags):
    """Autocorrelation at lags 1..lags."""
    c = autocovariance(y.astype(float), lags)
    return c[1:] / c[0]


def lag_weights(kind, lags):
    """
    How much each lag counts in the ACF error, summing to 1.
    "lag":     weight 1/k, so short lags count most (lags 1-10 get 37% of the
               weight for 1440 lags, lag 1 alone 13%). Our predictor looks
               3 to 5 minutes ahead, so the short lags matter most.
    "uniform": every lag the same, as in Koltuk's plain MSE.
    """
    k = np.arange(1, lags + 1)
    w = 1.0 / k if kind == "lag" else np.ones(lags)
    return w / w.sum()


def match_acf(x, x_init, args, rng, label=""):
    """
    Koltuk's Algorithm 1, with a weighted ACF error. Returns (Y, info).

    A node is done when all 3 targets are met, or after args.max_iter iterations:
      1. weighted ACF error (lags 1..args.lags, weight 1/lag) at most args.eps
      2. ACF at each of lags 1..args.short_lags within args.short_tol of the real one
      3. ACF at lag args.day_lag (one day) within args.day_tol of the real one
    A shuffle is kept if it lowers the "score": the weighted error plus, for
    targets 2 and 3, how far each lag still is outside its tolerance (squared).
    Once targets 2 and 3 are met, that extra part is 0 and the score is the
    weighted error alone. Without it, lag 1440 (weight 1/1440) would hardly
    ever move toward its target.

    Speed-up, same result: a shuffle changes only S values, and it keeps the
    mean and the variance (the same numbers in another order). So instead of
    computing the whole ACF again with an FFT every iteration (n log n), we
    update only the products z_t * z_(t+k) that touch the S changed positions
    (S * lags). The result is the same up to rounding; at the end the ACF is
    computed once more with the FFT and those values are reported.
    """
    n, S, lags = len(x), args.S, args.lags
    target = acf(x, lags)
    w = lag_weights(args.weights, lags)
    # (lags as indexes, tolerance): index 0 = lag 1
    limits = [(np.arange(args.short_lags), args.short_tol),
              (np.array([args.day_lag - 1]), args.day_tol)]

    def weighted_error(r):
        return float(np.sum(w * (r - target) ** 2))

    def outside(r):
        """How far the target lags are outside their tolerance, squared and summed (0 = all met)."""
        return float(sum(np.sum(np.maximum(np.abs(r[i] - target[i]) - tol, 0) ** 2)
                         for i, tol in limits))

    y = x_init.copy()
    c = autocovariance(y.astype(float), lags)
    c0 = c[0]
    # z with `lags` zeros on both sides, so z[t + k] and z[t - k] never fall off the ends.
    z = np.zeros(n + 2 * lags)
    z[lags:lags + n] = y - y.mean()
    offsets = np.arange(1, lags + 1)
    error_now, outside_now = weighted_error(c[1:] / c0), outside(c[1:] / c0)
    e_init = error_now
    score = error_now + outside_now

    start = time.time()
    iterations = accepted = 0
    while (error_now > args.eps or outside_now > 0) and iterations < args.max_iter:
        iterations += 1
        positions = rng.choice(n, S, replace=False)
        order = rng.permutation(S)
        old = z[lags + positions]
        new = old[order]
        d = new - old
        # Change of every sum z_t * z_(t+k): the changed values times their
        # neighbours k steps ahead and behind ...
        neighbours = z[lags + positions[:, None] + offsets] + z[lags + positions[:, None] - offsets]
        change = d @ neighbours
        # ... plus a correction when two changed positions are k apart.
        gap = positions[None, :] - positions[:, None]
        close = (gap > 0) & (gap <= lags)
        if close.any():
            np.add.at(change, gap[close] - 1, np.outer(d, d)[close])
        c_new = c[1:] + change
        r_new = c_new / c0
        e, o = weighted_error(r_new), outside(r_new)
        if e + o < score:                  # better: keep the shuffle
            score, error_now, outside_now = e + o, e, o
            c[1:] = c_new
            z[lags + positions] = new
            y[positions] = y[positions][order]
            accepted += 1
        # else: nothing was changed yet, so there is nothing to undo
        if iterations % 1_000_000 == 0:
            r = c[1:] / c0
            print(f"  {label}{iterations:>11,} iterations, weighted ACF error {error_now:.2e}, "
                  f"lag 1 {r[0]:.4f} ({target[0]:.4f}), lag 10 {r[9]:.4f} ({target[9]:.4f}), "
                  f"lag {args.day_lag} {r[args.day_lag - 1]:.4f} ({target[args.day_lag - 1]:.4f})",
                  flush=True)
    runtime = time.time() - start

    r = acf(y, lags)                       # checked with the FFT
    short = slice(0, args.short_lags)
    targets = {
        "weighted_error": weighted_error(r) <= args.eps,
        f"lags_1_{args.short_lags}": bool(np.max(np.abs(r[short] - target[short])) <= args.short_tol),
        f"lag_{args.day_lag}": bool(abs(r[args.day_lag - 1] - target[args.day_lag - 1]) <= args.day_tol),
    }
    return y, {"acf_error_init": e_init, "acf_error_final": weighted_error(r),
               "acf_error_tracked": error_now,  # the fast update's own value, should equal the line above
               "acf_mse_unweighted_final": float(np.mean((r - target) ** 2)),
               "targets_met": targets, "all_targets_met": all(targets.values()),
               "lag1": float(r[0]), "lag1_real": float(target[0]),
               "lag5": float(r[4]), "lag5_real": float(target[4]),
               "lag10": float(r[9]), "lag10_real": float(target[9]),
               f"lag{args.day_lag}": float(r[args.day_lag - 1]),
               f"lag{args.day_lag}_real": float(target[args.day_lag - 1]),
               f"worst_gap_lags_1_{args.short_lags}": float(np.max(np.abs(r[short] - target[short]))),
               "iterations": iterations, "accepted": accepted,
               "runtime_s": round(runtime, 1),
               "us_per_iteration": round(1e6 * runtime / iterations, 1) if iterations else None}


# ----------------------------------------------------------------------
# One node
# ----------------------------------------------------------------------
def make_node(node, x, cdf, args, resume=None):
    """
    Draw X_init with seed = node number, then match the ACF. Returns (x_init, y, info).

    resume = (saved trace, that node's entry in the old report.json): continue
    from the saved trace instead of from X_init. X_init is still drawn (the
    same seed gives the same draw), to check that the saved trace holds
    exactly the values of X_init, only in another order, and for the plots.
    """
    rng = np.random.default_rng(node)
    x_init = draw_initial(x, cdf, rng)
    start, before = x_init, {"iterations": 0, "accepted": 0, "runtime_s": 0.0}
    if resume is not None:
        start, before = resume
        if not np.array_equal(np.sort(start), np.sort(x_init)):
            raise SystemExit(f"node {node:02d}: the saved trace does not have the values of X_init "
                             "(other window, --cdf or seed?)")
        # New random positions: a seed made of the node and the iterations done so far.
        rng = np.random.default_rng([node, before["iterations"]])
    y, info = match_acf(x, start, args, rng, label=f"node {node:02d}: ")
    info.update(node=node, seed=node, mean=float(y.mean()), max=int(y.max()),
                acf_error_x_init=(before["acf_error_x_init"] if resume is not None
                                  else info["acf_error_init"]),
                acf_error_at_start=info.pop("acf_error_init"),
                iterations_this_run=info["iterations"], runtime_s_this_run=info["runtime_s"])
    # Totals over the first run and every continued run
    info["iterations"] += before["iterations"]
    info["accepted"] += before["accepted"]
    info["runtime_s"] = round(info["runtime_s"] + before["runtime_s"], 1)
    print(f"  node {node:02d}: done, all targets met: {info['all_targets_met']}, "
          f"weighted ACF error {info['acf_error_final']:.2e}, "
          f"lag 1 {info['lag1']:.4f} (real {info['lag1_real']:.4f}), "
          f"lag 10 {info['lag10']:.4f} (real {info['lag10_real']:.4f}), "
          f"lag {args.day_lag} {info[f'lag{args.day_lag}']:.4f} "
          f"(real {info[f'lag{args.day_lag}_real']:.4f}), after "
          f"{info['iterations_this_run']:,} iterations in this run "
          f"({info['iterations']:,} in total), {info['runtime_s_this_run']} s "
          f"({info['us_per_iteration'] or '-'} µs per iteration)", flush=True)
    return x_init, y, info


def load_resume(folder, minutes, nodes):
    """
    For --resume: each node's saved trace and its entry in folder/report.json,
    plus the old report itself.
    """
    with open(os.path.join(folder, "report.json")) as f:
        old = json.load(f)
    entries = {e["node"]: e for e in old["nodes"]}
    resume = {}
    for node in range(nodes):
        data = np.genfromtxt(os.path.join(folder, f"node_{node:02d}.csv"), delimiter=",", names=True,
                             dtype=None, encoding="utf-8")
        if not np.array_equal(data["minute_paris"], minutes):
            raise SystemExit(f"node {node:02d}: the saved trace covers other minutes; use the same "
                             "--start and --end as before")
        resume[node] = (data["requests"].astype(np.int64), entries[node])
    return resume, old


def save_node(path, minutes, y):
    with open(path, "w") as f:
        f.write("minute_paris,requests\n")
        for minute, value in zip(minutes, y.tolist()):
            f.write(f"{minute},{value}\n")


# ----------------------------------------------------------------------
# Plots like Koltuk's slide 15
# ----------------------------------------------------------------------
def plot_node(path, node, minutes, x, x_init, y, lags):
    import matplotlib
    matplotlib.use("Agg")   # draw to a file, no window needed
    import matplotlib.pyplot as plt

    REAL, SYNTH = "#4b5563", "#3987e5"   # grey = real, blue = synthetic
    lag = np.arange(1, lags + 1)
    fig, axes = plt.subplots(2, 2, figsize=(14, 8))
    (a, b), (c, d) = axes

    # (a) CDF: the share of minutes with at most v requests.
    for values, color, name in ((x, REAL, "real X"), (y, SYNTH, "synthetic")):
        v = np.sort(values)
        a.step(v, np.arange(1, len(v) + 1) / len(v), where="post", color=color, lw=1.5, label=name)
    a.set_xscale("symlog", linthresh=100)
    a.set(title="(a) CDF", xlabel="requests per minute (log scale)", ylabel="share of minutes")

    # (b) ACF of X_init: random order, so about 0 at every lag.
    b.plot(lag, acf(x, lags), color=REAL, lw=1, alpha=0.5, label="real X")
    b.plot(lag, acf(x_init, lags), color=SYNTH, lw=1, label="X_init")
    b.set(title="(b) ACF of X_init", xlabel="lag (minutes)", ylabel="autocorrelation", ylim=(-1, 1))

    # (c) ACF after matching.
    c.plot(lag, acf(x, lags), color=REAL, lw=2, label="real X")
    c.plot(lag, acf(y, lags), color=SYNTH, lw=1, ls="--", label="X_fit")
    c.set(title="(c) ACF of real X and X_fit", xlabel="lag (minutes)", ylabel="autocorrelation",
          ylim=(-1, 1))

    # (d) The two time series.
    t = minutes.astype("datetime64[m]").astype("datetime64[s]").astype(object)
    d.plot(t, x, color=REAL, lw=0.5, label="real X")
    d.plot(t, y, color=SYNTH, lw=0.5, alpha=0.7, label="synthetic")
    d.set(title="(d) Time series", xlabel="Paris time, 1998", ylabel="requests per minute")
    d.xaxis.set_major_formatter(matplotlib.dates.ConciseDateFormatter(d.xaxis.get_major_locator()))

    for ax in axes.flat:
        ax.grid(color="#e5e7eb", lw=0.8)
        ax.legend(frameon=False)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    fig.suptitle(f"Node {node:02d}: real vs synthetic trace", x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Synthetic traces with the CDF and ACF of the FIFA trace.")
    parser.add_argument("--input", default=INPUT, help="per-minute CSV from fifa_workload.py")
    parser.add_argument("--start", default=FIRST_DAY, help=f"first day, Paris time (default {FIRST_DAY})")
    parser.add_argument("--end", default=LAST_DAY, help=f"last day, included (default {LAST_DAY})")
    parser.add_argument("--nodes", type=int, default=16, help="traces to make, seeds 0..nodes-1 (default 16)")
    parser.add_argument("--cdf", choices=["fit", "empirical"], default="fit",
                        help="fit a distribution (default) or draw from the real values")
    parser.add_argument("--lags", type=int, default=1440, help="ACF compared over lags 1..lags (default 1440 = 1 day)")
    parser.add_argument("--S", type=int, default=2, help="positions shuffled per iteration (default 2)")
    parser.add_argument("--weights", choices=["lag", "uniform"], default="lag",
                        help="ACF error weights: 1/lag (default, short lags count most) or uniform")
    parser.add_argument("--eps", type=float, default=1e-5,
                        help="stop when the weighted ACF error is below this (default 1e-5) ...")
    parser.add_argument("--short-lags", type=int, default=10,
                        help="... and the ACF at lags 1..short-lags (default 10) ...")
    parser.add_argument("--short-tol", type=float, default=0.01,
                        help="... is within this of the real ACF at each of them (default 0.01) ...")
    parser.add_argument("--day-lag", type=int, default=1440,
                        help="... and the ACF at this lag (default 1440 = one day) ...")
    parser.add_argument("--day-tol", type=float, default=0.02,
                        help="... is within this of the real one (default 0.02)")
    parser.add_argument("--max-iter", type=float, default=2e8, help="safety stop per node (default 2e8)")
    parser.add_argument("--jobs", type=int, default=min(16, os.cpu_count() or 1),
                        help="nodes computed at the same time")
    parser.add_argument("--plot-nodes", default="0,1", help="nodes to plot (default 0,1)")
    parser.add_argument("--out-dir", default=OUT_DIR, help="output folder (default data/synthetic)")
    parser.add_argument("--resume", metavar="DIR",
                        help="continue the traces saved in DIR (node_XX.csv and report.json) "
                             "instead of starting from X_init; --max-iter counts this run only")
    args = parser.parse_args()
    args.max_iter = int(args.max_iter)
    if args.S < 2:
        parser.error("--S must be at least 2 (one value alone can't be shuffled)")

    started = time.time()
    minutes, x = load_trace(args.input, args.start, args.end)
    n = len(x)
    if args.lags >= n:
        parser.error(f"--lags must be below the number of minutes ({n})")
    if not 1 <= args.short_lags <= args.lags:
        parser.error("--short-lags must be between 1 and --lags")
    if not 1 <= args.day_lag <= args.lags:
        parser.error("--day-lag must be between 1 and --lags")
    c_real = dispersion(x.mean(), x.var())
    print(f"Real trace: {n} minutes, {minutes[0]} to {minutes[-1]} (Paris), "
          f"mean {x.mean():.0f}, max {x.max()}, C = variance / mean = {c_real:.0f}")

    # STEP 1 (skipped with --resume: the saved traces already have their values)
    resume = None
    if args.resume:
        resume, old = load_resume(args.resume, minutes, args.nodes)
        if old["cdf"]["method"] != args.cdf:
            parser.error(f"--resume: those traces were made with --cdf {old['cdf']['method']}")
        candidates, why = old["cdf"]["candidates"], old["cdf"]["why"]
        cdf = {"name": old["cdf"]["chosen"], "params": old["cdf"]["params"], "ad": old["cdf"]["ad"],
               "p": old["cdf"]["p"], "C": old["cdf"]["C_fit"]}
        print(f"STEP 1: continuing the traces in {os.path.relpath(args.resume, ROOT)}/ ({why})")
    elif args.cdf == "fit":
        print("STEP 1: fitting distributions")
        candidates = fit_candidates(x.astype(float))
        cdf, why = choose(candidates, c_real)
        print(f"  chosen: {cdf['name']}: {why}")
    else:
        candidates, cdf = [], {"name": "empirical", "params": [], "ad": None, "p": None, "C": c_real}
        why = "--cdf empirical: values drawn from the real trace itself"
        print(f"STEP 1: {why}")

    # STEP 2, one node per process
    print(f"STEP 2: matching the ACF for {args.nodes} node(s), S = {args.S}, lags 1..{args.lags} "
          f"weighted {args.weights}; stop at error {args.eps:g}, lags 1-{args.short_lags} "
          f"within {args.short_tol:g} and lag {args.day_lag} within {args.day_tol:g}")
    os.makedirs(args.out_dir, exist_ok=True)
    plot_nodes = {int(k) for k in args.plot_nodes.split(",") if k.strip()}
    nodes = []
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        jobs = [pool.submit(make_node, node, x, cdf, args, resume and resume[node])
                for node in range(args.nodes)]
        for job in jobs:
            x_init, y, info = job.result()
            node = info["node"]
            save_node(os.path.join(args.out_dir, f"node_{node:02d}.csv"), minutes, y)
            if node in plot_nodes:
                plot_node(os.path.join(args.out_dir, f"node_{node:02d}.png"), node, minutes, x,
                          x_init, y, args.lags)
            nodes.append(info)

    report = {
        "input": os.path.relpath(args.input, ROOT),
        "window_paris": {"start": str(minutes[0]), "end": str(minutes[-1]), "minutes": n},
        "real": {"mean": float(x.mean()), "variance": float(x.var()), "C": c_real, "max": int(x.max())},
        "cdf": {"method": args.cdf, "chosen": cdf["name"], "params": cdf["params"],
                "ad": cdf["ad"], "ad_critical_5pct": AD_CRITICAL, "p": cdf["p"], "C_fit": cdf["C"],
                "why": why, "candidates": candidates},
        "settings": {"S": args.S, "weights": args.weights, "eps": args.eps, "lags": args.lags,
                     "short_lags": args.short_lags, "short_tol": args.short_tol,
                     "day_lag": args.day_lag, "day_tol": args.day_tol,
                     "max_iter": args.max_iter},
        "resumed_from": os.path.relpath(args.resume, ROOT) if args.resume else None,
        "nodes": nodes,
        "total_runtime_s": round(time.time() - started, 1),
    }
    with open(os.path.join(args.out_dir, "report.json"), "w") as f:
        json.dump(report, f, indent=2)
    print(f"Saved {args.nodes} trace(s), plots and report.json in "
          f"{os.path.relpath(args.out_dir, ROOT)}/ ({report['total_runtime_s']} s)")


if __name__ == "__main__":
    main()
