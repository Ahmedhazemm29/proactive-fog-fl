"""
Report of the live runs (step 4B): Table 11 from real CPU, next to the step 4A
simulation of the same window.

Usage (after the three runs of scripts/live_run.py):
    .venv/bin/python scripts/live_report.py
    .venv/bin/python scripts/live_report.py --tag demo     # the runs made with --tag demo
    .venv/bin/python scripts/live_report.py --dir results/autoscaler_live/calm   # another window

1. Live, requested workers from real CPU: ceil(CPU of the step / (0.5 x 0.7)),
   at least 1. This is what the task asks for. When workers are saturated the
   CPU cannot grow any more, so this hides part of the demand.
2. Live, requested workers from the replayed traffic: ceil(requests / workload_pod).
   The same for every run, as in step 4A.
3. Step 4A simulation on the same steps: the code of scalers.py with the same
   settings. KHPA there reads the traffic of the last step, not the CPU.
θU, θO, TU, TO: Eqs. 14 to 17. εn: Eq. 18 against the no-autoscaling row of
the same table. Failed requests and p95 response time come from the load generator.

Outputs in --dir (default results/autoscaler_live/): report.md, report.json,
and plot_<scaler>.png per run (workers above, p95 response time below).
"""
import argparse
import csv
import json
import os
import sys

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from autoscaler.metrics import METRICS, elastic_speedup, elasticity  # noqa: E402
from autoscaler.scalers import khpa, no_autoscaling, planner, requested_pods  # noqa: E402
import live_run  # noqa: E402
from simulate_autoscaler import DOGANI_TABLE11, json_safe, number  # noqa: E402

SCALERS = {"none": "No autoscaling", "khpa": "KHPA", "planner": "Planner (FedAvg-BiGRU)"}
DOGANI = {"none": "No autoscaling", "khpa": "KHPA", "planner": "FedAvg-BiGRU"}


def read_steps(path):
    with open(path) as f:
        rows = [r for r in csv.DictReader(f) if r["phase"] == "run"]
    return {k: np.array([float(r[k]) if r[k] != "" else np.nan for r in rows])
            for k in rows[0] if k not in ("minute", "phase", "action")} | {
        "minute": np.array([r["minute"] for r in rows], dtype="datetime64[m]"),
        "action": [r["action"] for r in rows]}


def table(requested, pods, counts):
    """Table 11 rows of each scaler. requested: {scaler: array} (or one array for all)."""
    rows = {}
    for name, p in pods.items():
        need = requested[name] if isinstance(requested, dict) else requested
        rows[name] = elasticity(need, p) | {"scale_ups": counts[name][0], "scale_downs": counts[name][1],
                                            "mean_workers": float(np.mean(p))}
    if "none" in rows:
        for name, row in rows.items():
            row["speedup"], row["speedup_zero"] = elastic_speedup(row, rows["none"])
    return rows


def simulate(window_dir, first_step, steps):
    """Step 4A's scalers on the same window steps, with the live settings and the 20-worker cap."""
    info = json.load(open(os.path.join(window_dir, "window.json")))
    all_steps, _, requests, forecasts = live_run.read_window(os.path.join(window_dir, "window.csv"))
    first = int(np.flatnonzero(all_steps == first_step)[0])
    part = slice(first, first + steps)
    runs = {}
    s = live_run.settings("none", info["workload_pod"], info["fixed_pods"])
    runs["none"] = no_autoscaling(steps, s)
    s = live_run.settings("khpa", info["workload_pod"], info["fixed_pods"])
    runs["khpa"] = khpa(requests[first - 1:first + steps - 1].astype(float), s, start_pods=s.fixed_pods)
    s = live_run.settings("planner", info["workload_pod"], info["fixed_pods"])
    runs["planner"] = planner(forecasts[part], s, start_pods=s.fixed_pods)
    return requested_pods(requests[part], s.capacity), runs


def markdown_table(rows, runs=None, failed=True):
    head = "| Scaler | θU | θO | TU | TO | εn | #Up | #Down | Mean workers |"
    rule = "|---|---|---|---|---|---|---|---|---|"
    if failed:
        head += " Failed requests | p95 (ms) |"
        rule += "---|---|"
    lines = [head, rule]
    for name, row in rows.items():
        speed = number(row["speedup"]) if "speedup" in row else "–"
        if "speedup" in row and row["speedup_zero"]:
            speed += " (" + ", ".join(row["speedup_zero"]) + " = 0)"
        line = (f"| {SCALERS[name]} | " + " | ".join(number(row[m]) for m in METRICS)
                + f" | {speed} | {row['scale_ups']} | {row['scale_downs']} | {row['mean_workers']:.2f} |")
        if failed:
            run = runs[name]
            line += f" {run['failed']:,} ({run['failed_pct']:.2f}%) | {run['p95_ms']:.1f} |"
        lines.append(line)
    return lines


