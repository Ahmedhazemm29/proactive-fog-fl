"""
Table 8 on random windows: how much do the predictor errors, and the ranking
of the four models, depend on which part of the test period is scored?

results/predictors/table8.md scores each model once, pooled over the whole
test part (last 20% of every node, about 17 days) of all 16 nodes. Here the
same trained seed-0 models are scored on N random windows of the test part
instead (no retraining):
    - a window is LENGTH consecutive forecasts (default 1440 = one day),
      starting at a random point, the same minutes on all 16 nodes
    - in a window the errors are pooled over the 16 nodes with the rules of
      table8.md: real requests, MAPE skips minutes with 0 real requests
    - all four models are scored on exactly the same windows
    - the window starts come from --seed, so a run can be repeated exactly
The test part holds about 17 days, so 30 one-day windows overlap.

The models, the data and their settings come from results/predictors/report.json
(the Table 8 run). Before the windows, every model is scored on the whole test
part once more: that must give the numbers of table8.md (metrics.csv).

Outputs in results/predictors/random_windows/:
    summary.md       mean ± sd per model and step, where the Table 8 value falls,
                     first places, BiGRU vs LSTM per step
    windows.csv      the windows: number, first forecast, first minute, seed
    per_window.csv   every window's MAPE, MAE, RMSE per model and step
    boxplot_<metric>.png and .pdf, one per metric

Usage:  .venv/bin/python scripts/table8_random_windows.py
        .venv/bin/python scripts/table8_random_windows.py --windows 30 --length 1440 --seed 1
"""
import argparse
import csv
import json
import os
import statistics
import sys

import matplotlib
matplotlib.use("Agg")  # draw straight to files, no window needed
import matplotlib.pyplot as plt
import numpy as np
import torch
from matplotlib.patches import Patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from predictors.data import NodeData, french_holidays, load_node  # noqa: E402
from predictors.evaluate import metrics  # noqa: E402
from predictors.models import ARCHITECTURES  # noqa: E402
from predictors.training import predict  # noqa: E402
from train_predictors import EVAL_STEPS, MODELS  # noqa: E402

TABLE8_DIR = os.path.join(ROOT, "results", "predictors")
OUT_DIR = os.path.join(TABLE8_DIR, "random_windows")
METRICS = [("mape", "MAPE (%)"), ("mae", "MAE (requests/min)"), ("rmse", "RMSE (requests/min)")]
STEPS = [f"t+{s}" for s in EVAL_STEPS]
PAIRS = [("FedAvg", "FedAvg-BiGRU", "FedAvg-LSTM"), ("Central", "CentralBiGRU", "CentralLSTM")]

# Colour = architecture (categorical slots 1 and 2 of the validated default
# palette), solid = FedAvg, hatched = central: two encodings, so no colour
# has to carry four models on its own.
COLORS = {"BiGRU": "#2a78d6", "LSTM": "#eb6834"}
INK, MUTED = "#2b2b29", "#8a8a84"


def architecture(model):
    """'FedAvg-BiGRU' -> 'BiGRU', 'CentralLSTM' -> 'LSTM'."""
    return model.replace("FedAvg-", "").replace("Central", "")


# ----------------------------------------------------------------------
# 1. The forecasts of the Table 8 models
# ----------------------------------------------------------------------
def load_forecasts(report, device):
    """
    {model: (predicted, real)}, each (nodes, forecasts, HORIZON) in real
    requests, for the test part of every node, from the Table 8 weights.
    """
    s = report["settings"]
    window = report["chosen_window"]
    paths = [os.path.join(s["traces"], f"node_{i:02d}.csv") for i in range(s["nodes"])]
    holiday_days = french_holidays(load_node(paths[0])[0])
    scale = tuple(float(v) for v in s.get("scale", "0,1").split(","))
    nodes = [NodeData(path, window, holiday_days, device, scale) for path in paths]
    forecasts = {}
    for name in MODELS:
        model = ARCHITECTURES[architecture(name)](s["units"], s["dropout"])
        weights = os.path.join(s["weights_dir"], f"{name}_W{window}.pt")
        model.load_state_dict(torch.load(weights, map_location=device, weights_only=True))
        model.to(device)
        with torch.no_grad():
            out = [predict(model, node) for node in nodes]
        forecasts[name] = (np.stack([p for p, _ in out]), np.stack([r for _, r in out]))
    return forecasts, nodes[0].target_minutes("test")


