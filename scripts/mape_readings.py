"""
Which MAPE did Dogani compute? Every reading of Eq. 13 on the same saved
forecasts, and a check against Dogani's own MAE and MAPE (decision 3.12).

Usage:
    .venv/bin/python scripts/mape_readings.py

1. BANDS: where quiet, normal and busy minutes land on [-1, 1], and the MAPE
   of each band in real requests and on [-1, 1].
2. READINGS: MAPE of FedAvg-BiGRU (seed 0, and the mean of seeds 0, 1 and 2)
   and of "repeat the last minute" under every reading in predictors/mape.py.
3. CONSISTENCY: the mean traffic per node that makes Dogani's MAE and MAPE fit
   together under each reading, at t+3, t+4 and t+5, against the FIFA trace
   given to every node in full or split over 16 nodes.
4. RATIO: model error divided by the error of "repeat the last minute".
5. [-1, 1] TRAINING: the BiGRUs trained on [-1, 1] (decision 3.12), when
   their weights exist.

Forecasts come from the saved weights (step 3 in data/predictors/, the
experiments in data/predictor_gap/). They are computed once and kept in
data/predictor_gap/forecasts/. Writes results/predictor_gap/mape_readings.md
and mape_readings.json.
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
from predictors import mape  # noqa: E402
from predictors.data import HORIZON, NodeData, french_holidays, load_node  # noqa: E402
from predictors.models import ARCHITECTURES  # noqa: E402
from predictors.training import predict  # noqa: E402
from train_predictors import DOGANI_TABLE8  # noqa: E402

FIFA_REQUESTS, FIFA_DAYS, NODES = 1_352_804_107, 88, 16
FULL = FIFA_REQUESTS / (FIFA_DAYS * 1440)                 # mean requests per minute of the whole trace
STEPS = [3, 4, 5]
SEEDS = ["FedAvg-BiGRU seed 0", "FedAvg-BiGRU seed 1", "FedAvg-BiGRU seed 2"]
PREDICTORS_DIR = os.path.join(ROOT, "data", "predictors")
GAP_DIR = os.path.join(ROOT, "data", "predictor_gap")
# run: (model, weights file, min-max range it was trained with)
RUNS = {
    "FedAvg-BiGRU seed 0": ("FedAvg-BiGRU", os.path.join(PREDICTORS_DIR, "FedAvg-BiGRU_W30.pt"), (0.0, 1.0)),
    "FedAvg-BiGRU seed 1": ("FedAvg-BiGRU", os.path.join(GAP_DIR, "seed1_FedAvg-BiGRU.pt"), (0.0, 1.0)),
    "FedAvg-BiGRU seed 2": ("FedAvg-BiGRU", os.path.join(GAP_DIR, "seed2_FedAvg-BiGRU.pt"), (0.0, 1.0)),
    "CentralBiGRU seed 0": ("CentralBiGRU", os.path.join(PREDICTORS_DIR, "CentralBiGRU_W30.pt"), (0.0, 1.0)),
    "FedAvg-BiGRU [-1, 1]": ("FedAvg-BiGRU", os.path.join(GAP_DIR, "scale11_FedAvg-BiGRU.pt"), (-1.0, 1.0)),
    "CentralBiGRU [-1, 1]": ("CentralBiGRU", os.path.join(GAP_DIR, "scale11_CentralBiGRU.pt"), (-1.0, 1.0)),
}
BANDS = [("quiet", 0, 0.25), ("normal", 0.25, 2), ("busy", 2, np.inf)]     # real / node mean


def forecasts(run, nodes, cache_dir):
    """(nodes, windows, HORIZON) forecasts and real values of one run, from the cache or the weights."""
    model_name, weights, _ = RUNS[run]
    cache = os.path.join(cache_dir, run.replace(" ", "_").replace(",", "").replace("[", "").replace("]", "") + ".npz")
    if os.path.exists(cache) and os.path.getmtime(cache) > os.path.getmtime(weights):
        saved = np.load(cache)
        return saved["predicted"], saved["real"]
    model = ARCHITECTURES[model_name.replace("FedAvg-", "").replace("Central", "")](64, 0.3)
    model.load_state_dict(torch.load(weights, map_location="cpu", weights_only=True))
    model.to(nodes[0].series.device)
    out = [predict(model, node) for node in nodes]
    predicted, real = np.stack([p for p, _ in out]), np.stack([r for _, r in out])
    os.makedirs(cache_dir, exist_ok=True)
    np.savez_compressed(cache, predicted=predicted, real=real)
    return predicted, real


def readings(scalers):
    """{key: (label, function of the nodes' (predicted, real) pairs)}. scalers: per node (low, span) of requests."""
    low_all = min(lo for lo, _ in scalers)
    span_all = max(lo + sp for lo, sp in scalers) - low_all

    def on_scale(a, b, glob):
        def f(pairs):
            sc = [(low_all, span_all) if glob else s for s in scalers]
            p = np.concatenate([mape.scale(pr, lo, sp, a, b) for (pr, _), (lo, sp) in zip(pairs, sc)])
            r = np.concatenate([mape.scale(re, lo, sp, a, b) for (_, re), (lo, sp) in zip(pairs, sc)])
            return mape.mape(p, r, floor=-np.inf)
        return f
    return {
        "a": ("Real requests, skip only zeros (ours)", lambda pairs: mape.pooled(pairs)),
        "b1": ("Real requests, skip below 1% of the node mean", lambda pairs: mape.pooled(pairs, 0.01)),
        "b5": ("Real requests, skip below 5% of the node mean", lambda pairs: mape.pooled(pairs, 0.05)),
        "b10": ("Real requests, skip below 10% of the node mean", lambda pairs: mape.pooled(pairs, 0.10)),
        "c": ("Real requests, each node first, then the mean over nodes", mape.per_node),
        "d": ("Real requests, one total trace of all 16 nodes", mape.of_total),
        "e1": ("[0, 1], each node's own scaling", on_scale(0.0, 1.0, False)),
        "e2": ("[-1, 1], each node's own scaling", on_scale(-1.0, 1.0, False)),
        "e3": ("[0, 1], one scaling for all nodes", on_scale(0.0, 1.0, True)),
        "e4": ("[-1, 1], one scaling for all nodes", on_scale(-1.0, 1.0, True)),
    }


def pairs_of(predicted, real, k):
    return [(predicted[n, :, k], real[n, :, k]) for n in range(len(real))]


def main():
    parser = argparse.ArgumentParser(description="Every reading of MAPE on the same forecasts.")
    parser.add_argument("--report", default=os.path.join(ROOT, "results", "predictors", "report.json"))
    parser.add_argument("--cache-dir", default=os.path.join(GAP_DIR, "forecasts"))
    parser.add_argument("--real", default=os.path.join(ROOT, "data", "fifa_requests_per_minute_days5-92.csv"))
    parser.add_argument("--out-dir", default=os.path.join(ROOT, "results", "predictor_gap"))
    args = parser.parse_args()
    window = json.load(open(args.report))["chosen_window"]
    device = "cuda" if torch.cuda.is_available() else "cpu"
    paths = [os.path.join(ROOT, "data", "synthetic", f"node_{n:02d}.csv") for n in range(NODES)]
    holiday_days = french_holidays(load_node(paths[0])[0])
    nodes = {}

    def nodes_for(scale_range):
        if scale_range not in nodes:
            nodes[scale_range] = [NodeData(p, window, holiday_days, device, scale_range) for p in paths]
        return nodes[scale_range]

    runs = {}
    for run, (_, weights, scale_range) in RUNS.items():
        if os.path.exists(weights):
            runs[run] = forecasts(run, nodes_for(scale_range), args.cache_dir)
    base = nodes_for((0.0, 1.0))
    scalers = [(node.scaler.low[0], node.scaler.span[0]) for node in base]
    real = runs["FedAvg-BiGRU seed 0"][1]
    # "Repeat the last minute": the real requests of each window's last input minute, for all 5 steps
    last = np.stack([load_node(path)[1][node.starts["test"].cpu().numpy() + window - 1]
                     for path, node in zip(paths, base)])
    runs["Persistence"] = (np.repeat(last[:, :, None], HORIZON, axis=2), real)
    read = readings(scalers)

    # ---------- 2. every reading, every run, t+3 .. t+5 ----------
    table = {run: {key: [f(pairs_of(*runs[run], s - 1)) for s in STEPS] for key, (_, f) in read.items()}
             for run in runs}
    mae = {run: [float(np.mean(np.abs(runs[run][0][:, :, s - 1] - real[:, :, s - 1]))) for s in STEPS] for run in runs}
    mae_total = {run: [float(np.mean(np.abs(runs[run][0][:, :, s - 1].sum(0) - real[:, :, s - 1].sum(0))))
                       for s in STEPS] for run in runs}
    seed_mean = {key: list(np.mean([table[s][key] for s in SEEDS], axis=0)) for key in read}
    seed_mae = list(np.mean([mae[s] for s in SEEDS], axis=0))
    seed_mae_total = list(np.mean([mae_total[s] for s in SEEDS], axis=0))
    mean_node = [float(real[:, :, s - 1].mean()) for s in STEPS]
    mean_total = [float(real[:, :, s - 1].sum(0).mean()) for s in STEPS]

    # ---------- 1. where the minutes land on [-1, 1], seed 0 at t+3 ----------
    k = 2
    p0 = runs["FedAvg-BiGRU seed 0"][0][:, :, k]
    r0 = real[:, :, k]
    level = r0 / r0.mean(axis=1, keepdims=True)
    lows, spans = np.array([s[0] for s in scalers])[:, None], np.array([s[1] for s in scalers])[:, None]
    ps, rs = mape.scale(p0, lows, spans, -1, 1), mape.scale(r0, lows, spans, -1, 1)
    bands = []
    for name, lo, hi in BANDS:
        inside = (level >= lo) & (level < hi)
        bands.append({"band": name, "level": f"{lo:g} to {hi:g} x node mean", "share": float(inside.mean()),
                      "position": float(rs[inside].mean()), "position_min": float(rs[inside].min()),
                      "position_max": float(rs[inside].max()),
                      "mape_real": mape.mape(p0[inside], r0[inside]),
                      "mape_11": mape.mape(ps[inside], rs[inside], floor=-np.inf)})
    quiet = level < 0.25
    quiet_mape = {run: mape.mape(runs[run][0][:, :, k][quiet], r0[quiet]) for run in runs}
    near = (np.abs(rs) < 0.05) & (rs != 0)                # exact zeros are skipped, as in mape.mape
    ape = np.abs((ps - rs) / rs)[near] * 100
    near_zero = {"minutes": int(near.sum()), "share": float(near.mean()),
                 "mape": float(ape.mean()) if near.any() else None, "largest": float(ape.max()) if near.any() else None,
                 "points": float(ape.sum() / (rs != 0).sum()) if near.any() else 0.0,
                 "closest": float(np.abs(rs).min())}

    # ---------- 3. what MAE 166.8 and MAPE 9.04 imply, per reading ----------
    dogani = DOGANI_TABLE8["FedAvg-BiGRU"]
    # The real FIFA trace over the test minutes (days 6 to 92, last 20%): the end of the tournament
    data = np.genfromtxt(args.real, delimiter=",", names=True, dtype=None, encoding="utf-8")
    trace = data["requests"][data["minute_paris"].astype("datetime64[m]") >= np.datetime64("1998-05-01T00:00")]
    real_test_mean = float(trace[int(round(0.8 * len(trace))):].mean())
    consistency = []
    for key, (label, _) in read.items():
        total = key == "d"
        implied = [mape.implied_mean_traffic(dogani[3 + i], dogani[i],
                                             (seed_mae_total if total else seed_mae)[i],
                                             (mean_total if total else mean_node)[i], seed_mean[key][i])
                   for i in range(3)]
        times = NODES if total else 1
        candidates = {"whole trace per node, all days": times * FULL,
                      "whole trace per node, its test part": times * real_test_mean,
                      "trace split over 16 nodes, all days": times * FULL / NODES,
                      "trace split over 16 nodes, its test part": times * real_test_mean / NODES}
        nearest = min(candidates, key=lambda c: abs(np.log(implied[0] / candidates[c])))
        off = max(implied[0] / candidates[nearest], candidates[nearest] / implied[0])
        consistency.append({"reading": key, "label": label, "implied": implied, "nearest": nearest,
                            "candidate": candidates[nearest], "off_by": off,
                            "spread": max(implied) / min(implied),
                            "dogani_vs_our_naive": dogani[0] / table["Persistence"][key][0],
                            "our_model_vs_naive": seed_mean[key][0] / table["Persistence"][key][0]})

    report = {"window": window, "full_trace_mean": FULL, "real_test_mean": real_test_mean, "readings": {k: v[0] for k, v in read.items()},
              "mape": table, "seed_mean": seed_mean, "mae": mae, "mae_total": mae_total, "seed_mae": seed_mae,
              "mean_node": mean_node, "mean_total": mean_total, "bands": bands, "near_zero": near_zero,
              "quiet": quiet_mape,
              "consistency": consistency}
    os.makedirs(args.out_dir, exist_ok=True)
    with open(os.path.join(args.out_dir, "mape_readings.json"), "w") as f:
        json.dump(report, f, indent=1)
    text = markdown(report)
    with open(os.path.join(args.out_dir, "mape_readings.md"), "w") as f:
        f.write(text)
    print(text)


def markdown(r):
    t, sm = r["mape"], r["seed_mean"]
    dog = DOGANI_TABLE8["FedAvg-BiGRU"]
    lines = ["# Which MAPE did Dogani compute?", "",
             f"The same saved forecasts (W = {r['window']}, test part of all 16 nodes) under every reading of "
             "Eq. 13. \"3 seeds\" is the mean of the MAPEs of FedAvg-BiGRU seeds 0, 1 and 2. \"Naive\" repeats "
             "the last input minute.", "",
             "## 1. Where the minutes land on [-1, 1] (FedAvg-BiGRU seed 0, t+3)", "",
             "| Band | Share of minutes | Position on [-1, 1], mean (range) | MAPE, real requests | MAPE, [-1, 1] |",
             "|---|---|---|---|---|"]
    for b in r["bands"]:
        lines.append(f"| {b['band']} ({b['level']}) | {100 * b['share']:.1f}% | {b['position']:+.2f} "
                     f"({b['position_min']:+.2f} to {b['position_max']:+.2f}) | {b['mape_real']:.2f} | "
                     f"{b['mape_11']:.2f} |")
    nz = r["near_zero"]
    lines += ["", f"Minutes within 0.05 of 0 on [-1, 1]: {nz['minutes']} ({100 * nz['share']:.2f}%). "
              + (f"Their MAPE is {nz['mape']:.1f}%, the largest single error {nz['largest']:.0f}%, and they add "
                 f"{nz['points']:.2f} points to the total. " if nz["minutes"] else "")
              + f"The closest real minute to 0 is at {nz['closest']:.4f}.", "",
              "## 2. MAPE (%) under every reading, t+3 / t+4 / t+5", "",
              "| Reading | FedAvg-BiGRU seed 0 | 3 seeds | Naive | 3 seeds / naive at t+3 |", "|---|---|---|---|---|"]
    for key, label in r["readings"].items():
        fmt = lambda v: " / ".join(f"{x:.2f}" for x in v)                      # noqa: E731
        lines.append(f"| {key}. {label} | {fmt(t['FedAvg-BiGRU seed 0'][key])} | {fmt(sm[key])} | "
                     f"{fmt(t['Persistence'][key])} | {sm[key][0] / t['Persistence'][key][0]:.2f} |")
    lines += ["", f"Dogani's FedAvg-BiGRU: {dog[0]} / {dog[1]} / {dog[2]}.", "",
              "## 3. What Dogani's MAE and MAPE imply, per reading", "",
              f"Dogani's FedAvg-BiGRU: MAE {dog[3]} / {dog[4]} / {dog[5]} and MAPE {dog[0]} / {dog[1]} / {dog[2]} "
              "at t+3 / t+4 / t+5. If his errors have the same shape as ours, MAE / mean traffic is the same "
              "multiple of MAPE for him and for us. That gives the mean traffic his numbers imply. "
              f"The FIFA trace has {FIFA_REQUESTS:,} requests over {FIFA_DAYS} days: {r['full_trace_mean']:,.0f} "
              f"per minute if every node gets the whole trace, {r['full_trace_mean'] / NODES:,.0f} if it is split "
              "over 16 nodes. MAE is measured on the test part, so the candidates also include the real trace's "
              f"test part, the last 20% of the days and the end of the tournament: {r['real_test_mean']:,.0f} per "
              f"minute, or {r['real_test_mean'] / NODES:,.0f} split over 16 nodes. Reading d is the total of all "
              "nodes, so its candidates are 16 times larger.", "",
              "| Reading | Implied mean per minute, t+3 / t+4 / t+5 | Nearest candidate | Off by | "
              "Dogani / our naive, t+3 |", "|---|---|---|---|---|"]
    for c in sorted(r["consistency"], key=lambda c: c["off_by"]):
        lines.append(f"| {c['reading']}. {c['label']} | " + " / ".join(f"{v:,.0f}" for v in c["implied"])
                     + f" | {c['nearest']} ({c['candidate']:,.0f}) | x{c['off_by']:.2f} | "
                       f"{c['dogani_vs_our_naive']:.2f} |")
    lines += ["", "\"Off by\" compares the t+3 value with the nearest candidate. \"Dogani / our naive\" is his "
              "MAPE divided by the MAPE of repeating the last minute on our data under the same reading: below 1 "
              "means better than the naive forecast.", "",
              "## 4. Model error / naive error (unit-free)", "",
              "| Run | MAPE ratio t+3 / t+4 / t+5 | MAE ratio t+3 / t+4 / t+5 |", "|---|---|---|"]
    naive_a, naive_mae = t["Persistence"]["a"], r["mae"]["Persistence"]
    for run in [x for x in t if x != "Persistence"]:
        lines.append(f"| {run} | " + " / ".join(f"{a / b:.2f}" for a, b in zip(t[run]["a"], naive_a)) + " | "
                     + " / ".join(f"{a / b:.2f}" for a, b in zip(r["mae"][run], naive_mae)) + " |")
    lines.append(f"| 3 seeds | " + " / ".join(f"{a / b:.2f}" for a, b in zip(sm["a"], naive_a)) + " | "
                 + " / ".join(f"{a / b:.2f}" for a, b in zip(r["seed_mae"], naive_mae)) + " |")
    if "FedAvg-BiGRU [-1, 1]" in t:
        lines += ["", "## 5. Trained on [-1, 1] (seed 0)", "",
                  "| Run | MAPE real, t+3 / t+4 / t+5 | MAPE on [-1, 1], t+3 | MAE t+3 | Quiet minutes, MAPE t+3 |",
                  "|---|---|---|---|---|"]
        for run in ["FedAvg-BiGRU seed 0", "FedAvg-BiGRU [-1, 1]", "CentralBiGRU seed 0", "CentralBiGRU [-1, 1]"]:
            if run not in t:
                continue
            lines.append(f"| {run} | " + " / ".join(f"{v:.2f}" for v in t[run]["a"]) + f" | {t[run]['e2'][0]:.2f} | "
                         f"{r['mae'][run][0]:.1f} | {r['quiet'][run]:.2f} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
