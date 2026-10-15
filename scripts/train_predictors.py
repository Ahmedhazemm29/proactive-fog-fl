"""
Train and compare workload predictors on the synthetic node traces
(Dogani & Khunjush 2024, experiment 3 / Table 8).

Usage:
    .venv/bin/python scripts/train_predictors.py --nodes 2 --rounds 3 --central-epochs 2 \\
        --out-dir data/predictors/quick_test                       (quick test)
    .venv/bin/python scripts/train_predictors.py                    (16 nodes, full run)

Models: FedAvg-BiGRU (Dogani's proposal), FedAvg-LSTM, and CentralBiGRU /
CentralLSTM, trained on all nodes' training windows pooled.

1. DATA: each node's trace (data/synthetic/node_XX.csv) becomes 5 features per
   minute, scaled per node, split 60/20/20 in time (predictors/data.py).
2. WINDOW: FedAvg-BiGRU is trained once per window length in --windows; the
   one with the lowest validation loss is kept, and its W is used for the rest.
3. TRAIN: the other three models with that W.
4. EVALUATE: MAPE, MAE, RMSE for t+3, t+4, t+5 on every node's test part, in
   real requests; Diebold-Mariano test of FedAvg-BiGRU against each other
   model; size and communication cost of each model.

Outputs in --out-dir (default results/predictors/): table8.md, metrics.csv,
metrics_per_node.csv, dm.csv, cost.csv, report.json, prediction_node_XX.png.
Model weights go to --weights-dir (default data/predictors/, not in git).
"""
import argparse
import csv
import json
import os
import sys
import time

import numpy as np
import torch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from predictors.data import FEATURES, HORIZON, NodeData, PooledData, french_holidays, load_node  # noqa: E402
from predictors.evaluate import diebold_mariano, metrics  # noqa: E402
from predictors.federated import Client, run_fedavg  # noqa: E402
from predictors.models import ARCHITECTURES, model_bytes, parameter_count  # noqa: E402
from predictors.training import predict, train_central  # noqa: E402

MODELS = ["FedAvg-BiGRU", "FedAvg-LSTM", "CentralBiGRU", "CentralLSTM"]
EVAL_STEPS = [3, 4, 5]                  # t+3, t+4, t+5

# Dogani & Khunjush (2024), Table 8: MAPE, MAE, RMSE at t+3, t+4, t+5
DOGANI_TABLE8 = {
    "FedAvg-LSTM": [11.2, 12.4, 14.1, 204.3, 221.4, 279.7, 385.5, 414.7, 495.8],
    "CentralLSTM": [10.4, 11.3, 13.1, 192.7, 208.8, 263.9, 364.5, 392.1, 449.1],
    "FedAvg-BiGRU": [9.04, 10.2, 11.2, 166.8, 241.3, 221.9, 316.9, 389.2, 437.7],
    "CentralBiGRU": [8.49, 9.66, 10.45, 156.5, 213.0, 224.8, 296.7, 351.8, 406.3],
}


def log(text):
    print(text, flush=True)


# ----------------------------------------------------------------------
# Training
# ----------------------------------------------------------------------
def model_maker(name, args, device):
    """A function that builds a fresh model of the given kind ("FedAvg-BiGRU" -> BiGRU)."""
    architecture = ARCHITECTURES[name.replace("FedAvg-", "").replace("Central", "")]
    return lambda: architecture(args.units, args.dropout).to(device)


def load_nodes(paths, window, holiday_days, device):
    return [NodeData(path, window, holiday_days, device) for path in paths]


def train_federated(name, nodes, args, device):
    make_model = model_maker(name, args, device)
    torch.manual_seed(args.seed)
    clients = [Client(node, make_model, args.batch_size, args.lr, args.seed + i)
               for i, node in enumerate(nodes)]
    return run_fedavg(clients, make_model, args.rounds, args.local_epochs, args.fraction,
                      args.patience, args.seed, log)


