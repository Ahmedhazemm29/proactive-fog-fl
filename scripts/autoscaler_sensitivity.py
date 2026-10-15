"""
Sensitivity of our Table 11 to three assumptions (step 4A).

Usage:
    .venv/bin/python scripts/autoscaler_sensitivity.py

Grid: mean traffic (--mean-pods 15, 25, 40), threshold (1.0, 0.7) and KHPA's
Pods_min (5, 1). For each combination: θU, θO, TU, TO, εn of no autoscaling,
KHPA and the planner with FedAvg-BiGRU, mean over the 16 nodes. Everything
else is the default run of simulate_autoscaler.py (15 fixed pods, planner
Pods_min 5, Table 3).

Distance to Dogani's Table 11: sum of |ours - Dogani| over θU, θO, TU, TO of
the three scalers. His TO for no autoscaling (235.34) is left out: a share of
time cannot be above 100.

Outputs in --out-dir (default results/autoscaler_sensitivity/):
sensitivity.md, grid.csv, report.json.
"""
import argparse
import csv
import itertools
import json
import os
import sys
import time

import numpy as np
import torch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import simulate_autoscaler as sim  # noqa: E402
from autoscaler.metrics import METRICS  # noqa: E402
from autoscaler.scalers import Settings  # noqa: E402
from predictors.data import NodeData, french_holidays, load_node  # noqa: E402

SCALERS = ["No autoscaling", "KHPA", "FedAvg-BiGRU"]
NAMES = {"theta_u": "θU", "theta_o": "θO", "t_u": "TU", "t_o": "TO"}


def distance(name, row):
    """Sum of |ours - Dogani| over θU, θO, TU, TO (no TO for no autoscaling)."""
    dogani = dict(zip(METRICS, sim.DOGANI_TABLE11[name][:4]))
    used = [m for m in METRICS if not (name == "No autoscaling" and m == "t_o")]
    return sum(abs(row[m] - dogani[m]) for m in used)


