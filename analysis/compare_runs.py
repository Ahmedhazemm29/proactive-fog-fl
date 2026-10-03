"""
Compare the reactive and the proactive controller over repeated runs.

Reads the list of runs that scripts/run_experiments.py wrote to
data/runs/runs.csv. For each run it:
    1. takes the run's time window (start and end in runs.csv) and the
       controller's CPU limits (the run's CSV log)
    2. pulls per-worker CPU usage and throttled time from Prometheus
       (5 s steps, the same queries the controllers use)
       demand = usage + throttled time
    3. pulls the workers' training speed (steps/s) from `docker logs`
    4. computes averages per worker and in total
Then it reports every metric as mean and standard deviation across the
repeats of each controller, in results/comparison.md, and draws the
figures of every run in figures/ (PDF).

Usage:  python analysis/compare_runs.py
        python analysis/compare_runs.py --runs-dir data/runs_test --results /tmp/c.md --figures-dir /tmp/fig
Needs Prometheus on localhost:9090 and the worker containers still present.
"""
import argparse
import csv
import os
import re
import statistics
import subprocess
import sys
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")  # draw straight to files, no window needed
import matplotlib.pyplot as plt
import requests

# Reuse the controllers' queries, so the analysis measures exactly what they saw.
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "controller"))
from reactive import PROMETHEUS_URL, QUERY as USAGE_QUERY, WORKERS  # noqa: E402
from proactive import THROTTLED_SECONDS_QUERY  # noqa: E402


# ----------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------
RUNS_DIR = os.path.join(ROOT, "data", "runs")       # written by run_experiments.py
RESULTS_FILE = os.path.join(ROOT, "results", "comparison.md")
FIGURES_DIR = os.path.join(ROOT, "figures")
STEP_SECONDS = 5          # resolution of the Prometheus range queries
CONTROLLERS = ["reactive", "proactive"]
METRICS = [  # key, column title
    ("demand", "Demand (CPU)"),
    ("used", "CPU used (CPU)"),
    ("unmet", "Unmet demand (CPU)"),
    ("steps", "Training speed (steps/s)"),
]

# Worker colors: categorical slots 1 and 2 of the validated default palette.
COLORS = {"fl-worker-1": "#2a78d6", "fl-worker-2": "#eb6834"}
LABELS = {"fl-worker-1": "Worker 1", "fl-worker-2": "Worker 2"}
INK = "#2b2b29"     # text and the demand line
MUTED = "#8a8a84"   # limit line, grid


# ----------------------------------------------------------------------
# 1. The list of runs, their time windows and the controllers' limits
# ----------------------------------------------------------------------
def read_runs(runs_dir):
    """
    Return the finished runs from runs.csv as a list of dicts with
    controller, repeat, start, end (Unix seconds) and csv (full path).
    Runs that did not end with status "ok" are skipped.
    """
    runs = []
    with open(os.path.join(runs_dir, "runs.csv")) as f:
        for row in csv.DictReader(f):
            if row["status"] != "ok":
                print(f"skipping run {row['run']} ({row['controller']}): {row['status']}")
                continue
            runs.append({
                "controller": row["controller"],
                "repeat": int(row["repeat"]),
                # the times carry their UTC offset, e.g. 2026-10-02T21:30:00+03:00
                "start": datetime.fromisoformat(row["start"]).timestamp(),
                "end": datetime.fromisoformat(row["end"]).timestamp(),
                "csv": os.path.join(ROOT, row["csv"]),
            })
    return runs


def read_limits(path):
    """
    Return the CPU limits a controller set during one run:
    {worker: [(time, limit after that cycle's decision), ...]}
    The CSV timestamps are local time, which .timestamp() converts correctly.
    """
    limits = {w: [] for w in WORKERS}
    with open(path) as f:
        for row in csv.DictReader(f):
            t = datetime.fromisoformat(row["timestamp"]).timestamp()
            limits[row["worker"]].append((t, float(row["new_limit"])))
    return limits


# ----------------------------------------------------------------------
# 2. Usage and throttled time from Prometheus
# ----------------------------------------------------------------------
def query_range(query, start, end):
    """Return {worker: {time: value}} for a PromQL query over [start, end]."""
    response = requests.get(
        f"{PROMETHEUS_URL}/api/v1/query_range",
        params={"query": query, "start": start, "end": end, "step": STEP_SECONDS},
        timeout=30,
    )
    response.raise_for_status()
    result = {}
    for series in response.json()["data"]["result"]:
        name = series["metric"]["name"]
        result[name] = {float(t): float(v) for t, v in series["values"]}
    return result


def cpu_series(start, end):
    """
    Return {worker: [(time, usage, throttled, demand), ...]} in CPUs.
    Only time steps where both usage and throttled time exist are kept.
    """
    usage = query_range(USAGE_QUERY, start, end)
    throttled = query_range(THROTTLED_SECONDS_QUERY, start, end)
    series = {}
    for w in WORKERS:
        common = sorted(set(usage[w]) & set(throttled[w]))
        series[w] = [(t, usage[w][t], throttled[w][t], usage[w][t] + throttled[w][t])
                     for t in common]
    return series


