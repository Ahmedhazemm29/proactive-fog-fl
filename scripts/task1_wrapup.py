"""
Task 1 wrap-up: was Table 8 luck?

Puts the two Table 8 checks side by side, without training or scoring
anything again:
    - random seeds (PR #33): the 4 models trained with seeds 0, 1, 2, 3 and
      scored on the whole test part; seed 0 is the Table 8 run
    - random windows (PR #34): the seed-0 models scored on 30 random one-day
      windows of the test part

Reads (never changes):
    results/predictors/metrics.csv                      Table 8, full precision
    results/predictors/seeds/summary.csv                every seed, 4 decimals
    results/predictors/random_windows/per_window.csv    every window
    results/predictors/random_windows/windows.csv       where the windows start
    results/predictors/report.json                      split borders, W, traces folder
    <traces>/node_XX.csv                                synthetic traffic (timeline only)

Writes results/task1/:
    spread.csv     mean, sd, min, max over the seeds and over the windows
    ranking.csv    the model order of every seed and window, per metric and step
    tables.md      the tables of docs/task1_summary.md
    figures/       windows_<metric>.png, seeds_<metric>.png, ranking.png, timeline.png

Usage:  .venv/bin/python scripts/task1_wrapup.py
"""
import csv
import json
import os
import statistics
import sys

import matplotlib
matplotlib.use("Agg")  # draw straight to files, no window needed
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from train_predictors import EVAL_STEPS, MODELS  # noqa: E402

TABLE8_DIR = os.path.join(ROOT, "results", "predictors")
SEEDS_CSV = os.path.join(TABLE8_DIR, "seeds", "summary.csv")
WINDOWS_DIR = os.path.join(TABLE8_DIR, "random_windows")
OUT_DIR = os.path.join(ROOT, "results", "task1")
METRICS = [("mape", "MAPE (%)"), ("mae", "MAE (requests/min)"), ("rmse", "RMSE (requests/min)")]
STEPS = [f"t+{s}" for s in EVAL_STEPS]
SHORT = {"FedAvg-BiGRU": "FB", "FedAvg-LSTM": "FL", "CentralBiGRU": "CB", "CentralLSTM": "CL"}
TWO_LINES = {"FedAvg-BiGRU": "FedAvg\nBiGRU", "FedAvg-LSTM": "FedAvg\nLSTM",
             "CentralBiGRU": "Central\nBiGRU", "CentralLSTM": "Central\nLSTM"}   # axis labels

# Same encoding as the PR #34 box plots: colour = architecture,
# filled = FedAvg, hollow = central.
COLORS = {"BiGRU": "#2a78d6", "LSTM": "#eb6834"}
INK, MUTED = "#2b2b29", "#8a8a84"
RANK_COLORS = ["#1b4f8a", "#4f86c6", "#a3c4e6", "#e3edf7"]   # 1st (dark) to 4th (light)


# ----------------------------------------------------------------------
# 1. Reading
# ----------------------------------------------------------------------
def read_runs(path, key):
    """{run: {(model, step, metric): value}} from a CSV with columns key, model, step, metrics.

    key=None reads a single run (Table 8's metrics.csv) and returns it under run 0.
    """
    runs = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            run = int(row[key]) if key else 0
            for metric, _ in METRICS:
                runs.setdefault(run, {})[(row["model"], row["step"], metric)] = float(row[metric])
    return runs


def check_complete(runs, what):
    """Every run must have all 4 models x 3 steps x 3 metrics."""
    expected = {(m, s, k) for m in MODELS for s in STEPS for k, _ in METRICS}
    for run, scores in runs.items():
        if set(scores) != expected:
            sys.exit(f"{what} {run} is incomplete: {len(scores)} of {len(expected)} values")


# ----------------------------------------------------------------------
# 2. Numbers
# ----------------------------------------------------------------------
def spread(values):
    """Mean, sample standard deviation, min and max of a list."""
    return {"mean": statistics.mean(values), "sd": statistics.stdev(values),
            "min": min(values), "max": max(values)}


def ranking(scores, step, metric):
    """The 4 models from best (lowest error) to worst, as a tuple."""
    return tuple(sorted(MODELS, key=lambda name: scores[(name, step, metric)]))


def stability(runs, reference, step, metric):
    """In how many runs the whole order, and the best model, equal the reference's."""
    ref = ranking(reference, step, metric)
    orders = [ranking(scores, step, metric) for scores in runs.values()]
    return {"same_order": sum(o == ref for o in orders),
            "same_best": sum(o[0] == ref[0] for o in orders), "n": len(orders)}