# ----------------------------------------------------------------------
# 2. Windows and their errors
# ----------------------------------------------------------------------
def sample_starts(count, length, n_forecasts, seed):
    """`count` random window starts; a window must fit inside the n_forecasts forecasts."""
    rng = np.random.default_rng(seed)
    return [int(s) for s in rng.integers(0, n_forecasts - length + 1, size=count)]


def window_metrics(predicted, real, start, length):
    """
    {(step, metric): value} of one model in one window: the forecasts
    start .. start+length-1 of every node, pooled over the nodes.
    """
    out = {}
    for step_number, step in zip(EVAL_STEPS, STEPS):
        k = step_number - 1
        m = metrics(predicted[:, start:start + length, k].ravel(),
                    real[:, start:start + length, k].ravel())
        for metric, _ in METRICS:
            out[(step, metric)] = m[metric]
    return out


def full_test_metrics(predicted, real):
    """The same, on the whole test part: must equal table8.md."""
    return window_metrics(predicted, real, 0, predicted.shape[1])


def read_table8():
    """{(model, step, metric): value} from results/predictors/metrics.csv."""
    with open(os.path.join(TABLE8_DIR, "metrics.csv")) as f:
        return {(row["model"], row["step"], metric): float(row[metric])
                for row in csv.DictReader(f) for metric, _ in METRICS}


# ----------------------------------------------------------------------
# 3. Summaries over the windows
# ----------------------------------------------------------------------
def mean_sd(values):
    return statistics.mean(values), (statistics.stdev(values) if len(values) > 1 else float("nan"))


def share_below(values, reference):
    """Share of the windows (%) whose value is below the reference value."""
    return 100 * sum(v < reference for v in values) / len(values)


def first_places(per_window, step, metric):
    """{model: in how many windows it has the lowest error} for one step and metric."""
    counts = {name: 0 for name in MODELS}
    for scores in per_window:
        best = min(MODELS, key=lambda name: scores[name][(step, metric)])
        counts[best] += 1
    return counts


def bigru_wins(per_window, bigru, lstm, step, metric):
    """In how many windows BiGRU has the lower error than LSTM."""
    return sum(s[bigru][(step, metric)] < s[lstm][(step, metric)] for s in per_window)