def main():
    parser = argparse.ArgumentParser(description="Sensitivity grid for the autoscaler simulation.")
    parser.add_argument("--traces", default=os.path.join(ROOT, "data", "synthetic"))
    parser.add_argument("--nodes", type=int, default=16)
    parser.add_argument("--weights-dir", default=os.path.join(ROOT, "data", "predictors"))
    parser.add_argument("--predictors-report", default=os.path.join(ROOT, "results", "predictors", "report.json"))
    parser.add_argument("--mean-pods", default="15,25,40")
    parser.add_argument("--thresholds", default="1.0,0.7")
    parser.add_argument("--khpa-pods-min", default="5,1")
    parser.add_argument("--out-dir", default=os.path.join(ROOT, "results", "autoscaler_sensitivity"))
    args = parser.parse_args()
    started = time.time()
    os.makedirs(args.out_dir, exist_ok=True)
    grid = list(itertools.product([float(v) for v in args.mean_pods.split(",")],
                                  [float(v) for v in args.thresholds.split(",")],
                                  [int(v) for v in args.khpa_pods_min.split(",")]))

    # 1. Predictions once per node: they do not depend on the grid.
    trained = json.load(open(args.predictors_report))
    window = trained["chosen_window"]
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = {"FedAvg-BiGRU": sim.load_model("FedAvg-BiGRU", trained["settings"], args.weights_dir, window, device)}
    paths = [os.path.join(args.traces, f"node_{i:02d}.csv") for i in range(args.nodes)]
    holiday_days = french_holidays(load_node(paths[0])[0])
    nodes = []
    for path in paths:
        node = NodeData(path, window, holiday_days, device)
        requests = load_node(path)[1]
        minutes, forecasts = sim.node_inputs(node, requests, model)
        nodes.append((requests, minutes, forecasts))
    sim.log(f"Predictions ready for {len(nodes)} nodes. Grid of {len(grid)} combinations.")

    # 2. Every combination on every node, then the mean over the nodes.
    rows = []
    for mean_pods, threshold, khpa_min in grid:
        s = Settings(threshold=threshold)
        per_node = []
        for requests, minutes, forecasts in nodes:
            _, requested, runs = sim.simulate_node(requests, minutes, forecasts, s, mean_pods,
                                                   khpa_pods_min=khpa_min, predictors=["FedAvg-BiGRU"])
            per_node.append(sim.node_metrics(requested, runs))
        for name in SCALERS:
            values = [node[name] for node in per_node]
            row = {m: float(np.mean([v[m] for v in values])) for m in METRICS}
            speedups = np.array([v["speedup"] for v in values])
            finite = np.isfinite(speedups)
            row["speedup"] = float(speedups[finite].mean()) if finite.any() else float("inf")
            row["speedup_not_finite"] = int((~finite).sum())
            row["distance"] = distance(name, row)
            rows.append({"mean_pods": mean_pods, "threshold": threshold, "khpa_pods_min": khpa_min,
                         "scaler": name, **row})
        total = sum(r["distance"] for r in rows[-len(SCALERS):])
        sim.log(f"  mean {mean_pods:g}, threshold {threshold:g}, KHPA Pods_min {khpa_min}: distance {total:.1f}")

    # 3. Outputs
    with open(os.path.join(args.out_dir, "grid.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()} for r in rows)
    with open(os.path.join(args.out_dir, "sensitivity.md"), "w") as f:
        f.write(markdown(rows, grid))
    report = {"settings": vars(args), "table3": vars(Settings()), "fixed_pods": Settings().fixed_pods,
              "planner_pods_min": Settings().pods_min, "window": window, "device": device,
              "dogani_table11": {k: sim.DOGANI_TABLE11[k] for k in SCALERS},
              "rows": rows, "seconds": round(time.time() - started, 1)}
    with open(os.path.join(args.out_dir, "report.json"), "w") as f:
        json.dump(sim.json_safe(report), f, indent=2)
    sim.log(f"Done in {time.time() - started:.0f} s. Results in {args.out_dir}")


def key(r):
    return (r["mean_pods"], r["threshold"], r["khpa_pods_min"])


def markdown(rows, grid):
    """The ranking of the combinations, the closest one next to Dogani, and every row."""
    by = {(key(r), r["scaler"]): r for r in rows}
    totals = sorted(grid, key=lambda g: sum(by[(g, n)]["distance"] for n in SCALERS))
    lines = [
        "# Autoscaler sensitivity (step 4A)",
        "",
        "Mean over 16 nodes. Mean pods = mean traffic / 500, so the pods needed at 100% use.",
        "Threshold 0.7: pods = ceil(load / 350) for the requested pods, KHPA and the planner.",
        "No autoscaling stays at 15 pods. The planner's Pods_min stays 5.",
        "",
        "Distance = sum of |ours - Dogani| over θU, θO, TU, TO (Table 11, p. 17).",
        "Dogani's TO for no autoscaling (235.34) is left out, because TO cannot be above 100.",
        "",
        "## Ranking",
        "",
        "| Rank | Mean pods | Threshold | KHPA Pods_min | No autoscaling | KHPA | FedAvg-BiGRU | Total |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for rank, g in enumerate(totals, 1):
        d = [by[(g, n)]["distance"] for n in SCALERS]
        lines.append(f"| {rank} | {g[0]:g} | {g[1]:g} | {g[2]} | " + " | ".join(f"{v:.1f}" for v in d)
                     + f" | {sum(d):.1f} |")
    best_per_scaler = {n: min(grid, key=lambda g: by[(g, n)]["distance"]) for n in SCALERS}
    lines += ["", "Closest combination per scaler:", ""]
    for n, g in best_per_scaler.items():
        lines.append(f"- **{n}:** mean pods {g[0]:g}, threshold {g[1]:g}, KHPA Pods_min {g[2]} "
                     f"(distance {by[(g, n)]['distance']:.1f})")

    best = totals[0]
    lines += ["", f"## Closest combination: mean pods {best[0]:g}, threshold {best[1]:g}, "
                  f"KHPA Pods_min {best[2]}", "",
              "Each cell: ours / Dogani.", "",
              "| Scaler | θU | θO | TU | TO | εn |", "|---|---|---|---|---|---|"]
    for n in SCALERS:
        r, d = by[(best, n)], sim.DOGANI_TABLE11[n]
        cells = [f"{r[m]:.2f} / {v:.2f}" for m, v in zip(METRICS, d[:4])]
        lines.append(f"| {n} | " + " | ".join(cells) + f" | {speedup(r)} / {d[4]:.2f} |")

    lines += ["", "## All combinations", "",
              "| Mean pods | Threshold | KHPA Pods_min | Scaler | θU | θO | TU | TO | εn | Distance |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['mean_pods']:g} | {r['threshold']:g} | {r['khpa_pods_min']} | {r['scaler']} | "
                     + " | ".join(f"{r[m]:.2f}" for m in METRICS)
                     + f" | {speedup(r)} | {r['distance']:.1f} |")
    lines += ["", "Dogani, Table 11:", "", "| Scaler | θU | θO | TU | TO | εn |", "|---|---|---|---|---|---|"]
    for n in SCALERS:
        lines.append(f"| {n} | " + " | ".join(f"{v:.2f}" for v in sim.DOGANI_TABLE11[n][:5]) + " |")
    return "\n".join(lines) + "\n"


def speedup(r):
    """εn as text; ∞ and on how many nodes when it divides by 0."""
    if r["speedup_not_finite"] == 0:
        return f"{r['speedup']:.2f}"
    if np.isinf(r["speedup"]):
        return "∞"
    return f"{r['speedup']:.2f} (∞ on {r['speedup_not_finite']})"


if __name__ == "__main__":
    main()
