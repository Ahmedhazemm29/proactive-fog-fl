"""
Why is our BiGRU less accurate than Dogani's? Checks on the trained models of
step 3, without new training.

Usage:
    .venv/bin/python scripts/predictor_gap.py

1. STEPS: MAPE and MAE of every model at t+1 .. t+5, next to a naive
   forecast that repeats the last input minute ("persistence").
2. MAPE VARIANTS for FedAvg-BiGRU and CentralBiGRU at t+3: ours (real
   requests, zeros skipped), the same on min-max scaled values ([0, 1] and
   [-1, 1]), and MAPE per traffic level, relative to the node's test mean.
3. DATA: how bursty every node's test part is, next to the real FIFA trace
   over the same minutes: coefficient of variation, peak/mean, the 1-minute
   change relative to the mean, the lag-1 autocorrelation and the
   persistence MAPE at t+3.

Reads data/synthetic/, data/predictors/ (the step 3 weights) and the real
trace data/fifa_requests_per_minute_days5-92.csv. Writes
results/predictor_gap/report.md and report.json.
"""
import argparse
import json
import os
import sys

import numpy as np
import torch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import simulate_autoscaler as sim  # noqa: E402
from predictors.data import HORIZON, NodeData, french_holidays, load_node, split_bounds  # noqa: E402
from predictors.evaluate import metrics  # noqa: E402
from predictors.training import predict  # noqa: E402

MODELS = ["FedAvg-BiGRU", "FedAvg-LSTM", "CentralBiGRU", "CentralLSTM"]
DOGANI_MAPE = {"FedAvg-BiGRU": [9.04, 10.2, 11.2], "FedAvg-LSTM": [11.2, 12.4, 14.1],
               "CentralBiGRU": [8.49, 9.66, 10.45], "CentralLSTM": [10.4, 11.3, 13.1]}
LEVELS = [(0, 0.25), (0.25, 0.5), (0.5, 1), (1, 2), (2, np.inf)]     # real value / node test mean


def mape(predicted, real):
    nonzero = real != 0
    return float(np.mean(np.abs((predicted[nonzero] - real[nonzero]) / real[nonzero])) * 100)


def shape(x):
    """Burstiness of one series of requests per minute."""
    x = np.asarray(x, dtype=float)
    c = x - x.mean()
    return {"mean": float(x.mean()), "cv": float(x.std() / x.mean()), "peak_mean": float(x.max() / x.mean()),
            "step_change": float(np.mean(np.abs(np.diff(x))) / x.mean()),
            "acf1": float(np.dot(c[1:], c[:-1]) / np.dot(c, c))}


def persistence_mape(x, window, step):
    """MAPE of 'the value step minutes ahead = the last input minute', on windows inside x."""
    last = x[window - 1:len(x) - step]
    target = x[window - 1 + step:]
    return mape(last, target)


def main():
    parser = argparse.ArgumentParser(description="Checks on the predictor gap to Dogani.")
    parser.add_argument("--nodes", type=int, default=16)
    parser.add_argument("--weights-dir", default=os.path.join(ROOT, "data", "predictors"))
    parser.add_argument("--report", default=os.path.join(ROOT, "results", "predictors", "report.json"))
    parser.add_argument("--real", default=os.path.join(ROOT, "data", "fifa_requests_per_minute_days5-92.csv"))
    parser.add_argument("--out-dir", default=os.path.join(ROOT, "results", "predictor_gap"))
    args = parser.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    trained = json.load(open(args.report))
    window, settings = trained["chosen_window"], trained["settings"]
    device = "cuda" if torch.cuda.is_available() else "cpu"
    models = {m: sim.load_model(m, settings, args.weights_dir, window, device) for m in MODELS}
    paths = [os.path.join(ROOT, "data", "synthetic", f"node_{n:02d}.csv") for n in range(args.nodes)]

    # ---------- predictions of the test windows, per node ----------
    pred = {m: [] for m in MODELS + ["Persistence"]}
    real, mean_of_node, nodes_shape, nodes = [], [], [], []
    for path in paths:
        minutes, requests = load_node(path)
        node = NodeData(path, window, french_holidays(minutes), device)
        starts = node.starts["test"].cpu().numpy()
        r = None
        for m, model in models.items():
            p, r = predict(model, node)
            pred[m].append(p)
        last = requests[starts + window - 1]
        pred["Persistence"].append(np.repeat(last[:, None], HORIZON, axis=1))
        real.append(r)
        first, end = node.bounds["test"]
        test = requests[first:end]
        mean_of_node.append(np.full(len(r), test.mean()))
        nodes_shape.append({"node": node.name, **shape(test), "persistence_t3": persistence_mape(test, window, 3)})
        nodes.append(node)
    y = np.concatenate(real)
    p = {m: np.concatenate(v) for m, v in pred.items()}
    node_mean = np.concatenate(mean_of_node)

    # 1. Every step, every model and persistence
    steps = []
    for m in MODELS + ["Persistence"]:
        for k in range(HORIZON):
            steps.append({"model": m, "step": f"t+{k + 1}", **metrics(p[m][:, k], y[:, k])})

    # 2. MAPE variants at t+3 for the two BiGRUs
    k = 2
    variants = {}
    for m in ["FedAvg-BiGRU", "CentralBiGRU"]:
        scaled01, scaled11 = [], []
        offset = 0
        for node, r in zip(nodes, real):
            n = len(r)
            low, span = node.scaler.low[0], node.scaler.span[0]
            a, b = (p[m][offset:offset + n, k] - low) / span, (r[:, k] - low) / span
            scaled01.append((a, b))
            scaled11.append((2 * a - 1, 2 * b - 1))
            offset += n
        levels = []
        for lo, hi in LEVELS:
            inside = (y[:, k] / node_mean >= lo) & (y[:, k] / node_mean < hi)
            levels.append({"level": f"{lo:g} to {hi:g} x mean", "share": float(inside.mean()),
                           "mape": mape(p[m][inside, k], y[inside, k])})
        variants[m] = {
            "ours": mape(p[m][:, k], y[:, k]),
            "scaled_0_1": mape(np.concatenate([a for a, _ in scaled01]), np.concatenate([b for _, b in scaled01])),
            "scaled_-1_1": mape(np.concatenate([a for a, _ in scaled11]), np.concatenate([b for _, b in scaled11])),
            "levels": levels}

    # 3. The real trace over the same minutes as the test parts (days 6 to 92, last 20%)
    data = np.genfromtxt(args.real, delimiter=",", names=True, dtype=None, encoding="utf-8")
    keep = data["minute_paris"].astype("datetime64[m]") >= np.datetime64("1998-05-01T00:00")
    real_trace = data["requests"][keep].astype(float)
    first, end = split_bounds(len(real_trace))["test"]
    real_test = real_trace[first:end]
    real_shape = {"node": "real FIFA trace", **shape(real_test), "persistence_t3": persistence_mape(real_test, window, 3)}
    whole = {"real": shape(real_trace), "synthetic node_00": shape(load_node(paths[0])[1])}

    report = {"window": window, "steps": steps, "variants": variants, "data": nodes_shape + [real_shape],
              "whole_series": whole}
    with open(os.path.join(args.out_dir, "report.json"), "w") as f:
        json.dump(report, f, indent=1)
    with open(os.path.join(args.out_dir, "report.md"), "w") as f:
        f.write(markdown(report))
    print(markdown(report))


