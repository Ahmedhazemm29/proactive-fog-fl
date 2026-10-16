"""
The live runs on four windows (step 4B): one table per window, a summary
over all windows, plain answers to three questions and one plot.

Usage (after scripts/live_report.py has made report.json in every window folder):
    .venv/bin/python scripts/live_windows_report.py

Windows: the first live window (node 0, centred on its busiest half hour, in
results/autoscaler_live/) and the three windows of scripts/live_windows.py
(calm, rise and spiky, each in its own folder). Table 11 uses the workers
requested from real CPU, as the main table of report.md does.

Outputs in --out-dir (default: --dir, results/autoscaler_live/):
  windows_report.md    the tables and the answers
  windows_report.json  the same numbers
  windows_workers.png  each window's traffic with the workers of each scaler
"""
import argparse
import json
import os
import sys
from datetime import datetime

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from autoscaler.metrics import METRICS  # noqa: E402
from live_report import SCALERS, read_steps, simulate  # noqa: E402
from live_run import read_window  # noqa: E402
from simulate_autoscaler import json_safe, number  # noqa: E402

# Window: (folder under --dir, its entry in windows.json, the rule that chose it)
WINDOWS = {
    "original": ("", "busiest", "busiest half hour of node 0, centred on it"),
    "calm": ("calm", "calm", "lowest peak/mean"),
    "rise": ("rise", "rise", "biggest 1-minute rise relative to the mean, centred on it"),
    "spiky": ("spiky", "spiky", "biggest 1-minute jump relative to the mean, centred on it"),
}
SYMBOLS = {"theta_u": "θU", "theta_o": "θO", "t_u": "TU", "t_o": "TO"}


def as_float(value):
    """report.json keeps inf and nan as strings, float() turns them back."""
    return None if value is None else float(value)


def load(folder):
    """The rows of report.json (requested workers from CPU), the traffic and the workers per step."""
    report = json.load(open(os.path.join(folder, "report.json")))
    rows = {}
    for name, row in report["live_requested_from_cpu"].items():
        run = report["runs"][name]
        rows[name] = {m: row[m] for m in METRICS} | {
            "speedup": as_float(row.get("speedup")), "speedup_zero": row.get("speedup_zero", []),
            "scale_ups": row["scale_ups"], "scale_downs": row["scale_downs"],
            "actions": row["scale_ups"] + row["scale_downs"], "mean_workers": row["mean_workers"],
            "sent": run["sent"], "failed": run["failed"], "failed_pct": run["failed_pct"], "p95_ms": run["p95_ms"]}
    traffic = report["live_requested_from_traffic"]
    traffic_speedup = {name: as_float(row.get("speedup")) for name, row in traffic.items()}
    steps, _, requests, _ = read_window(os.path.join(folder, "window.csv"))
    per_step = {name: read_steps(os.path.join(folder, f"steps_{name}.csv")) for name in rows}
    return {"rows": rows, "traffic_speedup": traffic_speedup, "window": report["window"],
            "traffic_none_zero": traffic.get("none", {}).get("speedup_zero", []),
            "traffic": requests[steps >= 0], "pods": {name: s["pods"] for name, s in per_step.items()},
            "steps": per_step, "runs": report["runs"], "folder": folder}


def when(first, last):
    """'23 Jul 07:30 to 10:29', with the second date only when the window passes midnight."""
    a, b = datetime.fromisoformat(first), datetime.fromisoformat(last)
    end = b.strftime("%H:%M") if a.date() == b.date() else b.strftime("%-d %b %H:%M")
    return f"{a.strftime('%-d %b %H:%M')} to {end}"


def window_table(results, shapes):
    lines = ["| Window | Rule | Node | Time (1998) | Trace rows | Mean demand (workers) | Peak/mean "
             "| Biggest 1-minute jump | Fixed workers |",
             "|---|---|---|---|---|---|---|---|---|"]
    for w, r in results.items():
        info, shape = r["window"], shapes[w]
        lines.append(f"| {w} | {WINDOWS[w][2]} | {shape['node']} | {when(info['first_minute'], info['last_minute'])} "
                     f"| {shape['first_row']:,} to {shape['last_row']:,} | {info['mean_demand_workers']:.2f} "
                     f"| {shape['peak_mean']:.2f} | {shape['biggest_jump']:+,.0f} ({shape['biggest_jump_pct']:.0f}%) "
                     f"| {info['fixed_pods']} |")
    return lines


