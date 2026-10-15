"""
Simulate the autoscalers on every node's test period and compare them
(Dogani & Khunjush 2024, experiment 5 / Table 11, Section 7.5, p. 17).

Usage:
    .venv/bin/python scripts/simulate_autoscaler.py                 (main "Dogani-like" run)
    .venv/bin/python scripts/simulate_autoscaler.py --pods-min 1 --khpa-pods-min 1 \
        --out-dir results/autoscaler_fair/pods_min_1 --pods-dir data/autoscaler_fair/pods_min_1   (fair run)

Defaults: mean pods 15, threshold 0.7, KHPA Pods_min 1, planner Pods_min 5.

1. PREDICT: the 4 trained models (data/predictors/, patience-10 run) predict
   minutes t .. t+4 for every minute t of each node's test period. A 5th
   predictor, Oracle, uses the real future traffic (best case).
2. SCALE: per node, real traffic and predictions are multiplied by one
   factor, so that the node's mean traffic is --mean-pods x 500 requests per
   minute (--mean-pods pods at 100% use). --threshold 0.7 then asks for
   ceil(load / 350) pods, as Dogani does for the optimal pods (p. 17).
3. SIMULATE: no autoscaling (fixed pods), KHPA (reactive), and the proactive
   planner with each predictor (autoscaler/scalers.py).
4. MEASURE: θU, θO, TU, TO, elastic speedup and scaling counts per node
   (autoscaler/metrics.py), then the mean over the nodes.

Outputs in --out-dir (default results/autoscaler/): table11.md,
metrics.csv, metrics_per_node.csv, report.json, pods_node_XX.png.
Pods per minute of every node go to --pods-dir (default data/autoscaler/, not in git).
"""
import argparse
import csv
import json
import math
import os
import sys
import time
from dataclasses import replace

import numpy as np
import torch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from autoscaler.metrics import METRICS, elastic_speedup, elasticity  # noqa: E402
from autoscaler.scalers import Settings, khpa, no_autoscaling, planner, requested_pods  # noqa: E402
from predictors.data import HORIZON, NodeData, french_holidays, load_node  # noqa: E402
from predictors.models import ARCHITECTURES  # noqa: E402
from predictors.training import predict  # noqa: E402

PREDICTORS = ["FedAvg-BiGRU", "FedAvg-LSTM", "CentralBiGRU", "CentralLSTM", "Oracle"]
SCALERS = ["No autoscaling", "KHPA"] + PREDICTORS

# Dogani & Khunjush (2024), Table 11 (p. 17): θU, θO, TU, TO, εn, #Scale_Up, #Scale_Down.
# Only the columns we simulate. His GRU columns are left out.
DOGANI_TABLE11 = {
    "No autoscaling": [2.01, 152.07, 10.76, 235.34, 1, None, None],
    "KHPA": [6.23, 3.05, 32.05, 18.23, 1.3, 1841, 1892],
    "CentralBiGRU": [0.23, 12.50, 1.42, 72.20, 1.63, 976, 1009],
    "FedAvg-BiGRU": [0.26, 13.04, 1.65, 75.12, 1.59, 1008, 1049],
    "CentralLSTM": [0.53, 16.12, 3.37, 87.43, 1.42, 1144, 1171],
    "FedAvg-LSTM": [0.61, 16.46, 3.81, 94.53, 1.39, 1156, 1194],
}
ROWS = ["theta_u", "theta_o", "t_u", "t_o", "speedup", "scale_ups", "scale_downs"]
ROW_NAMES = {"theta_u": "θU (%)", "theta_o": "θO (%)", "t_u": "TU (%)", "t_o": "TO (%)",
             "speedup": "εn", "scale_ups": "#Scale_Up", "scale_downs": "#Scale_Down"}


def log(text):
    print(text, flush=True)


# ----------------------------------------------------------------------
# Predictions
# ----------------------------------------------------------------------
def load_model(name, settings, weights_dir, window, device):
    """A trained predictor from data/predictors/<name>_W<window>.pt."""
    architecture = ARCHITECTURES[name.replace("FedAvg-", "").replace("Central", "")]
    model = architecture(settings["units"], settings["dropout"]).to(device)
    path = os.path.join(weights_dir, f"{name}_W{window}.pt")
    model.load_state_dict(torch.load(path, map_location=device, weights_only=True))
    return model