def markdown(report):
    value = {(r["model"], r["step"]): r for r in report["steps"]}
    lines = ["# Predictor gap to Dogani: checks without new training", "",
             f"Step 3 models (W = {report['window']}), test part of all 16 nodes pooled. "
             "Persistence repeats the last input minute. MAPE skips minutes with 0 real requests.", "",
             "## MAPE (%) at every step", "",
             "| Model | t+1 | t+2 | t+3 | t+4 | t+5 | Dogani t+3 / t+4 / t+5 |", "|---|---|---|---|---|---|---|"]
    for m in MODELS + ["Persistence"]:
        cells = [f"{value[(m, f't+{s}')]['mape']:.2f}" for s in range(1, HORIZON + 1)]
        dogani = " / ".join(str(v) for v in DOGANI_MAPE[m]) if m in DOGANI_MAPE else "–"
        lines.append(f"| {m} | " + " | ".join(cells) + f" | {dogani} |")
    lines += ["", "## MAE (requests per minute) at every step", "",
              "| Model | t+1 | t+2 | t+3 | t+4 | t+5 |", "|---|---|---|---|---|---|"]
    for m in MODELS + ["Persistence"]:
        lines.append(f"| {m} | " + " | ".join(f"{value[(m, f't+{s}')]['mae']:.1f}"
                                               for s in range(1, HORIZON + 1)) + " |")
    lines += ["", "## MAPE at t+3, computed different ways", "",
              "| Model | Real requests (ours) | Min-max [0, 1] | Min-max [-1, 1] |", "|---|---|---|---|"]
    for m, v in report["variants"].items():
        lines.append(f"| {m} | {v['ours']:.2f} | {v['scaled_0_1']:.2f} | {v['scaled_-1_1']:.2f} |")
    lines += ["", "## MAPE at t+3 by traffic level", "",
              "Level = the real requests of the minute divided by the node's test mean.", "",
              "| Level | Share of minutes | FedAvg-BiGRU | CentralBiGRU |", "|---|---|---|---|"]
    a, b = report["variants"]["FedAvg-BiGRU"]["levels"], report["variants"]["CentralBiGRU"]["levels"]
    for la, lb in zip(a, b):
        lines.append(f"| {la['level']} | {100 * la['share']:.1f}% | {la['mape']:.2f} | {lb['mape']:.2f} |")
    lines += ["", "## How bursty is each test part", "",
              "CV = std / mean. 1-minute change = mean absolute change from one minute to the next, "
              "divided by the mean. The real trace is the FIFA trace over the same minutes (the last 20% of "
              "days 6 to 92).", "",
              "| Series | Mean | CV | Peak/mean | 1-minute change | Lag-1 ACF | Persistence MAPE t+3 |",
              "|---|---|---|---|---|---|---|"]
    for d in report["data"]:
        lines.append(f"| {d['node']} | {d['mean']:,.0f} | {d['cv']:.2f} | {d['peak_mean']:.1f} | "
                     f"{100 * d['step_change']:.1f}% | {d['acf1']:.4f} | {d['persistence_t3']:.2f} |")
    w = report["whole_series"]
    lines += ["", "Whole series (all 87 days): real trace CV {:.2f}, lag-1 ACF {:.4f}, 1-minute change {:.1f}%; "
              "synthetic node_00 CV {:.2f}, lag-1 ACF {:.4f}, 1-minute change {:.1f}%.".format(
                  w["real"]["cv"], w["real"]["acf1"], 100 * w["real"]["step_change"],
                  w["synthetic node_00"]["cv"], w["synthetic node_00"]["acf1"],
                  100 * w["synthetic node_00"]["step_change"]), ""]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