def results_table(rows):
    lines = ["| Scaler | θU | θO | TU | TO | εn | Failed requests | p95 (ms) | Mean workers | #Up / #Down |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for name in SCALERS:
        if name not in rows:
            lines.append(f"| {SCALERS[name]} | skipped, the run failed twice" + " | –" * 8 + " |")
            continue
        r = rows[name]
        speed = "–" if r["speedup"] is None else number(r["speedup"])
        if r["speedup_zero"]:
            speed += " (" + ", ".join(SYMBOLS[m] for m in r["speedup_zero"]) + " = 0)"
        lines.append(f"| {SCALERS[name]} | " + " | ".join(number(r[m]) for m in METRICS)
                     + f" | {speed} | {r['failed']:,} ({r['failed_pct']:.2f}%) | {r['p95_ms']:.1f} "
                       f"| {r['mean_workers']:.2f} | {r['scale_ups']} / {r['scale_downs']} |")
    return lines


SUMMARY = [("θU", "theta_u", 2), ("θO", "theta_o", 2), ("TU", "t_u", 2), ("TO", "t_o", 2), ("εn", "speedup", 2),
           ("Failed requests (%)", "failed_pct", 2), ("p95 (ms)", "p95_ms", 1), ("Mean workers", "mean_workers", 2),
           ("Scaling actions (up + down)", "actions", 0)]


def counted(r, name, key):
    """Whether a window adds this scaler's value to the summary: εn only where it is defined."""
    if name not in r["rows"]:
        return False
    return key != "speedup" or ("none" in r["rows"] and defined(r["rows"]))


def summary(results):
    """{metric: {scaler: (mean, min, max, windows)}} over the windows that have the run."""
    out = {}
    for _, key, _ in SUMMARY:
        out[key] = {}
        for name in SCALERS:
            values = [r["rows"][name][key] for r in results.values() if counted(r, name, key)]
            if values:
                out[key][name] = (float(np.mean(values)), float(min(values)), float(max(values)), len(values))
    return out


def summary_table(stats):
    lines = ["| Metric | " + " | ".join(SCALERS.values()) + " |", "|---|" + "---|" * len(SCALERS)]
    for label, key, digits in SUMMARY:
        cells = []
        for name in SCALERS:
            if name not in stats[key]:
                cells.append("–")
                continue
            mean, low, high, _ = stats[key][name]
            cells.append(f"{number(mean, digits)} ({number(low, digits)} to {number(high, digits)})")
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    return lines


def holds(results, test):
    """The windows where a claim holds, fails or is not defined (only windows with all three runs)."""
    yes, no, undefined = [], [], []
    for w, r in results.items():
        if {"none", "khpa", "planner"} <= set(r["rows"]):
            result = test(r["rows"])
            (undefined if result is None else yes if result else no).append(w)
    return yes, no, undefined


def listing(windows):
    """'calm', 'calm and rise', 'original, calm and rise', or 'none'."""
    if not windows:
        return "none"
    return windows[0] if len(windows) == 1 else ", ".join(windows[:-1]) + " and " + windows[-1]


def winner(planner, khpa, none_zero):
    """
    Who has the higher εn. When no autoscaling has a θ or T of 0 (none_zero),
    Eq. 18 gives every scaler 0 or 0/0, so εn picks no winner: "not defined".
    """
    if none_zero:
        return "not defined"
    return "planner" if planner > khpa else "KHPA" if khpa > planner else "tie"


def winner_sentence(winners, n):
    """Who has the higher εn: in all n windows, or in which ones."""
    def sentence(kind, where):
        if kind == "tie":
            return f"it is a tie in {where}."
        if kind == "not defined":
            return f"in {where} εn is not defined, because no autoscaling has a θ or T of 0 there."
        return f"{'the planner' if kind == 'planner' else kind} wins in {where}."

    kinds = sorted(set(winners.values()), key=lambda kind: (kind == "not defined", kind))
    if len(kinds) == 1 and kinds[0] in ("planner", "KHPA"):
        sentences = [f"{'the planner' if kinds[0] == 'planner' else 'KHPA'} has the higher εn in all {n} windows."]
    else:
        sentences = [sentence(kind, listing([w for w, v in winners.items() if v == kind])) for kind in kinds]
    return " ".join(s[0].upper() + s[1:] for s in sentences)


def defined(r):
    """False when no autoscaling has a θ or T of 0 in this window: then εn is not defined."""
    return not r["none"]["speedup_zero"]


# Dogani's claims about Table 11 (p. 17, finding 4.8): the planner against KHPA, and both against fixed pods.
# A test gives None when it needs εn and εn is not defined.
CLAIMS = [
    ("The planner has fewer shortages than KHPA: lower θU and lower TU.",
     lambda r: r["planner"]["theta_u"] < r["khpa"]["theta_u"] and r["planner"]["t_u"] < r["khpa"]["t_u"]),
    ("The planner has a higher εn than KHPA.",
     lambda r: r["planner"]["speedup"] > r["khpa"]["speedup"] if defined(r) else None),
    ("The planner scales less often than KHPA.",
     lambda r: r["planner"]["actions"] < r["khpa"]["actions"]),
    ("KHPA over-provisions less than the planner: lower θO.",
     lambda r: r["khpa"]["theta_o"] < r["planner"]["theta_o"]),
    ("Both scalers beat no autoscaling: εn above 1.",
     lambda r: r["khpa"]["speedup"] > 1 and r["planner"]["speedup"] > 1 if defined(r) else None),
]


def answers(results):
    """Plain answers to the three questions of the task."""
    n = sum({"none", "khpa", "planner"} <= set(r["rows"]) for r in results.values())
    lines = ["| Window | θU planner / KHPA | TU planner / KHPA | εn planner / KHPA | εn winner "
             "| εn winner, requested from traffic |", "|---|---|---|---|---|---|"]
    winners, traffic_winners = {}, {}
    for w, r in results.items():
        if not {"none", "khpa", "planner"} <= set(r["rows"]):
            continue
        p, k = r["rows"]["planner"], r["rows"]["khpa"]
        winners[w] = winner(p["speedup"], k["speedup"], r["rows"]["none"]["speedup_zero"])
        traffic_winners[w] = winner(r["traffic_speedup"]["planner"], r["traffic_speedup"]["khpa"],
                                    r["traffic_none_zero"])
        lines.append(f"| {w} | {number(p['theta_u'])} / {number(k['theta_u'])} "
                     f"| {number(p['t_u'])} / {number(k['t_u'])} "
                     f"| {number(p['speedup'], 3)} / {number(k['speedup'], 3)} "
                     f"| {winners[w]} | {traffic_winners[w]} |")
    lines.append("")

    yes, no, _ = holds(results, CLAIMS[0][1])
    if not no:
        lines.append(f"1. **Fewer shortages: yes.** The planner has a lower θU and a lower TU than KHPA in all "
                     f"{n} windows.")
    else:
        lines.append(f"1. **Fewer shortages: not everywhere.** The planner has a lower θU and a lower TU than KHPA "
                     f"in {len(yes)} of {n} windows. It does not in: {listing(no)}.")

    sentence = winner_sentence(winners, n)
    kinds = set(winners.values()) - {"not defined"}
    changes = "it does not change" if len(kinds) == 1 else "it changes"
    lines.append(f"2. **εn winner: {changes}.** {sentence}")
    lines.append("   With requested workers from the traffic (finding 4.11): " + winner_sentence(traffic_winners, n))

    lines += ["3. **Dogani's claims:** each claim of Table 11 (p. 17), checked per window with requested workers "
              "from real CPU.", "",
              "   | Claim | Holds in | Fails in |", "   |---|---|---|"]
    broken = []
    for text, test in CLAIMS:
        yes, no, undefined = holds(results, test)
        note = f", not defined in {listing(undefined)}" if undefined else ""
        lines.append(f"   | {text} | {len(yes)} of {len(yes) + len(no)} | {listing(no)}{note} |")
        if no:
            broken.append((text, no))
    lines.append("")
    if broken:
        lines.append("   So yes, some windows break a claim: " + " ".join(
            f"\"{text[:-1]}\" fails in {listing(no)}." for text, no in broken))
    else:
        lines.append("   So no window breaks any of these claims.")
    lost = {name: sum(r["rows"][name]["failed"] for r in results.values() if name in r["rows"]) for name in SCALERS}
    lines += ["", f"Not in Table 11, but what users notice: over the {len(results)} windows the planner lost "
                  f"{lost['planner']:,} requests, KHPA {lost['khpa']:,} and no autoscaling {lost['none']:,}. "
                  "The reasons behind these answers are in `docs/decisions.md`, findings 4.14 to 4.17."]
    return lines, winners, traffic_winners


def check_table(results):
    """
    Per window: the CPU KHPA read from Prometheus against the real CPU (the
    cgroup CPU of the step that had just ended), the planner's steps that
    differ from the step 4A simulation, the generator's delay and the laptop load.
    """
    lines = ["| Window | KHPA's CPU from Prometheus / real CPU | Planner steps unlike step 4A "
             "| Generator, p99 delay (ms) | Highest load average |", "|---|---|---|---|---|"]
    checked = {}
    for w, r in results.items():
        khpa, planner = "–", "–"
        if "khpa" in r["steps"]:
            prom, real = r["steps"]["khpa"]["prom_cpu"][1:], r["steps"]["khpa"]["cpu_total"][:-1]
            ok = np.isfinite(prom)
            checked[w] = float(prom[ok].sum() / real[ok].sum())
            khpa = f"{checked[w]:.2f}"
        if "planner" in r["steps"]:
            run = r["runs"]["planner"]
            _, simulated = simulate(r["folder"], run["first_step"], run["steps"])
            differ = int(np.sum(simulated["planner"][0] != r["steps"]["planner"]["pods"]))
            planner = f"{differ} of {run['steps']}"
        delay = max(run["queue_delay_p99_ms"] for run in r["runs"].values())
        load = max(run["load1_max"] for run in r["runs"].values())
        lines.append(f"| {w} | {khpa} | {planner} | {delay:.1f} | {load:.1f} |")
    return lines, checked


def plot(path, results, workload_pod):
    """Each window's traffic, in workers needed, with the workers of each scaler."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    styles = {"none": dict(color="#6b7280", ls="--", lw=1.4), "khpa": dict(color="#3987e5", lw=1.5),
              "planner": dict(color="#d95926", lw=1.8)}
    fig, axes = plt.subplots(2, 2, figsize=(13, 7.6), sharex=True, sharey=True)
    for ax, (w, r) in zip(axes.flat, results.items()):
        x = np.arange(len(r["traffic"]))
        ax.fill_between(x, r["traffic"] / workload_pod, step="post", color="#d1d5db", lw=0,
                        label=f"traffic in workers (requests / {workload_pod:,})")
        for name in SCALERS:
            if name in r["pods"]:
                ax.step(x, r["pods"][name], where="post", label=f"{SCALERS[name]}, running workers", **styles[name])
        ax.axhline(20, color="#9ca3af", lw=0.8, ls=":")
        ax.text(x[-1], 20.3, "cap 20", ha="right", va="bottom", fontsize=8, color="#6b7280")
        node = int(r["window"]["node"].split("_")[-1])
        span = when(r["window"]["first_minute"], r["window"]["last_minute"])
        ax.set_title(f"{w.capitalize()}, node {node}: {span}", loc="left", fontsize=10)
        ax.set_ylim(0, 22)
        ax.set_yticks(range(0, 21, 5))
        ax.grid(color="#e5e7eb", lw=0.8)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    for ax in axes[:, 0]:
        ax.set_ylabel("workers")
    for ax in axes[-1, :]:
        ax.set_xlabel("step = trace minute (10 s live)")
    handles, labels = axes.flat[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=4, frameon=False, fontsize=9)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(path, dpi=130)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description="Report of the live runs on four windows.")
    parser.add_argument("--dir", default=os.path.join(ROOT, "results", "autoscaler_live"))
    parser.add_argument("--out-dir", default=None, help="default: --dir")
    args = parser.parse_args()
    out_dir = args.out_dir or args.dir
    shapes = json.load(open(os.path.join(args.dir, "windows.json")))
    calibration = json.load(open(os.path.join(args.dir, "calibration.json")))

    results, shape = {}, {}
    for w, (folder, entry, _) in WINDOWS.items():
        path = os.path.join(args.dir, folder)
        if not os.path.exists(os.path.join(path, "report.json")):
            print(f"{w}: no report.json, left out")
            continue
        results[w] = load(path)
        shape[w] = shapes[entry] if entry == "busiest" else shapes[entry][0]
        assert shape[w]["first_minute"] == results[w]["window"]["first_minute"], f"{w}: not the window of windows.json"
    stats = summary(results)
    answer_lines, winners, traffic_winners = answers(results)
    checks, khpa_input = check_table(results)
    plot(os.path.join(out_dir, "windows_workers.png"), results, calibration["workload_pod"])

    missing = [f"{w} {SCALERS[name]}" for w, r in results.items() for name in SCALERS if name not in r["rows"]]
    undefined = [w for w, r in results.items() if "none" in r["rows"] and not defined(r["rows"])]
    lines = [
        "# Live runs on four windows (step 4B)",
        "",
        "The step 4B setup, unchanged, on four 3-hour windows instead of one. Each window is replayed with every "
        "scaler, one run after the other. The cluster is rebuilt before each run.",
        "",
        "- **Same as step 4B:** 180 steps of 10 s plus 3 warm-up steps, workers of 0.5 CPU, HAProxy, cooldowns "
        "of 3 and 5 steps, at most 20 workers, a failed request is one without an answer within 2 s.",
        f"- **Scale:** each window is scaled so that its busiest minute needs 18 workers at "
        f"{calibration['workload_pod']:,} requests per step. No autoscaling keeps the rounded mean demand.",
        "- **Requested workers:** from real CPU, ceil(CPU of all workers / 0.35), at least 1. This is the main "
        "table of step 4B. εn compares each scaler with no autoscaling in the same window. Above 1 is better.",
        "- **Windows:** all four lie in the test split, inside the minutes with forecasts. The three new ones "
        "come from `scripts/live_windows.py`. Every window's mean is at least the median of its node's test "
        "minutes, so no window is a quiet stretch where a jump is only noise.",
        "",
        "## The windows",
        "",
        "Trace rows count from 0 in `data/synthetic/node_<node>.csv`. The jump is in requests per minute of the "
        "trace, before scaling, with its share of the window mean. A plus is a rise.",
        "",
        *window_table(results, shape),
        "",
        "## Results per window",
        "",
    ]
    for w, r in results.items():
        lines += [f"**{w}**, node {shape[w]['node']}, {when(r['window']['first_minute'], r['window']['last_minute'])}:",
                  "", *results_table(r["rows"]), ""]
    lines += [
        "## All four windows",
        "",
        "Mean over the windows, with the lowest and highest window in brackets.",
        "",
        *summary_table(stats),
        "",
        *([f"Skipped runs, left out of the summary: {', '.join(missing)}.", ""] if missing else []),
        *([f"εn leaves out {listing(undefined)}, where it is not defined.", ""] if undefined else []),
        "## Answers",
        "",
        *answer_lines,
        "",
        "## Plot",
        "",
        "![Traffic and workers per window](windows_workers.png)",
        "",
        "Grey: the traffic of each step divided by the calibrated 1,650 requests per worker. Lines: the workers "
        "each scaler ran. Each window folder also has `report.md` and one `plot_<scaler>.png` per run, with the "
        "requested workers and the p95 response time.",
        "",
        "## Checks",
        "",
        "- **KHPA's input:** at each step start KHPA reads the 15 s CPU rate from Prometheus. The table divides "
        "its sum over the run by the real CPU from the cgroup files, for the step that had just ended. "
        "1.00 means KHPA saw the real CPU.",
        "- **Planner:** it only reads the forecasts, so it must run the same workers as the step 4A simulation.",
        "- **Generator and laptop:** the worst p99 delay of the load generator against the planned send times, "
        "and the highest 1-minute load average of the window's runs, on 16 threads.",
        "",
        *checks,
    ]
    with open(os.path.join(out_dir, "windows_report.md"), "w") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(out_dir, "windows_report.json"), "w") as f:
        json.dump(json_safe({"windows": {w: {"window": r["window"], "shape": shape[w], "rows": r["rows"],
                                             "speedup_from_traffic": r["traffic_speedup"]} for w, r in results.items()},
                             "summary": stats, "speedup_winner": winners,
                             "speedup_winner_from_traffic": traffic_winners,
                             "khpa_prometheus_over_real_cpu": khpa_input}), f, indent=2)
    print(f"Saved {os.path.join(out_dir, 'windows_report.md')}")


if __name__ == "__main__":
    main()