def node_inputs(node, requests, models):
    """
    The simulated minutes of one node and what the scalers see there.
    Minute t of the simulation is the first predicted minute of test window t.
    Returns (minute indexes, {predictor: forecasts (minutes x HORIZON)}).
    """
    minutes = node.starts["test"].cpu().numpy() + node.window
    ahead = minutes[:, None] + np.arange(HORIZON)
    forecasts = {}
    for name, model in models.items():
        predicted, real = predict(model, node)
        assert np.array_equal(real, requests[ahead]), "predictions and trace are not aligned"
        forecasts[name] = predicted
    forecasts["Oracle"] = requests[ahead]            # the real future traffic
    return minutes, forecasts


# ----------------------------------------------------------------------
# Simulation of one node
# ----------------------------------------------------------------------
def simulate_node(requests, minutes, forecasts, s, mean_pods, khpa_pods_min=None, predictors=PREDICTORS):
    """
    The scalers on one node. Traffic and forecasts are multiplied by `factor`
    so that the mean traffic is mean_pods x workload_pod (500) requests per
    minute. The factor does not depend on the threshold: with threshold 0.7
    the same traffic needs 1/0.7 times more pods.
    khpa_pods_min: KHPA's own Pods_min (default: the planner's).
    Returns (factor, requested pods, {scaler: (pods, ups, downs)}).
    """
    factor = mean_pods * s.workload_pod / requests[minutes].mean()
    real = requests * factor
    requested = requested_pods(real[minutes], s.capacity)
    khpa_s = s if khpa_pods_min is None else replace(s, pods_min=khpa_pods_min)
    runs = {"No autoscaling": no_autoscaling(len(minutes), s),
            "KHPA": khpa(real[minutes - 1], khpa_s, start_pods=s.fixed_pods)}
    for name in predictors:
        runs[name] = planner(forecasts[name] * factor, s, start_pods=s.fixed_pods)
    return factor, requested, runs


def node_metrics(requested, runs):
    """One row per scaler: θU, θO, TU, TO, εn against no autoscaling, scaling counts."""
    fixed = elasticity(requested, runs["No autoscaling"][0])
    rows = {}
    for name, (pods, ups, downs) in runs.items():
        row = elasticity(requested, pods)
        row["speedup"], zero = elastic_speedup(row, fixed)
        row["speedup_zero"] = " ".join(zero)          # which of the scaler's metrics are 0
        row["scale_ups"], row["scale_downs"] = ups, downs
        row["mean_pods"] = float(pods.mean())
        rows[name] = row
    return rows


def write_pods(path, minute_stamps, real, requested, runs):
    """Pods per minute of one node: traffic (scaled), requested pods, every scaler's pods."""
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["minute_paris", "requests_scaled", "requested_pods"] + list(runs))
        stamps = np.datetime_as_string(minute_stamps, unit="m")
        columns = [runs[name][0] for name in runs]
        for i in range(len(requested)):
            writer.writerow([stamps[i], f"{real[i]:.1f}", requested[i]] + [c[i] for c in columns])


# ----------------------------------------------------------------------
# Summary over the nodes
# ----------------------------------------------------------------------
def summarize(per_node):
    """Mean over the nodes of each metric. εn: mean of the finite node values, and how many are not finite."""
    summary = {}
    for name in SCALERS:
        rows = [node[name] for node in per_node]
        mean = {m: float(np.mean([r[m] for r in rows])) for m in METRICS + ["scale_ups", "scale_downs", "mean_pods"]}
        speedups = np.array([r["speedup"] for r in rows])
        finite = np.isfinite(speedups)
        mean["speedup"] = float(speedups[finite].mean()) if finite.any() else None
        mean["speedup_not_finite"] = int((~finite).sum())
        mean["speedup_zero"] = [m for m in METRICS if any(m in r["speedup_zero"].split() for r in rows)]
        summary[name] = mean
    # Eq. 18 applied to the mean rows, the way a reader of Table 11 would check it
    for name in SCALERS:
        summary[name]["speedup_of_means"] = elastic_speedup(summary[name], summary["No autoscaling"])[0]
    return summary