def plot(path, title, steps, timeout_ms):
    """Requested and running workers per step above, p95 response time below."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    t = steps["minute"].astype("datetime64[s]").astype(object)
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(11, 6.5), sharex=True, gridspec_kw={"height_ratios": [3, 2]})
    top.step(t, steps["requested_cpu"], where="post", color="#1f2937", lw=1.3, ls="-.",
             label="requested, from real CPU")
    top.step(t, steps["requested_traffic"], where="post", color="#9ca3af", lw=1.2, ls=":",
             label="requested, from traffic")
    top.step(t, steps["pods"], where="post", color="#d95926", lw=2.0, label="running workers")
    top.set_ylabel("workers")
    top.set_ylim(0, 21)
    top.legend(frameon=False, ncol=3, loc="upper left")
    ok = np.isfinite(steps["p95_ms"])
    bottom.step(t, np.where(ok, steps["p95_ms"], np.nan), where="post", color="#3987e5", lw=1.4,
                label="p95 response time")
    failed = steps["failed"] > 0
    if failed.any():
        bottom.scatter(np.array(t)[failed], np.full(failed.sum(), timeout_ms), s=10, color="#b91c1c",
                       label="step with failed requests", zorder=3)
    bottom.axhline(timeout_ms, color="#b91c1c", lw=0.8, ls="--", label=f"timeout {timeout_ms / 1000:g} s")
    bottom.set_yscale("log")
    bottom.set_ylabel("ms (log)")
    bottom.set_ylim(1, timeout_ms * 3)
    bottom.legend(frameon=False, ncol=3, loc="center left")
    locator = mdates.AutoDateLocator()
    bottom.xaxis.set_major_locator(locator)
    bottom.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    for ax in (top, bottom):
        ax.grid(color="#e5e7eb", lw=0.8)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    fig.suptitle(title, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description="Report of the live runs.")
    parser.add_argument("--dir", default=os.path.join(ROOT, "results", "autoscaler_live"))
    parser.add_argument("--tag", default="", help="report the runs made with this --tag")
    parser.add_argument("--calibration", default=os.path.join(ROOT, "results", "autoscaler_live", "calibration.json"))
    args = parser.parse_args()
    suffix = f"_{args.tag}" if args.tag else ""
    names = [n for n in SCALERS if os.path.exists(os.path.join(args.dir, f"steps_{n}{suffix}.csv"))]
    assert names, "no runs found"
    steps = {n: read_steps(os.path.join(args.dir, f"steps_{n}{suffix}.csv")) for n in names}
    runs = {n: json.load(open(os.path.join(args.dir, f"run_{n}{suffix}.json"))) for n in names}
    calibration = json.load(open(args.calibration))
    info = json.load(open(os.path.join(args.dir, "window.json")))
    first, length = runs[names[0]]["first_step"], runs[names[0]]["steps"]
    assert all((r["first_step"], r["steps"]) == (first, length) for r in runs.values()), "runs cover other steps"

    pods = {n: steps[n]["pods"] for n in names}
    counts = {n: (runs[n]["scale_ups"], runs[n]["scale_downs"]) for n in names}
    live_cpu = table({n: steps[n]["requested_cpu"] for n in names}, pods, counts)
    live_traffic = table(steps[names[0]]["requested_traffic"], pods, counts)
    sim_requested, sim_runs = simulate(args.dir, first, length)
    sim = table(sim_requested, {n: sim_runs[n][0] for n in names},
                {n: sim_runs[n][1:] for n in names})

    for n in names:
        plot(os.path.join(args.dir, f"plot_{n}{suffix}.png"),
             f"{SCALERS[n]}, live: workers per step (1 step = 1 trace minute = {runs[n]['step_seconds']:g} s)",
             steps[n], 1000 * runs[n]["timeout_s"])

    minutes = steps[names[0]]["minute"]

    # Checks worth writing down
    notes = []
    if "planner" in names:
        differ = int(np.sum(sim_runs["planner"][0] != pods["planner"]))
        notes.append(f"- **Planner, live against simulated:** the worker counts differ in {differ} of {length} steps. "
                     "The planner only reads the forecasts, so they should be equal.")
    if "khpa" in names:
        differ = int(np.sum(sim_runs["khpa"][0] != pods["khpa"]))
        notes.append(f"- **KHPA, live against simulated:** the worker counts differ in {differ} of {length} steps. "
                     "Live KHPA reads CPU from Prometheus, the simulated one reads the traffic.")
    for n in names:
        gap = steps[n]["requested_cpu"] - steps[n]["requested_traffic"]
        notes.append(f"- **{SCALERS[n]}, requested from CPU minus from traffic:** mean {gap.mean():+.2f} workers, "
                     f"from {gap.min():+.0f} to {gap.max():+.0f}.")
    for n in names:
        r = runs[n]
        notes.append(f"- **{SCALERS[n]}, run:** {r['sent']:,} requests, {r['wall_seconds'] / 60:.1f} min. "
                     f"The generator queued 99% of the requests within {r['queue_delay_p99_ms']:.1f} ms of their "
                     f"planned time (max {r['queue_delay_max_ms']:.0f} ms). Prometheus did not answer in "
                     f"{r['prom_missing']} steps. Highest 1-minute load average {r['load1_max']:.1f} (16 threads).")

    lines = [
        "# Live autoscaler demo (step 4B)",
        "",
        f"Node {int(info['node'].split('_')[-1])}, {str(minutes[0]).replace('T', ' ')} to "
        f"{str(minutes[-1]).replace('T', ' ')} "
        f"(steps {first} to {first + length - 1}), replayed with real worker containers behind HAProxy.",
        f"One step = one trace minute = {runs[names[0]]['step_seconds']:g} s. "
        "Cooldowns 3 steps after a scale-up (30 s) and 5 after a scale-down (50 s), SDR 0.3.",
        "",
        f"- **Worker:** one container, 0.5 CPU, 256 MB. Each request sorts 3000 numbers, finds the eigenvalues of "
        "a 100 x 100 matrix or compresses 64 KB, with equal chance.",
        f"- **Calibration:** one worker handles {calibration['workload_pod']:,} requests per step "
        f"({calibration['rate70_per_second']:.0f} per second, {calibration['workload_pod_per_real_minute']:,} per real "
        f"minute) at 70% CPU, measured while {calibration['sweep_workers']} workers run. This is workload_pod "
        "x threshold, so the planner and the traffic-based demand use it.",
        f"- **Traffic:** scale factor {info['factor']:.4f}, so the busiest minute needs {info['peak_workers']} workers. "
        f"Mean demand {info['mean_demand_workers']:.2f} workers.",
        f"- **Scalers:** no autoscaling has {info['fixed_pods']} workers, the mean demand. KHPA: "
        "ceil(CPU from Prometheus / 0.35), at least 1. Planner: Algorithm 3 with FedAvg-BiGRU, at least 5. "
        "All start at the fixed count, at most 20.",
        "- **Failed request:** no 200 answer within 2 s of its planned send time. p95: of the requests that succeeded.",
        "",
        "## Table 11, live, requested workers from real CPU",
        "",
        "Requested workers of a step = ceil(CPU used by all workers / 0.35), at least 1.",
        "",
        *markdown_table(live_cpu, runs),
        "",
        "## Live, requested workers from the traffic",
        "",
        f"Requested workers of a step = ceil(requests / {calibration['workload_pod']:,}), the same in every run.",
        "",
        *markdown_table(live_traffic, runs),
        "",
        "## Step 4A simulation of the same steps",
        "",
        "scalers.py with the same settings and requested workers from the traffic. KHPA reads the traffic of the "
        "last step here.",
        "",
        *markdown_table(sim, failed=False),
        "",
        "## Checks",
        "",
        *notes,
        "",
        "## Dogani, Table 11 (p. 17)",
        "",
        "Simulated over 16 nodes and 17 days, not one 3-hour window, so only the direction compares.",
        "",
        "| Scaler | θU | θO | TU | TO | εn |",
        "|---|---|---|---|---|---|",
        *[f"| {SCALERS[n]} | " + " | ".join(number(v) for v in DOGANI_TABLE11[DOGANI[n]][:5]) + " |" for n in names],
        "",
        "Plots: " + ", ".join(f"[plot_{n}{suffix}.png](plot_{n}{suffix}.png)" for n in names) + ".",
    ]
    with open(os.path.join(args.dir, f"report{suffix}.md"), "w") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(args.dir, f"report{suffix}.json"), "w") as f:
        json.dump(json_safe({"live_requested_from_cpu": live_cpu, "live_requested_from_traffic": live_traffic,
                             "simulation": sim, "runs": runs, "window": info,
                             "calibration_workload_pod": calibration["workload_pod"]}), f, indent=2)
    print(f"Saved {os.path.join(args.dir, f'report{suffix}.md')}")


if __name__ == "__main__":
    main()