def train_pooled(name, nodes, args, device):
    torch.manual_seed(args.seed)
    model = model_maker(name, args, device)()
    return train_central(model, PooledData(nodes), args.central_epochs, args.patience,
                         args.batch_size, args.lr, args.seed, log)


# ----------------------------------------------------------------------
# Evaluation
# ----------------------------------------------------------------------
def evaluate_all(models, nodes):
    """
    Test-set predictions of every model on every node, then metrics pooled over
    all nodes and per node, and the DM test of FedAvg-BiGRU against the others.
    """
    predictions = {name: [predict(model, node) for node in nodes] for name, model in models.items()}
    pooled, per_node, dm = [], [], []
    for name, per in predictions.items():
        for step in EVAL_STEPS:
            k = step - 1
            predicted = np.concatenate([p[:, k] for p, _ in per])
            real = np.concatenate([r[:, k] for _, r in per])
            pooled.append({"model": name, "step": f"t+{step}", **metrics(predicted, real)})
            for node, (p, r) in zip(nodes, per):
                per_node.append({"model": name, "node": node.name, "step": f"t+{step}",
                                 **metrics(p[:, k], r[:, k])})
    base = "FedAvg-BiGRU"
    for name in predictions:
        if name == base:
            continue
        for step in EVAL_STEPS:
            k = step - 1
            errors = {m: np.concatenate([p[:, k] - r[:, k] for p, r in predictions[m]]) for m in (base, name)}
            statistic, p_value = diebold_mariano(errors[base], errors[name], step)
            dm.append({"pair": f"{base} vs {name}", "step": f"t+{step}", "dm": statistic, "p_value": p_value})
    return predictions, pooled, per_node, dm


# ----------------------------------------------------------------------
# Outputs
# ----------------------------------------------------------------------
def write_csv(path, rows):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def table8_markdown(pooled, dm, cost, args, chosen_window, n_nodes):
    value = {(r["model"], r["step"], m): r[m] for r in pooled for m in ("mape", "mae", "rmse")}
    steps = [f"t+{s}" for s in EVAL_STEPS]
    header = ("| Model | " + " | ".join(f"MAPE {s}" for s in steps) + " | "
              + " | ".join(f"MAE {s}" for s in steps) + " | " + " | ".join(f"RMSE {s}" for s in steps) + " |")
    lines = [f"# Workload prediction, {n_nodes} synthetic FIFA nodes (like Dogani's Table 8)", "",
             f"W = {chosen_window} minutes, test part = last 20% of every node, errors pooled over all "
             "nodes' test windows, in requests per minute. MAPE in %.", "",
             header, "|---" * 10 + "|"]
    for name in MODELS:
        if any(k[0] == name for k in value):
            cells = [f"{value[(name, s, m)]:.2f}" if m == "mape" else f"{value[(name, s, m)]:.1f}"
                     for m in ("mape", "mae", "rmse") for s in steps]
            lines.append(f"| {name} (ours) | " + " | ".join(cells) + " |")
    for name in MODELS:
        lines.append(f"| {name} (Dogani) | " + " | ".join(str(v) for v in DOGANI_TABLE8[name]) + " |")
    skipped = {r["model"]: r["mape_skipped"] for r in pooled}
    lines += ["", f"MAPE skips minutes with 0 real requests: {max(skipped.values())} per model and step "
              "(pooled over all nodes).", "",
              "## Diebold-Mariano test (absolute errors)", "",
              "| Pair | " + " | ".join(f"DM {s} | p {s}" for s in steps) + " |", "|---" * 7 + "|"]
    for pair in dict.fromkeys(r["pair"] for r in dm):
        cells = [f"{r['dm']:.2f} | {r['p_value']:.3g}" for r in dm if r["pair"] == pair]
        lines.append(f"| {pair} | " + " | ".join(cells) + " |")
    lines += ["", "DM > 0: FedAvg-BiGRU has the larger errors. p < 0.05: the accuracy differs.", "",
              "## Size and communication", "",
              "| Model | Parameters | Model bytes | Rounds or epochs | Bytes per round | Bytes in total | Training time (s) |",
              "|---|---|---|---|---|---|---|"]
    for row in cost:
        lines.append(f"| {row['model']} | {row['parameters']:,} | {row['model_bytes']:,} | "
                     f"{row['rounds_or_epochs']} | {format(row['bytes_per_round'], ',') if row['bytes_per_round'] else '–'} | "
                     f"{row['bytes_total']:,} | {row['train_seconds']} |")
    lines += ["", "Federated: bytes = model weights down and up for every chosen client. Central: "
              "bytes = every node's training and validation minutes (5 float32 features) sent once.", ""]
    return "\n".join(lines)