def dogani_speedup_of_rows():
    """Eq. 18 applied to Dogani's own Table 11 rows."""
    fixed = dict(zip(METRICS, DOGANI_TABLE11["No autoscaling"][:4]))
    return {name: elastic_speedup(dict(zip(METRICS, row[:4])), fixed)[0] for name, row in DOGANI_TABLE11.items()}


def json_safe(value):
    """inf and nan as the strings "inf" and "nan": plain JSON has no such numbers."""
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    return value


def number(value, digits=2):
    if value is None:
        return "–"
    if isinstance(value, float) and math.isinf(value):
        return "∞"
    if isinstance(value, float) and math.isnan(value):
        return "undefined"
    return f"{value:,.{digits}f}"


def table11_markdown(summary, factors, s, args, n_minutes):
    """Our Table 11 with Dogani's numbers next to ours, plus the εn check."""
    n = len(factors)
    names = {"theta_u": "θU", "theta_o": "θO", "t_u": "TU", "t_o": "TO"}
    lines = [
        "# Autoscaler simulation (Dogani & Khunjush 2024, Table 11)",
        "",
        f"Mean over {n} nodes, {n_minutes:,} test minutes each (one step = 1 minute).",
        f"Traffic per node scaled so that the mean demand is {args.mean_pods:g} pods at 100% use "
        f"(factors {min(factors):.4f} to {max(factors):.4f}).",
        f"Settings (Table 3): workload_pod {s.workload_pod:g}, threshold {s.threshold:g}, "
        f"Pods_min {s.pods_min} (KHPA {args.khpa_pods_min}), "
        f"CDT scale-up {s.cdt_up} min, scale-down {s.cdt_down} min, SDR {s.sdr:g}. "
        f"No autoscaling: {s.fixed_pods} pods.",
        "",
        "Each cell: ours / Dogani. Counts are per node and test period for us. "
        "Dogani does not say what his counts cover.",
        "",
        "| Scaler | " + " | ".join(ROW_NAMES[r] for r in ROWS) + " |",
        "|---" * (len(ROWS) + 1) + "|",
    ]
    notes = []
    for name in SCALERS:
        ours, theirs = summary[name], DOGANI_TABLE11.get(name, [None] * len(ROWS))
        cells = []
        for row, dogani in zip(ROWS, theirs):
            if row == "speedup":
                value = number(ours["speedup"])
                if ours["speedup_not_finite"]:
                    zero = " and ".join(names[z] for z in ours["speedup_zero"])
                    verb = "are" if len(ours["speedup_zero"]) > 1 else "is"
                    value = "∞" if ours["speedup_not_finite"] == n else f"{value} (∞ on {ours['speedup_not_finite']})"
                    notes.append(f"- **{name}:** εn is infinite on {ours['speedup_not_finite']} of {n} nodes, "
                                 f"because its {zero} {verb} 0 there and Eq. 18 divides by them.")
            elif row in ("scale_ups", "scale_downs"):
                value = "0" if name == "No autoscaling" else number(ours[row], 1)
            else:
                value = number(ours[row])
            dogani = number(dogani, 0 if row in ("scale_ups", "scale_downs") else 2)
            cells.append(f"{value} / {dogani}")
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    if notes:
        lines += ["", *notes]

    check = dogani_speedup_of_rows()
    shown = [m for m in SCALERS if m != "No autoscaling"]
    lines += [
        "",
        "## Elastic speedup check",
        "",
        "Eq. 18 applied to the mean rows above. Dogani's printed εn does not follow from his own rows.",
        "",
        "| | " + " | ".join(shown) + " |",
        "|---" * (len(shown) + 1) + "|",
        "| Ours, mean of the node values | " + " | ".join(
            "∞" if summary[m]["speedup"] is None else number(summary[m]["speedup"]) for m in shown) + " |",
        "| Ours, Eq. 18 on the mean rows | " + " | ".join(number(summary[m]["speedup_of_means"]) for m in shown) + " |",
        "| Dogani, as printed | " + " | ".join(number(DOGANI_TABLE11[m][4]) if m in DOGANI_TABLE11 else "–"
                                              for m in shown) + " |",
        "| Dogani, Eq. 18 on his rows | " + " | ".join(number(check[m]) if m in check else "–" for m in shown) + " |",
        "",
        "## Mean pods",
        "",
        "| Scaler | Mean pods |",
        "|---|---|",
    ]
    lines += [f"| {name} | {summary[name]['mean_pods']:.2f} |" for name in SCALERS]
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------
# Plot like Fig. 9
# ----------------------------------------------------------------------
PLOT_STYLE = {"Requested pods": ("#1f2937", "-.", 1.3), "KHPA": ("#d95926", "-", 1.6),
              "FedAvg-BiGRU": ("#3987e5", "-", 1.6)}