def rank_counts(runs, metric):
    """{model: [times 1st, 2nd, 3rd, 4th]} over all runs and the 3 steps."""
    counts = {name: [0, 0, 0, 0] for name in MODELS}
    for scores in runs.values():
        for step in STEPS:
            for place, name in enumerate(ranking(scores, step, metric)):
                counts[name][place] += 1
    return counts


def gap_vs_spread(runs, step, metric):
    """Two sizes, both in % of the mean error, to compare in the summary:
    gap    = median over runs of (worst model - best model) / mean of the 4 models
    spread = mean over the models of sd / mean across the runs (coefficient of variation)
    """
    gaps = []
    for scores in runs.values():
        values = [scores[(name, step, metric)] for name in MODELS]
        gaps.append(100 * (max(values) - min(values)) / statistics.mean(values))
    cvs = []
    for name in MODELS:
        values = [scores[(name, step, metric)] for scores in runs.values()]
        cvs.append(100 * statistics.stdev(values) / statistics.mean(values))
    return statistics.median(gaps), statistics.mean(cvs)


# ----------------------------------------------------------------------
# 3. Tables
# ----------------------------------------------------------------------
def fmt(value, metric):
    return f"{value:.2f}" if metric == "mape" else f"{value:.1f}"


def write_csvs(out_dir, table8, seeds, windows):
    with open(os.path.join(out_dir, "spread.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["source", "n", "model", "step", "metric", "table8",
                         "mean", "sd", "min", "max"])
        for source, runs in (("seeds", seeds), ("windows", windows)):
            for name in MODELS:
                for metric, _ in METRICS:
                    for step in STEPS:
                        s = spread([r[(name, step, metric)] for r in runs.values()])
                        writer.writerow([source, len(runs), name, step, metric,
                                         f"{table8[(name, step, metric)]:.4f}",
                                         *(f"{s[k]:.4f}" for k in ("mean", "sd", "min", "max"))])
    with open(os.path.join(out_dir, "ranking.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["source", "run", "metric", "step", "order_best_to_worst", "same_as_table8"])
        for source, runs in (("table8", {0: table8}), ("seeds", seeds), ("windows", windows)):
            for run, scores in runs.items():
                for metric, _ in METRICS:
                    for step in STEPS:
                        order = ranking(scores, step, metric)
                        writer.writerow([source, run, metric, step, " < ".join(SHORT[n] for n in order),
                                         order == ranking(table8, step, metric)])


def write_tables(path, table8, seeds, windows):
    n_seeds, n_windows = len(seeds), len(windows)
    lines = ["<!-- Written by scripts/task1_wrapup.py; do not edit by hand. -->", ""]

    # Spread per metric
    for metric, title in METRICS:
        lines += [f"**{title}**", "",
                  f"| Model | Step | Table 8 | Windows mean ± sd (n={n_windows}) | Windows min to max "
                  f"| Seeds mean ± sd (n={n_seeds}) | Seeds min to max |",
                  "|---|---|---|---|---|---|---|"]
        for name in MODELS:
            for step in STEPS:
                w = spread([r[(name, step, metric)] for r in windows.values()])
                s = spread([r[(name, step, metric)] for r in seeds.values()])
                lines.append(f"| {name} | {step} | {fmt(table8[(name, step, metric)], metric)} "
                             f"| {fmt(w['mean'], metric)} ± {fmt(w['sd'], metric)} "
                             f"| {fmt(w['min'], metric)} to {fmt(w['max'], metric)} "
                             f"| {fmt(s['mean'], metric)} ± {fmt(s['sd'], metric)} "
                             f"| {fmt(s['min'], metric)} to {fmt(s['max'], metric)} |")
        lines.append("")

    # Ranking stability
    other_seeds = {k: v for k, v in seeds.items() if k != 0}   # seed 0 is Table 8 itself
    lines += ["**Model ranking (best to worst) against Table 8**", "",
              "FB = FedAvg-BiGRU, FL = FedAvg-LSTM, CB = CentralBiGRU, CL = CentralLSTM. "
              f"Seeds: the {len(other_seeds)} seeds other than seed 0 (seed 0 is Table 8).", "",
              "| Metric | Step | Table 8 order | Windows: same order | Windows: same best "
              "| Seeds: same order | Seeds: same best |",
              "|---|---|---|---|---|---|---|"]
    totals = {"w_order": 0, "w_best": 0, "s_order": 0, "s_best": 0, "w_n": 0, "s_n": 0}
    for metric, title in METRICS:
        for step in STEPS:
            order = " < ".join(SHORT[n] for n in ranking(table8, step, metric))
            w = stability(windows, table8, step, metric)
            s = stability(other_seeds, table8, step, metric)
            totals["w_order"] += w["same_order"]
            totals["w_best"] += w["same_best"]
            totals["s_order"] += s["same_order"]
            totals["s_best"] += s["same_best"]
            totals["w_n"] += w["n"]
            totals["s_n"] += s["n"]
            lines.append(f"| {title.split(' ')[0]} | {step} | {order} "
                         f"| {w['same_order']} of {w['n']} | {w['same_best']} of {w['n']} "
                         f"| {s['same_order']} of {s['n']} | {s['same_best']} of {s['n']} |")
    lines += [f"| **All** | | | **{totals['w_order']} of {totals['w_n']}** "
              f"| **{totals['w_best']} of {totals['w_n']}** "
              f"| **{totals['s_order']} of {totals['s_n']}** | **{totals['s_best']} of {totals['s_n']}** |",
              ""]

    # Model gap against run-to-run spread
    lines += ["**Model gap against run-to-run spread** (both in % of the mean error)", "",
              "Gap = median over the runs of (worst model - best model) / mean of the 4 models. "
              "Spread = sd / mean across the runs, averaged over the 4 models.", "",
              "| Metric | Step | Windows: gap | Windows: spread | Seeds: gap | Seeds: spread |",
              "|---|---|---|---|---|---|"]
    for metric, title in METRICS:
        for step in STEPS:
            wg, ws = gap_vs_spread(windows, step, metric)
            sg, ss = gap_vs_spread(seeds, step, metric)
            lines.append(f"| {title.split(' ')[0]} | {step} | {wg:.1f} | {ws:.1f} | {sg:.1f} | {ss:.1f} |")
    lines.append("")
    with open(path, "w") as f:
        f.write("\n".join(lines))


# ----------------------------------------------------------------------
# 4. Figures
# ----------------------------------------------------------------------
def style():
    """Large fonts: the figures go on slides."""
    plt.rcParams.update({
        "font.size": 13, "axes.labelsize": 13, "axes.titlesize": 14, "legend.fontsize": 12,
        "xtick.labelsize": 12, "ytick.labelsize": 12,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": INK, "ytick.color": INK,
        "axes.grid": True, "grid.color": "#e4e4e0", "grid.linewidth": 0.6,
    })


def model_marker(name):
    """Colour by architecture; FedAvg filled, central hollow."""
    color = COLORS["BiGRU" if "BiGRU" in name else "LSTM"]
    return color, (color if name.startswith("FedAvg") else "white")


def legend_handles(points_label):
    handles = []
    for name in MODELS:
        edge, face = model_marker(name)
        handles.append(Line2D([], [], marker="o", markersize=8, linestyle="none",
                              markeredgecolor=edge, markerfacecolor=face, markeredgewidth=1.6,
                              label=f"{name} ({points_label})"))
    handles.append(Line2D([], [], marker="D", markersize=10, linestyle="none", color=INK,
                          label="Table 8 value"))
    return handles


def plot_spread(path, runs, table8, metric, title, label, boxes):
    """One panel per step: every run as a dot per model, Table 8 as a black diamond.
    boxes=True also draws a box per model (for the 30 windows; 4 seeds are too few)."""
    fig, axes = plt.subplots(1, len(STEPS), figsize=(13, 5.2), sharey=True)
    rng = np.random.default_rng(0)   # only spreads the dots sideways, so they do not hide each other
    for ax, step in zip(axes, STEPS):
        for i, name in enumerate(MODELS):
            values = [scores[(name, step, metric)] for scores in runs.values()]
            edge, face = model_marker(name)
            if boxes:
                ax.boxplot([values], positions=[i], widths=0.55, showfliers=False,
                           medianprops={"color": INK, "linewidth": 1.6},
                           boxprops={"color": MUTED}, whiskerprops={"color": MUTED},
                           capprops={"color": MUTED})
            else:   # a short line at the mean
                ax.plot([i - 0.25, i + 0.25], [statistics.mean(values)] * 2, color=INK, linewidth=1.6)
            ax.scatter(i + rng.uniform(-0.15, 0.15, len(values)), values, s=36, color=face,
                       edgecolors=edge, linewidths=1.4, zorder=3, alpha=0.85)
            ax.plot(i + 0.33, table8[(name, step, metric)], marker="D", markersize=10,
                    color=INK, linestyle="none", zorder=4)
        ax.set_xticks(range(len(MODELS)), [TWO_LINES[n] for n in MODELS])
        ax.set_xlim(-0.6, len(MODELS) - 0.4)
        ax.set_title(step, color=INK)
        ax.grid(axis="x", visible=False)
    axes[0].set_ylabel(title)
    fig.legend(handles=legend_handles(label), ncol=3, frameon=False, loc="upper center",
               bbox_to_anchor=(0.5, 1.0))
    fig.tight_layout(rect=(0, 0, 1, 0.86))
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_ranking(path, seeds, windows):
    """How often each model is 1st, 2nd, 3rd, 4th, per metric, over all runs and the 3 steps."""
    fig, axes = plt.subplots(2, len(METRICS), figsize=(14, 7.5), sharey=True)
    for row, (runs, source) in enumerate(((windows, f"{len(windows)} windows"),
                                          (seeds, f"{len(seeds)} seeds"))):
        for col, (metric, title) in enumerate(METRICS):
            ax = axes[row][col]
            counts = rank_counts(runs, metric)
            total = len(runs) * len(STEPS)
            for y, name in enumerate(MODELS):
                left = 0
                for place, n in enumerate(counts[name]):
                    share = 100 * n / total
                    ax.barh(y, share, left=left, color=RANK_COLORS[place], edgecolor="white")
                    if share >= 9:
                        ax.text(left + share / 2, y, str(n), ha="center", va="center", fontsize=11,
                                color="white" if place < 2 else INK)
                    left += share
            ax.set_yticks(range(len(MODELS)), MODELS)
            ax.invert_yaxis()
            ax.set_xlim(0, 100)
            ax.set_xlabel(f"% of {total} rankings")
            ax.set_title(f"{title.split(' ')[0]}, {source}", color=INK, loc="left")
            ax.grid(axis="y", visible=False)
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in RANK_COLORS]
    fig.legend(handles, ["1st (best)", "2nd", "3rd", "4th (worst)"], ncol=4, frameon=False,
               loc="upper center", bbox_to_anchor=(0.5, 1.0))
    fig.text(0.5, 0.005, "Numbers in the bars: count of rankings. Each run is ranked at t+3, t+4 and t+5.",
             ha="center", fontsize=11, color=MUTED)
    fig.tight_layout(rect=(0, 0.03, 1, 0.94))
    fig.savefig(path, dpi=150)
    plt.close(fig)


def load_timeline(report):
    """Minutes and total requests of all nodes (synthetic traces of the Table 8 run)."""
    folder = report["settings"]["traces"]
    minutes, total = None, None
    for i in range(report["settings"]["nodes"]):
        path = os.path.join(folder, f"node_{i:02d}.csv")
        data = np.loadtxt(path, delimiter=",", skiprows=1, dtype=str)
        node_minutes = data[:, 0].astype("datetime64[m]")
        requests = data[:, 1].astype(float)
        if minutes is None:
            minutes, total = node_minutes, requests
        elif not np.array_equal(minutes, node_minutes):
            sys.exit(f"{path} has other minutes than node_00.csv")
        else:
            total = total + requests
    return minutes, total


def window_spans(report, windows_rows, minutes):
    """[(window, first minute, last minute)] of every window's t+1 targets.

    Forecast k of the test part predicts from minute test_start + W + k on
    (NodeData.target_minutes), so a window starting at forecast s covers the
    minutes test_start + W + s ... + length - 1. Checked against windows.csv.
    """
    test_start = report["split_minutes"]["test"][0]
    w = report["chosen_window"]
    spans = []
    for row in windows_rows:
        first = test_start + w + int(row["first_forecast"])
        if str(minutes[first]) != row["first_minute"]:
            sys.exit(f"window {row['window']}: computed {minutes[first]}, windows.csv {row['first_minute']}")
        spans.append((int(row["window"]), first, first + int(row["length"]) - 1))
    return spans


def plot_timeline(path, report, minutes, total, spans):
    """Top: the whole dataset with its splits. Bottom: the test part with every window as a bar."""
    split = report["split_minutes"]
    hourly_minutes = minutes[::60]
    hourly = total[: len(total) // 60 * 60].reshape(-1, 60).mean(axis=1) / 1000
    fig, (top, mid, low) = plt.subplots(3, 1, figsize=(14, 9), height_ratios=[1, 1, 2.2])

    top.plot(hourly_minutes, hourly, color=INK, linewidth=0.7)
    for (name, (a, b)), color in zip(split.items(), ("#d9e6f5", "#f6e3c7", "#d8efd9")):
        top.axvspan(minutes[a], minutes[b - 1], color=color, zorder=0)
        top.text(minutes[(a + b) // 2], hourly.max() * 0.95,
                 {"train": "train 60%", "val": "validation 20%", "test": "test 20%"}[name],
                 ha="center", va="top", fontsize=12, color=INK)
    top.set_title("Whole synthetic dataset (16 nodes summed, hourly mean)", loc="left", color=INK)
    top.set_ylabel("1000 req/min")
    top.set_xlim(minutes[0], minutes[-1])

    a, b = split["test"]
    keep = (hourly_minutes >= minutes[a]) & (hourly_minutes <= minutes[b - 1])
    for ax in (mid, low):
        ax.set_xlim(minutes[a], minutes[b - 1])
    mid.plot(hourly_minutes[keep], hourly[keep], color=INK, linewidth=0.9)
    mid.set_title("Test part only", loc="left", color=INK)
    mid.set_ylabel("1000 req/min")

    ordered = sorted(spans, key=lambda s: s[1])
    for y, (window, first, last) in enumerate(ordered):
        low.plot([minutes[first], minutes[last]], [y, y], color=COLORS["BiGRU"], linewidth=5,
                 solid_capstyle="butt")
    low.set_yticks(range(len(ordered)), [str(s[0]) for s in ordered], fontsize=8)
    low.set_ylabel("window (sorted by start)")
    low.invert_yaxis()
    low.grid(axis="y", visible=False)
    low.set_title(f"The {len(spans)} random one-day windows", loc="left", color=INK)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def coverage(spans, test_first, test_last):
    """How many test minutes are in at least one window, and the most windows on one minute."""
    hits = np.zeros(test_last - test_first + 1, dtype=int)
    for _, first, last in spans:
        hits[first - test_first: last - test_first + 1] += 1
    return int((hits > 0).sum()), len(hits), int(hits.max())


# ----------------------------------------------------------------------
# 5. Main
# ----------------------------------------------------------------------
def main():
    table8 = read_runs(os.path.join(TABLE8_DIR, "metrics.csv"), None)[0]
    seeds = read_runs(SEEDS_CSV, "seed")
    windows = read_runs(os.path.join(WINDOWS_DIR, "per_window.csv"), "window")
    for runs, what in ((seeds, "seed"), (windows, "window"), ({0: table8}, "Table 8")):
        check_complete(runs, what)

    # Check: seed 0 in summary.csv (4 decimals) is the Table 8 run.
    worst = max(abs(seeds[0][k] - table8[k]) for k in table8)
    print(f"seed 0 vs Table 8: largest difference {worst:.1e} (summary.csv keeps 4 decimals)")
    if worst > 5.1e-5:
        sys.exit("seed 0 in seeds/summary.csv is not the Table 8 run, stopping")

    out_dir = OUT_DIR
    fig_dir = os.path.join(out_dir, "figures")
    os.makedirs(fig_dir, exist_ok=True)
    write_csvs(out_dir, table8, seeds, windows)
    write_tables(os.path.join(out_dir, "tables.md"), table8, seeds, windows)

    style()
    for metric, title in METRICS:
        plot_spread(os.path.join(fig_dir, f"windows_{metric}.png"), windows, table8, metric, title,
                    f"{len(windows)} windows", boxes=True)
        plot_spread(os.path.join(fig_dir, f"seeds_{metric}.png"), seeds, table8, metric, title,
                    f"seeds {', '.join(map(str, seeds))}", boxes=False)
    plot_ranking(os.path.join(fig_dir, "ranking.png"), seeds, windows)

    with open(os.path.join(TABLE8_DIR, "report.json")) as f:
        report = json.load(f)
    with open(os.path.join(WINDOWS_DIR, "windows.csv")) as f:
        windows_rows = list(csv.DictReader(f))
    minutes, total = load_timeline(report)
    spans = window_spans(report, windows_rows, minutes)
    plot_timeline(os.path.join(fig_dir, "timeline.png"), report, minutes, total, spans)

    w = report["chosen_window"]
    test_first = report["split_minutes"]["test"][0] + w
    test_last = test_first + report["windows_per_node"]["test"] - 1
    covered, n, most = coverage(spans, test_first, test_last)
    print(f"windows cover {covered} of {n} test forecast minutes ({100 * covered / n:.1f}%), "
          f"at most {most} windows on one minute")
    print(f"test forecasts from {minutes[test_first]} to {minutes[test_last]}")
    print(f"Wrote {out_dir}: spread.csv, ranking.csv, tables.md, figures/ (8 PNG)")


if __name__ == "__main__":
    main()
