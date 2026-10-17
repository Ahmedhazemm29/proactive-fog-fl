"""
Small training experiments on the predictor gap: one model, one setting.

Usage:
    .venv/bin/python scripts/predictor_experiments.py --model FedAvg-BiGRU --seed 1 --tag seed1
    .venv/bin/python scripts/predictor_experiments.py --model FedAvg-BiGRU --units 32 --tag units32

Same data, W, training and stopping rule as the step 3 run in
results/predictors/report.json (patience 10). Only the options given here
change. The step 3 results and weights are not touched: the weights go to
data/predictor_gap/<tag>_<model>.pt, and one row per step t+1 .. t+5 is added
to results/predictor_gap/experiments.csv (MAPE and MAE pooled over the test
part of all 16 nodes, as in Table 8).
"""
import argparse
import csv
import json
import os
import sys
import time

import torch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import train_predictors as tp  # noqa: E402
from predictors.data import HORIZON, french_holidays, load_node  # noqa: E402
from predictors.evaluate import metrics  # noqa: E402
from predictors.training import predict  # noqa: E402

import numpy as np  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Train one predictor with one changed setting.")
    parser.add_argument("--model", choices=tp.MODELS, required=True)
    parser.add_argument("--tag", required=True, help="name of this experiment, e.g. seed1")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--units", type=int, default=None)
    parser.add_argument("--report", default=os.path.join(ROOT, "results", "predictors", "report.json"))
    parser.add_argument("--out", default=os.path.join(ROOT, "results", "predictor_gap", "experiments.csv"))
    parser.add_argument("--weights-dir", default=os.path.join(ROOT, "data", "predictor_gap"))
    options = parser.parse_args()

    # The step 3 settings, with the changed ones on top
    trained = json.load(open(options.report))
    args = argparse.Namespace(**trained["settings"])
    for key in ("seed", "units"):
        if getattr(options, key) is not None:
            setattr(args, key, getattr(options, key))
    window = trained["chosen_window"]
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    paths = [os.path.join(args.traces, f"node_{i:02d}.csv") for i in range(args.nodes)]
    nodes = tp.load_nodes(paths, window, french_holidays(load_node(paths[0])[0]), device)

    started = time.time()
    train = tp.train_federated if options.model.startswith("FedAvg") else tp.train_pooled
    model, _, cost = train(options.model, nodes, args, device)
    seconds = time.time() - started
    os.makedirs(options.weights_dir, exist_ok=True)
    torch.save(model.state_dict(), os.path.join(options.weights_dir, f"{options.tag}_{options.model}.pt"))

    per = [predict(model, node) for node in nodes]
    rows = []
    for k in range(HORIZON):
        m = metrics(np.concatenate([p[:, k] for p, _ in per]), np.concatenate([r[:, k] for _, r in per]))
        rows.append({"tag": options.tag, "model": options.model, "seed": args.seed, "units": args.units,
                     "rounds_or_epochs": cost.get("rounds", cost.get("epochs")),
                     "best": cost.get("best_round", cost.get("best_epoch")),
                     "train_seconds": round(seconds), "step": f"t+{k + 1}",
                     "mape": round(m["mape"], 3), "mae": round(m["mae"], 1)})
    os.makedirs(os.path.dirname(options.out), exist_ok=True)
    new = not os.path.exists(options.out)
    with open(options.out, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        if new:
            writer.writeheader()
        writer.writerows(rows)
    print(f"{options.tag} {options.model}: {rows[0]['rounds_or_epochs']} rounds or epochs (best {rows[0]['best']}), "
          f"{seconds / 60:.1f} min, MAPE " + " / ".join(f"{r['mape']:.2f}" for r in rows), flush=True)


if __name__ == "__main__":
    main()