def plot_pods(path, node_name, minute_stamps, requested, runs, hours):
    """Requested pods, KHPA and FedAvg-BiGRU for three periods of `hours` hours (start, middle, end of the test)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    length = hours * 60
    starts = [int(f * (len(requested) - length)) for f in (0.2, 0.5, 0.8)]
    fig, axes = plt.subplots(3, 1, figsize=(12, 10))
    for ax, first, letter in zip(axes, starts, "abc"):
        part = slice(first, first + length)
        t = minute_stamps[part].astype("datetime64[s]").astype(object)
        series = {"Requested pods": requested, "KHPA": runs["KHPA"][0], "FedAvg-BiGRU": runs["FedAvg-BiGRU"][0]}
        for label, values in series.items():
            color, line, width = PLOT_STYLE[label]
            ax.step(t, values[part], where="post", color=color, ls=line, lw=width, label=label)
        ax.set_title(f"({letter}) {np.datetime_as_string(minute_stamps[first], unit='m').replace('T', ' ')}"
                     f", {hours} hours", loc="left", fontsize=10)
        ax.set_ylabel("pods")
        locator = mdates.AutoDateLocator()
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
        ax.grid(color="#e5e7eb", lw=0.8)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    axes[0].legend(frameon=False, ncol=3, loc="upper left")
    fig.suptitle(f"{node_name}: pods per minute, KHPA against the planner with FedAvg-BiGRU (Paris time)",
                 x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Simulate the autoscalers of Dogani & Khunjush (2024), Table 11.")
    parser.add_argument("--traces", default=os.path.join(ROOT, "data", "synthetic"), help="node_XX.csv folder")
    parser.add_argument("--nodes", type=int, default=16)
    parser.add_argument("--weights-dir", default=os.path.join(ROOT, "data", "predictors"))
    parser.add_argument("--predictors-report", default=os.path.join(ROOT, "results", "predictors", "report.json"),
                        help="report.json of the training run (window, units, dropout)")
    parser.add_argument("--mean-pods", type=float, default=15, help="mean traffic per node after scaling, in pods at 100%% use (default 15)")
    parser.add_argument("--workload-pod", type=float, default=500, help="requests per minute per pod (default 500)")
    parser.add_argument("--threshold", type=float, default=0.7,
                        help="target use of a pod: pods = ceil(load / (workload_pod x threshold)) (default 0.7)")
    parser.add_argument("--pods-min", type=int, default=5)
    parser.add_argument("--khpa-pods-min", type=int, default=1,
                        help="KHPA's Pods_min (default 1, closest to Dogani's KHPA; the planner uses --pods-min)")
    parser.add_argument("--cdt-up", type=int, default=3, help="cooldown after a scale-up, minutes (default 3)")
    parser.add_argument("--cdt-down", type=int, default=5, help="cooldown after a scale-down, minutes (default 5)")
    parser.add_argument("--sdr", type=float, default=0.3, help="scale-down rate (default 0.3)")
    parser.add_argument("--fixed-pods", type=int, default=15, help="pods without autoscaling (default 15)")
    parser.add_argument("--plot-node", type=int, default=0)
    parser.add_argument("--plot-hours", type=int, default=5, help="length of each plotted period (default 5)")
    parser.add_argument("--out-dir", default=os.path.join(ROOT, "results", "autoscaler"))
    parser.add_argument("--pods-dir", default=os.path.join(ROOT, "data", "autoscaler"))
    args = parser.parse_args()
    started = time.time()
    os.makedirs(args.out_dir, exist_ok=True)
    os.makedirs(args.pods_dir, exist_ok=True)

    s = Settings(args.workload_pod, args.pods_min, args.cdt_up, args.cdt_down, args.sdr, args.fixed_pods,
                 args.threshold)
    trained = json.load(open(args.predictors_report))
    window = trained["chosen_window"]
    device = "cuda" if torch.cuda.is_available() else "cpu"
    models = {name: load_model(name, trained["settings"], args.weights_dir, window, device)
              for name in PREDICTORS if name != "Oracle"}
    paths = [os.path.join(args.traces, f"node_{i:02d}.csv") for i in range(args.nodes)]
    holiday_days = french_holidays(load_node(paths[0])[0])
    log(f"{len(models)} models (W = {window}) on {device}, {args.nodes} nodes, mean demand {args.mean_pods:g} pods")

    per_node, factors, rows = [], [], []
    for i, path in enumerate(paths):
        node = NodeData(path, window, holiday_days, device)
        requests = load_node(path)[1]
        minutes, forecasts = node_inputs(node, requests, models)
        factor, requested, runs = simulate_node(requests, minutes, forecasts, s, args.mean_pods, args.khpa_pods_min)
        result = node_metrics(requested, runs)
        per_node.append(result)
        factors.append(factor)
        for name in SCALERS:
            rows.append({"node": node.name, "scaler": name, "factor": round(factor, 6),
                         **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in result[name].items()}})
        write_pods(os.path.join(args.pods_dir, f"{node.name}.csv"), node.minutes[minutes],
                   requests[minutes] * factor, requested, runs)
        if i == args.plot_node:
            plot_pods(os.path.join(args.out_dir, f"pods_{node.name}.png"), node.name, node.minutes[minutes],
                      requested, runs, args.plot_hours)
        log(f"  {node.name}: factor {factor:.4f}, KHPA θU {result['KHPA']['theta_u']:.2f}, "
            f"FedAvg-BiGRU θU {result['FedAvg-BiGRU']['theta_u']:.2f}")

    summary = summarize(per_node)
    n_minutes = len(minutes)
    with open(os.path.join(args.out_dir, "table11.md"), "w") as f:
        f.write(table11_markdown(summary, factors, s, args, n_minutes))
    with open(os.path.join(args.out_dir, "metrics_per_node.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with open(os.path.join(args.out_dir, "metrics.csv"), "w", newline="") as f:
        fields = METRICS + ["speedup", "speedup_not_finite", "speedup_of_means", "scale_ups", "scale_downs", "mean_pods"]
        writer = csv.writer(f)
        writer.writerow(["scaler"] + fields)
        for name in SCALERS:
            writer.writerow([name] + [summary[name][k] for k in fields])
    report = {
        "settings": vars(args), "table3": vars(s), "window": window, "device": device,
        "predictors": trained["settings"],
        "simulated_minutes_per_node": n_minutes,
        "first_minute": str(node.minutes[minutes[0]]), "last_minute": str(node.minutes[minutes[-1]]),
        "start_pods": s.fixed_pods,
        "factors": {f"node_{i:02d}": f for i, f in enumerate(factors)},
        "mean": summary,
        "dogani_table11": DOGANI_TABLE11,
        "dogani_speedup_of_rows": dogani_speedup_of_rows(),
        "seconds": round(time.time() - started, 1),
    }
    with open(os.path.join(args.out_dir, "report.json"), "w") as f:
        json.dump(json_safe(report), f, indent=2, default=str)
    log(f"Done in {time.time() - started:.0f} s. Results in {args.out_dir}")


if __name__ == "__main__":
    main()