# ----------------------------------------------------------------------
# 3. Training speed from the worker logs
# ----------------------------------------------------------------------
STEPS_PATTERN = re.compile(r"steps/s=\s*([\d.]+)")


def steps_per_second(worker, start, end):
    """
    Return [(time, steps/s), ...] from the worker's log lines inside the window.
    Each line reports the average speed over the previous 10 s.

    Only --since is passed to docker: these logs contain two lines with a wrong
    (future) clock from an earlier start, and `docker logs --until` stops at
    the first line it sees past the limit, so it would return nothing.
    The end of the window is therefore checked here instead.
    """
    since = datetime.fromtimestamp(start, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    output = subprocess.run(["docker", "logs", "--timestamps", "--since", since, worker],
                            capture_output=True, text=True, check=True)
    points = []
    for line in (output.stdout + output.stderr).splitlines():
        match = STEPS_PATTERN.search(line)
        if not match:
            continue
        # docker writes e.g. 2026-10-02T18:16:07.570588083Z (UTC, nanoseconds);
        # Python only reads 6 decimals, so cut the rest off.
        stamp = line.split()[0]
        t = datetime.fromisoformat(stamp[:26] + "+00:00").timestamp()
        if start <= t <= end:
            points.append((t, float(match.group(1))))
    return sorted(points)


# ----------------------------------------------------------------------
# 4. Averages
# ----------------------------------------------------------------------
def mean(values):
    return sum(values) / len(values) if values else float("nan")


def summarize(cpu, steps, start, end):
    """Averages per worker and in total, only counting data inside [start, end]."""
    rows = {}
    for w in WORKERS:
        points = [p for p in cpu[w] if start <= p[0] <= end]
        speed = [s for t, s in steps[w] if start <= t <= end]
        rows[w] = {
            "demand": mean([p[3] for p in points]),
            "used": mean([p[1] for p in points]),
            "unmet": mean([p[2] for p in points]),
            "steps": mean(speed),
        }
    # Totals: the two workers' averages added up.
    rows["total"] = {key: sum(rows[w][key] for w in WORKERS) for key in rows[WORKERS[0]]}
    return rows


# ----------------------------------------------------------------------
# 5a. Mean and standard deviation across repeats, and the results file
# ----------------------------------------------------------------------
def aggregate(summaries):
    """
    summaries = list of per-run summaries of ONE controller.
    Returns {worker or "total": {metric: (mean, standard deviation)}}.
    The standard deviation shows how much the repeats differ from each other.
    """
    result = {}
    for key in WORKERS + ["total"]:
        result[key] = {}
        for metric, _ in METRICS:
            values = [s[key][metric] for s in summaries]
            sd = statistics.stdev(values) if len(values) > 1 else float("nan")
            result[key][metric] = (statistics.mean(values), sd)
    return result


def mean_sd_table(stats):
    """stats = {controller: aggregate(...)}"""
    lines = ["| Controller | Worker | " + " | ".join(title for _, title in METRICS) + " |",
             "|---|---|" + "---:|" * len(METRICS)]
    for controller, rows in stats.items():
        for key in WORKERS + ["total"]:
            label = "**Total**" if key == "total" else LABELS[key]
            cells = []
            for metric, _ in METRICS:
                m, sd = rows[key][metric]
                digits = 1 if metric == "steps" else 3
                cells.append(f"{m:.{digits}f} ± {sd:.{digits}f}")
            lines.append(f"| {controller} | {label} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def difference_table(stats):
    """Totals of the proactive controller compared with the reactive one."""
    lines = ["| Metric (total) | Reactive | Proactive | Difference |", "|---|---:|---:|---:|"]
    for metric, title in METRICS:
        r, _ = stats["reactive"]["total"][metric]
        p, _ = stats["proactive"]["total"][metric]
        digits = 1 if metric == "steps" else 3
        lines.append(f"| {title} | {r:.{digits}f} | {p:.{digits}f} | "
                     f"{p - r:+.{digits}f} ({(p - r) / r:+.0%}) |")
    return "\n".join(lines)


def per_run_table(runs):
    """One line per run with its totals, so single odd runs are easy to spot."""
    lines = ["| Controller | Repeat | Start | Length | " + " | ".join(t for _, t in METRICS) + " |",
             "|---|---:|---|---:|" + "---:|" * len(METRICS)]
    for run in runs:
        total = run["summary"]["total"]
        cells = [f"{total[m]:.1f}" if m == "steps" else f"{total[m]:.3f}" for m, _ in METRICS]
        lines.append(f"| {run['controller']} | {run['repeat']} | "
                     f"{datetime.fromtimestamp(run['start']):%Y-%m-%d %H:%M} | "
                     f"{run['end'] - run['start']:.0f} s | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def write_results(path, runs, stats):
    counts = ", ".join(f"{c}: {sum(r['controller'] == c for r in runs)} runs" for c in stats)
    text = ["# Reactive vs proactive, repeated runs", "",
            f"Repeats: {counts}. Values are mean ± standard deviation across the repeats.",
            "",
            "Unmet demand = average throttled CPU (time per second a worker waited because",
            "its limit was used up). Demand = CPU used + unmet demand. Totals add up both",
            f"workers. CPU values are Prometheus 30 s rates sampled every {STEP_SECONDS} s; training",
            "speed is the average of the workers' 10 s log reports.",
            "", "## Mean ± standard deviation", "", mean_sd_table(stats), ""]
    if "reactive" in stats and "proactive" in stats:
        text += ["## Proactive compared with reactive", "", difference_table(stats), ""]
    text += ["## Every run (totals)", "", per_run_table(runs), ""]
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as f:
        f.write("\n".join(text))


# ----------------------------------------------------------------------
# 5b. Figures
# ----------------------------------------------------------------------
def style():
    """Thesis look: readable fonts, embedded TrueType fonts, quiet axes and grid."""
    plt.rcParams.update({
        "font.size": 10, "axes.labelsize": 10, "legend.fontsize": 9,
        "xtick.labelsize": 9, "ytick.labelsize": 9,
        "pdf.fonttype": 42,                      # fonts stay editable/searchable
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.edgecolor": MUTED, "axes.labelcolor": INK,
        "xtick.color": INK, "ytick.color": INK,
        "axes.grid": True, "grid.color": "#e4e4e0", "grid.linewidth": 0.6,
        "lines.linewidth": 1.6,
    })


def plot_limits(figures_dir, run, start, end, limits):
    """CPU limit of each worker over the run, as steps (a limit holds until the next decision)."""
    fig, ax = plt.subplots(figsize=(6.3, 2.6))
    for w in WORKERS:
        times = [t - start for t, _ in limits[w]]
        values = [v for _, v in limits[w]]
        ax.step(times, values, where="post", color=COLORS[w], label=LABELS[w])
    ax.set_xlim(0, end - start)
    ax.set_ylim(0, 1.0)
    ax.set_xlabel("Time since run start (s)")
    ax.set_ylabel("CPU limit (cores)")
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2, frameon=False)
    fig.tight_layout()
    fig.savefig(os.path.join(figures_dir, f"limits_{run}.pdf"))
    plt.close(fig)


def plot_demand_usage(figures_dir, run, start, end, cpu, limits):
    """
    One panel per worker: demand (line), CPU actually used (filled area) and
    the limit (dashed). The gap between the demand line and the filled area
    is the unmet demand.
    """
    fig, axes = plt.subplots(2, 1, figsize=(6.3, 4.4), sharex=True)
    for ax, w in zip(axes, WORKERS):
        times = [p[0] - start for p in cpu[w]]
        ax.fill_between(times, [p[1] for p in cpu[w]], color=COLORS[w], alpha=0.35,
                        linewidth=0, label="CPU used")
        ax.plot(times, [p[3] for p in cpu[w]], color=INK, label="Demand (used + throttled)")
        ax.step([t - start for t, _ in limits[w]], [v for _, v in limits[w]],
                where="post", color=COLORS[w], linestyle="--", linewidth=1.3, label="CPU limit")
        ax.set_ylim(0, 1.15)
        ax.set_ylabel(f"{LABELS[w]}\nCPU (cores)")
    axes[0].legend(loc="upper center", bbox_to_anchor=(0.5, 1.22), ncol=3, frameon=False)
    axes[-1].set_xlim(0, end - start)
    axes[-1].set_xlabel("Time since run start (s)")
    fig.tight_layout()
    fig.savefig(os.path.join(figures_dir, f"demand_usage_{run}.pdf"))
    plt.close(fig)


# ----------------------------------------------------------------------
# Main: runs -> data -> numbers per run -> mean ± sd, table and figures
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Compare repeated reactive and proactive runs.")
    parser.add_argument("--runs-dir", default=RUNS_DIR, help="folder with runs.csv")
    parser.add_argument("--results", default=RESULTS_FILE, help="markdown file to write")
    parser.add_argument("--figures-dir", default=FIGURES_DIR, help="folder for the PDFs")
    args = parser.parse_args()

    style()
    os.makedirs(args.figures_dir, exist_ok=True)
    runs = read_runs(args.runs_dir)

    for run in runs:
        name = f"{run['controller']}_{run['repeat']}"
        start, end = run["start"], run["end"]
        limits = read_limits(run["csv"])
        cpu = cpu_series(start, end)
        steps = {w: steps_per_second(w, start, end) for w in WORKERS}
        run["summary"] = summarize(cpu, steps, start, end)

        plot_limits(args.figures_dir, name, start, end, limits)
        plot_demand_usage(args.figures_dir, name, start, end, cpu, limits)
        print(f"{name}: {end - start:.0f} s, {len(cpu[WORKERS[0]])} Prometheus points, "
              f"{len(steps[WORKERS[0]])} log lines per worker")

    stats = {c: aggregate([r["summary"] for r in runs if r["controller"] == c])
             for c in CONTROLLERS if any(r["controller"] == c for r in runs)}
    write_results(args.results, runs, stats)
    print(f"Wrote {args.results} and {2 * len(runs)} PDFs in {args.figures_dir}")


if __name__ == "__main__":
    main()