# ----------------------------------------------------------------------
# 4. Output
# ----------------------------------------------------------------------
def write_summary(path, per_window, table8, args, n_forecasts, check):
    n = len(per_window)
    lines = ["# Table 8 on random windows", "",
             f"The trained seed-0 models of `results/predictors/table8.md` (no retraining), scored "
             f"on {n} random windows of the test part instead of the whole test part. A window is "
             f"{args.length} consecutive forecasts ({args.length / 1440:g} day), the same minutes "
             f"on all 16 nodes, starting at a random point (seed {args.seed}, `windows.csv`). In "
             f"a window the errors are pooled over the 16 nodes with the rules of table8.md: real "
             f"requests, MAPE skips minutes with 0 real requests. The test part has {n_forecasts:,} "
             f"forecasts per node (about {n_forecasts / 1440:.1f} days), so the windows overlap. "
             "Written by `scripts/table8_random_windows.py`.", "",
             f"Check: scored on the whole test part, these weights give table8.md's numbers "
             f"(largest relative difference {check:.1e}).", ""]

    lines += ["## Mean ± sd over the windows, and where Table 8 falls", "",
              "\"Table 8\" is the value of table8.md (whole test part). \"Below\" is the share of "
              "windows with a lower value than Table 8.", ""]
    for metric, title in METRICS:
        digits = 2 if metric == "mape" else 1
        lines += [f"**{title}**", "",
                  "| Model | " + " | ".join(f"{s} mean ± sd | {s} min to max | {s} Table 8 (below)"
                                           for s in STEPS) + " |",
                  "|---|" + "---|" * (3 * len(STEPS))]
        for name in MODELS:
            cells = []
            for step in STEPS:
                values = [w[name][(step, metric)] for w in per_window]
                m, sd = mean_sd(values)
                ref = table8[(name, step, metric)]
                cells += [f"{m:.{digits}f} ± {sd:.{digits}f}",
                          f"{min(values):.{digits}f} to {max(values):.{digits}f}",
                          f"{ref:.{digits}f} ({share_below(values, ref):.0f}%)"]
            lines.append(f"| {name} | " + " | ".join(cells) + " |")
        lines.append("")

    lines += ["## How often each model ranks first", "",
              f"Windows (of {n}) in which the model has the lowest error of the four.", "",
              "| Model | " + " | ".join(f"{title.split(' ')[0]} {s}" for _, title in METRICS
                                       for s in STEPS) + " |",
              "|---|" + "---|" * (len(METRICS) * len(STEPS))]
    firsts = {(step, metric): first_places(per_window, step, metric)
              for metric, _ in METRICS for step in STEPS}
    for name in MODELS:
        lines.append(f"| {name} | " + " | ".join(str(firsts[(step, metric)][name])
                                                 for metric, _ in METRICS for step in STEPS) + " |")
    lines.append("")

    lines += ["## BiGRU vs LSTM per step", "",
              f"Windows (of {n}) in which BiGRU has the lower error than LSTM. In brackets: "
              "the winner in table8.md (B = BiGRU, L = LSTM).", "",
              "| Pair | Metric | " + " | ".join(STEPS) + " |", "|---|---|" + "---|" * len(STEPS)]
    for pair, bigru, lstm in PAIRS:
        for metric, title in METRICS:
            cells = []
            for step in STEPS:
                t8 = "B" if table8[(bigru, step, metric)] < table8[(lstm, step, metric)] else "L"
                cells.append(f"{bigru_wins(per_window, bigru, lstm, step, metric)} ({t8})")
            lines.append(f"| {pair} | {title.split(' ')[0]} | " + " | ".join(cells) + " |")
    lines += ["", "Box plots: `boxplot_mape.png`, `boxplot_mae.png`, `boxplot_rmse.png` "
              "(and .pdf).", ""]
    with open(path, "w") as f:
        f.write("\n".join(lines))


