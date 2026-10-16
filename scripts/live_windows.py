"""
More replay windows for the live runs (step 4B), chosen by a fixed rule.

Usage:
    .venv/bin/python scripts/live_windows.py

Every candidate window has --minutes minutes (default 180) and --warmup
minutes before it (default 3). Both lie in the test minutes with forecasts of
one node, the minutes that step 4A simulates. The rule, over all 16 nodes:
  guard  the window mean is at least the median of the node's test minutes.
         This skips quiet night windows, where a jump relative to the mean
         is only noise.
  calm   the lowest peak/mean.
  rise   the biggest rise from one minute to the next, divided by the window
         mean. The window is centred on it: the rise goes from window minute
         89 to minute 90 (counted from 0).
  spiky  the same with the biggest jump up or down.
The window of the first live runs (node 0, centred on its busiest half hour,
the default of live_prepare.py) is listed too, for comparison.

Output: --out (default results/autoscaler_live/windows.json) with the best
window of each node and rule, best first, and a table on the screen with the
live_prepare.py command of each chosen window.
"""
import argparse
import json
import os
import sys

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from predictors.data import NodeData, french_holidays, load_node  # noqa: E402

NODES = 16
RULES = ["calm", "rise", "spiky"]


def scores(traffic, minutes, warmup):
    """
    All windows whose warm-up fits in `traffic`: window i starts at traffic[i + warmup].
    Returns per window: the mean, peak/mean, the jump in its middle divided by
    the mean (signed, a rise is positive) and whether it passes the guard.
    """
    windows = sliding_window_view(traffic, minutes)[warmup:]
    mean = windows.mean(axis=1)
    middle = minutes // 2
    jump = (windows[:, middle] - windows[:, middle - 1]) / mean
    return mean, windows.max(axis=1) / mean, jump, mean >= np.median(traffic)


def best(traffic, minutes, warmup):
    """{rule: (first minute of the best window as an index into traffic, its score)}."""
    mean, ratio, jump, busy = scores(traffic, minutes, warmup)
    score = {"calm": ratio, "rise": jump, "spiky": np.abs(jump)}
    picked = {"calm": int(np.argmin(np.where(busy, ratio, np.inf))),
              "rise": int(np.argmax(np.where(busy, jump, -np.inf))),
              "spiky": int(np.argmax(np.where(busy, np.abs(jump), -np.inf)))}
    return {rule: (i + warmup, float(score[rule][i])) for rule, i in picked.items()}


def describe(x):
    """Mean, peak, peak/mean and the biggest 1-minute jump (signed) of one window."""
    jumps = np.diff(x)
    j = int(np.argmax(np.abs(jumps)))
    return {"mean": float(x.mean()), "peak": float(x.max()), "peak_mean": float(x.max() / x.mean()),
            "biggest_jump": float(jumps[j]), "biggest_jump_pct": float(100 * abs(jumps[j]) / x.mean()),
            "biggest_jump_to_minute": j + 1}


def main():
    parser = argparse.ArgumentParser(description="Choose more replay windows by a fixed rule.")
    parser.add_argument("--minutes", type=int, default=180)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--predictors-report", default=os.path.join(ROOT, "results", "predictors", "report.json"))
    parser.add_argument("--out", default=os.path.join(ROOT, "results", "autoscaler_live", "windows.json"))
    args = parser.parse_args()
    window = json.load(open(args.predictors_report))["chosen_window"]
    middle = args.minutes // 2

    found = {rule: [] for rule in RULES}
    for n in range(NODES):
        # The test minutes with forecasts, as in simulate_autoscaler.node_inputs
        path = os.path.join(ROOT, "data", "synthetic", f"node_{n:02d}.csv")
        stamps, requests = load_node(path)[:2]
        node = NodeData(path, window, french_holidays(stamps), "cpu")
        minutes = node.starts["test"].cpu().numpy() + node.window
        traffic = requests[minutes]
        median = float(np.median(traffic))

        def entry(first, **extra):
            x = traffic[first:first + args.minutes]
            return {"node": n, "first_minute": str(stamps[minutes[first]]),
                    "last_minute": str(stamps[minutes[first + args.minutes - 1]]),
                    "warmup_first_row": int(minutes[first - args.warmup]), "first_row": int(minutes[first]),
                    "last_row": int(minutes[first + args.minutes - 1]), **extra,
                    "node_median": median, "passes_guard": bool(x.mean() >= median),
                    "middle_jump": float(x[middle] - x[middle - 1]), **describe(x)}

        for rule, (first, score) in best(traffic, args.minutes, args.warmup).items():
            found[rule].append(entry(first, score=score))
        if n == 0:
            # The window of the first live runs: the default of live_prepare.py
            centre = int(np.argmax(np.convolve(traffic, np.ones(30) / 30, "valid"))) + 15
            busiest = entry(centre - middle)

    found["calm"].sort(key=lambda e: e["score"])
    found["rise"].sort(key=lambda e: -e["score"])
    found["spiky"].sort(key=lambda e: -e["score"])
    with open(args.out, "w") as f:
        json.dump({"minutes": args.minutes, "warmup": args.warmup, "busiest": busiest} | found, f, indent=1)

    print(f"{'window':8} {'node':>4}  {'first minute':16}  {'trace rows':15} {'mean':>8} {'peak':>8} "
          f"{'peak/mean':>9} {'middle jump':>12} {'biggest jump':>13}")
    for name, e in [("busiest", busiest)] + [(rule, found[rule][0]) for rule in RULES]:
        print(f"{name:8} {e['node']:4}  {e['first_minute'].replace('T', ' '):16}  "
              f"{e['first_row']:,}-{e['last_row']:,} {e['mean']:8.0f} {e['peak']:8.0f} {e['peak_mean']:9.2f} "
              f"{100 * e['middle_jump'] / e['mean']:+11.1f}% {e['biggest_jump']:+9.0f} ({e['biggest_jump_pct']:.0f}%)")
    print("\nAll pass the guard (mean at least the node's median):",
          all(e["passes_guard"] for e in [found[rule][0] for rule in RULES]))
    for rule in RULES:
        e = found[rule][0]
        print(f'.venv/bin/python scripts/live_prepare.py --node {e["node"]} '
              f'--start "{e["first_minute"].replace("T", " ")}" --out-dir results/autoscaler_live/{rule}')
    print(f"Saved {args.out}")


if __name__ == "__main__":
    main()
