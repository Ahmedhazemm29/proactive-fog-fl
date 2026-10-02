"""
Compare the reactive and the proactive controller runs.

For each run it:
    1. finds the run's time window (first and last timestamp in its CSV log)
    2. pulls per-worker CPU usage and throttled time from Prometheus
       (5 s steps, the same queries the controllers use)
       demand = usage + throttled time
    3. pulls the workers' training speed (steps/s) from `docker logs`
    4. computes averages per worker and in total
    5. writes results/comparison.md and the figures in figures/ (PDF)

Usage:  python analysis/compare_runs.py
Needs Prometheus on localhost:9090 and the worker containers still present.
"""
import csv
import os
import re
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
RUNS = {  # run name -> controller log with its decisions
    "reactive": os.path.join(ROOT, "data", "reactive_log.csv"),
    "proactive": os.path.join(ROOT, "data", "proactive_log.csv"),
}
STEP_SECONDS = 5          # resolution of the Prometheus range queries
EQUAL_LENGTH_SECONDS = 600  # second table: first 10 min of each run (5 load cycles)

RESULTS_FILE = os.path.join(ROOT, "results", "comparison.md")
FIGURES_DIR = os.path.join(ROOT, "figures")

# Worker colors: categorical slots 1 and 2 of the validated default palette.
COLORS = {"fl-worker-1": "#2a78d6", "fl-worker-2": "#eb6834"}
LABELS = {"fl-worker-1": "Worker 1", "fl-worker-2": "Worker 2"}
INK = "#2b2b29"     # text and the demand line
MUTED = "#8a8a84"   # limit line, grid


# ----------------------------------------------------------------------
# 1. Time windows and limits from the controller logs
# ----------------------------------------------------------------------
def read_log(path):
    """
    Return (start, end, limits) for one run. Times are Unix seconds.
    limits = {worker: [(time, limit after that cycle's decision), ...]}
    The CSV timestamps are local time, which .timestamp() converts correctly.
    """
    limits = {w: [] for w in WORKERS}
    with open(path) as f:
        for row in csv.DictReader(f):
            t = datetime.fromisoformat(row["timestamp"]).timestamp()
            limits[row["worker"]].append((t, float(row["new_limit"])))
    times = [t for series in limits.values() for t, _ in series]
    return min(times), max(times), limits


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
# 5a. Summary table
# ----------------------------------------------------------------------
def table(summaries):
    lines = ["| Run | Worker | Demand (CPU) | CPU used (CPU) | Unmet demand (CPU) | Training speed (steps/s) |",
             "|---|---|---:|---:|---:|---:|"]
    for run, rows in summaries.items():
        for key in WORKERS + ["total"]:
            r = rows[key]
            label = "**Total**" if key == "total" else LABELS[key]
            lines.append(f"| {run} | {label} | {r['demand']:.3f} | {r['used']:.3f} | "
                         f"{r['unmet']:.3f} | {r['steps']:.1f} |")
    return "\n".join(lines)


def write_results(windows, full, equal):
    def clock(t):
        return datetime.fromtimestamp(t).strftime("%H:%M:%S")

    text = ["# Reactive vs proactive run", ""]
    text += ["| Run | Start | End | Length |", "|---|---|---|---:|"]
    for run, (start, end) in windows.items():
        text.append(f"| {run} | {clock(start)} | {clock(end)} | {end - start:.0f} s |")
    text += ["",
             "Unmet demand = average throttled CPU (time per second a worker waited because",
             "its limit was used up). Demand = CPU used + unmet demand. Totals add up both",
             f"workers. CPU values are Prometheus 30 s rates sampled every {STEP_SECONDS} s; training",
             "speed is the average of the workers' 10 s log reports.",
             "", "## Whole runs", "", table(full),
             "", f"## First {EQUAL_LENGTH_SECONDS // 60} minutes of each run",
             "",
             f"Same length for both runs ({EQUAL_LENGTH_SECONDS // 120} full 120 s load cycles), "
             "as a fairness check.",
             "", table(equal), ""]
    os.makedirs(os.path.dirname(RESULTS_FILE), exist_ok=True)
    with open(RESULTS_FILE, "w") as f:
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


def plot_limits(run, start, end, limits):
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
    fig.savefig(os.path.join(FIGURES_DIR, f"limits_{run}.pdf"))
    plt.close(fig)


def plot_demand_usage(run, start, end, cpu, limits):
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
    fig.savefig(os.path.join(FIGURES_DIR, f"demand_usage_{run}.pdf"))
    plt.close(fig)


# ----------------------------------------------------------------------
# Main: windows -> data -> numbers -> table and figures
# ----------------------------------------------------------------------
def main():
    style()
    os.makedirs(FIGURES_DIR, exist_ok=True)
    windows, full, equal = {}, {}, {}

    for run, log_path in RUNS.items():
        start, end, limits = read_log(log_path)
        windows[run] = (start, end)
        cpu = cpu_series(start, end)
        steps = {w: steps_per_second(w, start, end) for w in WORKERS}

        full[run] = summarize(cpu, steps, start, end)
        equal[run] = summarize(cpu, steps, start, start + EQUAL_LENGTH_SECONDS)

        plot_limits(run, start, end, limits)
        plot_demand_usage(run, start, end, cpu, limits)
        print(f"{run}: {end - start:.0f} s, {len(cpu[WORKERS[0]])} Prometheus points, "
              f"{len(steps[WORKERS[0]])} log lines per worker")

    write_results(windows, full, equal)
    print(f"Wrote {os.path.relpath(RESULTS_FILE, ROOT)} and 4 PDFs in "
          f"{os.path.relpath(FIGURES_DIR, ROOT)}/")


if __name__ == "__main__":
    main()