def write_csvs(out_dir, starts, minutes, args, per_window):
    with open(os.path.join(out_dir, "windows.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["window", "first_forecast", "first_minute", "length", "seed"])
        for i, start in enumerate(starts, start=1):
            writer.writerow([i, start, str(minutes[start]), args.length, args.seed])
    with open(os.path.join(out_dir, "per_window.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["window", "model", "step"] + [m for m, _ in METRICS])
        for i, scores in enumerate(per_window, start=1):
            for name in MODELS:
                for step in STEPS:
                    writer.writerow([i, name, step] + [f"{scores[name][(step, m)]:.4f}"
                                                       for m, _ in METRICS])


def style():
    plt.rcParams.update({
        "font.size": 10, "axes.labelsize": 10, "legend.fontsize": 8.5,
        "xtick.labelsize": 9, "ytick.labelsize": 9, "pdf.fonttype": 42,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": INK, "ytick.color": INK,
        "axes.grid": True, "grid.color": "#e4e4e0", "grid.linewidth": 0.6,
    })


def plot_box(out_dir, metric, title, per_window, table8):
    """Per step four boxes (one per model) over the windows; a black diamond marks Table 8."""
    fig, ax = plt.subplots(figsize=(7.2, 3.8))
    width = 0.18
    for s, step in enumerate(STEPS):
        for m, name in enumerate(MODELS):
            x = s + (m - 1.5) * (width + 0.03)
            values = [w[name][(step, metric)] for w in per_window]
            color = COLORS[architecture(name)]
            box = ax.boxplot([values], positions=[x], widths=width, patch_artist=True,
                             showfliers=True, flierprops={"marker": "o", "markersize": 3,
                                                          "markerfacecolor": color,
                                                          "markeredgecolor": "white"},
                             medianprops={"color": INK, "linewidth": 1.4},
                             whiskerprops={"color": MUTED}, capprops={"color": MUTED})["boxes"][0]
            central = name.startswith("Central")
            box.set(facecolor="white" if central else color, edgecolor=color, linewidth=1.3,
                    hatch="////" if central else None, alpha=1.0 if central else 0.55)
            ax.plot(x, table8[(name, step, metric)], marker="D", markersize=4.5, color=INK,
                    linestyle="none", zorder=4)
    ax.set_xticks(range(len(STEPS)), STEPS)
    ax.set_ylabel(title)
    ax.grid(axis="x", visible=False)
    handles = [Patch(facecolor=COLORS["BiGRU"], alpha=0.55, edgecolor=COLORS["BiGRU"], label="FedAvg-BiGRU"),
               Patch(facecolor=COLORS["LSTM"], alpha=0.55, edgecolor=COLORS["LSTM"], label="FedAvg-LSTM"),
               Patch(facecolor="white", edgecolor=COLORS["BiGRU"], hatch="////", label="CentralBiGRU"),
               Patch(facecolor="white", edgecolor=COLORS["LSTM"], hatch="////", label="CentralLSTM"),
               plt.Line2D([], [], marker="D", markersize=4.5, color=INK, linestyle="none",
                          label="Table 8 (whole test part)")]
    ax.legend(handles=handles, ncol=3, frameon=False, loc="upper left", bbox_to_anchor=(0, 1.22))
    ax.set_title(f"{title.split(' ')[0]} on {len(per_window)} random one-day windows",
                 fontsize=10, color=INK, loc="left", pad=40)
    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(os.path.join(out_dir, f"boxplot_{metric}.{ext}"), dpi=150)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description="Score the Table 8 models on random test windows.")
    parser.add_argument("--windows", type=int, default=30, help="number of windows (default 30)")
    parser.add_argument("--length", type=int, default=1440,
                        help="forecasts per window, 1440 = one day (default)")
    parser.add_argument("--seed", type=int, default=1, help="seed of the window starts (default 1)")
    parser.add_argument("--out-dir", default=OUT_DIR)
    args = parser.parse_args()

    with open(os.path.join(TABLE8_DIR, "report.json")) as f:
        report = json.load(f)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    forecasts, minutes = load_forecasts(report, device)

    # Check: the whole test part must give table8.md's numbers.
    table8 = read_table8()
    check = max(abs(full_test_metrics(*forecasts[name])[(step, metric)] - table8[(name, step, metric)])
                / table8[(name, step, metric)]
                for name in MODELS for step in STEPS for metric, _ in METRICS)
    print(f"whole test part vs table8.md: largest relative difference {check:.1e}")
    if check > 1e-3:
        sys.exit("the weights do not reproduce table8.md, stopping")

    n_forecasts = forecasts[MODELS[0]][0].shape[1]
    starts = sample_starts(args.windows, args.length, n_forecasts, args.seed)
    per_window = [{name: window_metrics(*forecasts[name], start, args.length) for name in MODELS}
                  for start in starts]

    os.makedirs(args.out_dir, exist_ok=True)
    write_csvs(args.out_dir, starts, minutes, args, per_window)
    write_summary(os.path.join(args.out_dir, "summary.md"), per_window, table8, args,
                  n_forecasts, check)
    style()
    for metric, title in METRICS:
        plot_box(args.out_dir, metric, title, per_window, table8)
    print(f"Wrote {args.out_dir}: summary.md, windows.csv, per_window.csv, 3 box plots")


if __name__ == "__main__":
    main()