def plot_node(path, node, predictions, node_index, hours):
    """Real requests and every model's t+3 prediction for the `hours` around the busiest test minute."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    step = 3
    real = next(iter(predictions.values()))[node_index][1][:, step - 1]
    minutes = node.target_minutes("test") + np.timedelta64(step - 1, "m")
    centre = int(np.argmax(real))
    half = hours * 30
    part = slice(max(0, centre - half), min(len(real), centre + half))
    t = minutes[part].astype("datetime64[s]").astype(object)

    style = {"FedAvg-BiGRU": ("#3987e5", "-"), "CentralBiGRU": ("#3987e5", "--"),
             "FedAvg-LSTM": ("#d95926", "-"), "CentralLSTM": ("#d95926", "--")}
    fig, ax = plt.subplots(figsize=(13, 4.5))
    ax.plot(t, real[part], color="#1f2937", lw=1.6, label="real")
    for name, per in predictions.items():
        color, line = style[name]
        ax.plot(t, per[node_index][0][part, step - 1], color=color, ls=line, lw=1.1, label=name)
    ax.set_title(f"{node.name}: real requests and t+{step} predictions (test part, Paris time)", loc="left")
    ax.set_ylabel("requests per minute")
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    locator = mdates.AutoDateLocator()
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    ax.grid(color="#e5e7eb", lw=0.8)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(frameon=False, ncol=5, loc="upper left")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Train FedAvg and central BiGRU / LSTM predictors.")
    parser.add_argument("--traces", default=os.path.join(ROOT, "data", "synthetic"), help="node_XX.csv folder")
    parser.add_argument("--nodes", type=int, default=16, help="nodes = FL clients (default 16)")
    parser.add_argument("--windows", default="30,60", help="window lengths W to try (default 30,60)")
    parser.add_argument("--rounds", type=int, default=100, help="max FedAvg rounds (default 100)")
    parser.add_argument("--local-epochs", type=int, default=1, help="local epochs E per round (default 1)")
    parser.add_argument("--fraction", type=float, default=1.0, help="share of clients per round (default 1.0)")
    parser.add_argument("--central-epochs", type=int, default=64, help="max central epochs (default 64)")
    parser.add_argument("--patience", type=int, default=5,
                        help="stop after this many rounds or epochs without a better validation loss (default 5)")
    parser.add_argument("--units", type=int, default=64)
    parser.add_argument("--dropout", type=float, default=0.3)
    parser.add_argument("--batch-size", type=int, default=60)
    parser.add_argument("--lr", type=float, default=1e-3, help="Adam learning rate (default 0.001)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--plot-node", type=int, default=0)
    parser.add_argument("--plot-hours", type=int, default=6)
    parser.add_argument("--out-dir", default=os.path.join(ROOT, "results", "predictors"))
    parser.add_argument("--weights-dir", default=os.path.join(ROOT, "data", "predictors"))
    args = parser.parse_args()

    started = time.time()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    log(f"Device: {torch.cuda.get_device_name(0) if device.type == 'cuda' else 'CPU'}")
    paths = [os.path.join(args.traces, f"node_{i:02d}.csv") for i in range(args.nodes)]
    holiday_days = french_holidays(load_node(paths[0])[0])
    log(f"French holidays in the traces: {', '.join(str(d) for d in holiday_days)}")
    os.makedirs(args.out_dir, exist_ok=True)
    os.makedirs(args.weights_dir, exist_ok=True)

    # STEP 2: pick W with FedAvg-BiGRU
    windows = [int(w) for w in args.windows.split(",")]
    tried = {}
    for window in windows:
        log(f"FedAvg-BiGRU, W = {window}:")
        nodes = load_nodes(paths, window, holiday_days, device)
        tried[window] = (nodes, *train_federated("FedAvg-BiGRU", nodes, args, device))
    chosen = min(windows, key=lambda w: tried[w][3]["best_val_loss"])
    log("W selection: " + ", ".join(f"W = {w}: val MAE {tried[w][3]['best_val_loss']:.5f}" for w in windows)
        + f" -> W = {chosen}")
    nodes, model, history, cost = tried[chosen]
    trained = {"FedAvg-BiGRU": (model, history, cost)}

    # STEP 3: the other three models
    log("FedAvg-LSTM:")
    trained["FedAvg-LSTM"] = train_federated("FedAvg-LSTM", nodes, args, device)
    for name in ("CentralBiGRU", "CentralLSTM"):
        log(f"{name}:")
        trained[name] = train_pooled(name, nodes, args, device)

    # STEP 4: evaluate
    models = {name: trained[name][0] for name in MODELS}
    predictions, pooled, per_node, dm = evaluate_all(models, nodes)
    central_bytes = sum((n.bounds["val"][1] - n.bounds["train"][0]) for n in nodes) * len(FEATURES) * 4
    cost_rows = []
    for name in MODELS:
        model, history, c = trained[name]
        federated = name.startswith("FedAvg")
        cost_rows.append({"model": name, "parameters": parameter_count(model), "model_bytes": model_bytes(model),
                          "rounds_or_epochs": c["rounds"] if federated else c["epochs"],
                          "best_round_or_epoch": c["best_round"] if federated else c["best_epoch"],
                          "bytes_per_round": c["bytes_per_round"] if federated else None,
                          "bytes_total": c["bytes_total"] if federated else central_bytes,
                          "train_seconds": c["train_seconds"]})
        torch.save(model.state_dict(), os.path.join(args.weights_dir, f"{name}_W{chosen}.pt"))

    write_csv(os.path.join(args.out_dir, "metrics.csv"), pooled)
    write_csv(os.path.join(args.out_dir, "metrics_per_node.csv"), per_node)
    write_csv(os.path.join(args.out_dir, "dm.csv"), dm)
    write_csv(os.path.join(args.out_dir, "cost.csv"), cost_rows)
    with open(os.path.join(args.out_dir, "table8.md"), "w") as f:
        f.write(table8_markdown(pooled, dm, cost_rows, args, chosen, len(nodes)))
    plot_node(os.path.join(args.out_dir, f"prediction_node_{args.plot_node:02d}.png"),
              nodes[args.plot_node], predictions, args.plot_node, args.plot_hours)
    report = {"settings": vars(args), "device": str(device), "features": FEATURES, "horizon": HORIZON,
              "holidays": [str(d) for d in holiday_days],
              "split_minutes": nodes[0].bounds, "windows_per_node": {s: nodes[0].count(s) for s in nodes[0].starts},
              "window_selection": {w: tried[w][3]["best_val_loss"] for w in windows}, "chosen_window": chosen,
              "history": {name: trained[name][1] for name in MODELS},
              "cost": cost_rows, "total_seconds": round(time.time() - started, 1)}
    with open(os.path.join(args.out_dir, "report.json"), "w") as f:
        json.dump(report, f, indent=2, default=str)
    log(f"Done in {time.time() - started:.0f} s. Results in {os.path.relpath(args.out_dir, ROOT)}/")


if __name__ == "__main__":
    main()
