"""
Paired comparison over random windows (scripts/run_random_windows.py).

For every profile folder in --runs-dir (data/runs/random_windows/<profile>/)
it reads windows.csv, runs.csv and the saved worker logs, and takes each
run's training speed: the two workers' mean steps/s inside the run, added up
("Training speed, total" in analysis/compare_runs.py). Then per window:

    gain = (proactive - reactive) / reactive

and per profile: mean ± sd of each controller's speed over the windows, the
mean, smallest and largest gain, and in how many windows proactive was faster.

Writes to --results-dir (results/random_windows/):
    summary.md                 one table per profile, plus each window
    <profile>_windows.csv      window, offset, seed, both speeds and the gain
    figures/<profile>_boxplot.pdf (and .png)
Needs only the saved files: no Prometheus and no Docker.

Usage:  python analysis/random_windows.py
        python analysis/random_windows.py --runs-dir data/runs_test/random_windows --results-dir /tmp/rw
"""
import argparse
import csv
import os
import re
import statistics
import sys
from datetime import datetime

import matplotlib
matplotlib.use("Agg")  # draw straight to files, no window needed
import matplotlib.pyplot as plt

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from compare_runs import INK, MUTED, STEPS_PATTERN, WORKERS, mean, style  # noqa: E402

RUNS_DIR = os.path.join(ROOT, "data", "runs", "random_windows")
RESULTS_DIR = os.path.join(ROOT, "results", "random_windows")
PROFILES = ["sine", "noisy_sine", "bursts"]       # order in the summary
CONTROLLERS = ["reactive", "proactive"]
TITLES = {"reactive": "Reactive", "proactive": "Proactive"}
# Categorical slots 1 and 2 of the validated default palette (as in compare_runs.py)
COLORS = {"reactive": "#2a78d6", "proactive": "#eb6834"}
WINDOW_COLUMNS = ["profile", "window", "offset_s", "seed",
                  "reactive_steps_s", "proactive_steps_s", "gain_pct"]


# ----------------------------------------------------------------------
# 1. Reading one profile's runs
# ----------------------------------------------------------------------
def read_csv(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def log_speeds(path, start, end):
    """
    The steps/s values of a saved worker log whose docker time stamp lies in
    [start, end] (Unix seconds). A line looks like
    2026-10-20T10:00:07.570588083Z t=   120s intensity=0.55 steps/s=  139.5 acc=0.986
    """
    speeds = []
    with open(path) as f:
        for line in f:
            match = STEPS_PATTERN.search(line)
            if not match:
                continue
            # Python reads only 6 decimals of the seconds, so cut the rest off
            stamp = datetime.fromisoformat(line[:26] + "+00:00").timestamp()
            if start <= stamp <= end:
                speeds.append(float(match.group(1)))
    return speeds


def run_speed(profile_dir, row):
    """Training speed of one run: each worker's mean steps/s inside the run, added up."""
    start = datetime.fromisoformat(row["start"]).timestamp()
    end = datetime.fromisoformat(row["end"]).timestamp()
    name = f"{row['controller']}_{row['repeat']}"
    return sum(mean(log_speeds(os.path.join(profile_dir, f"{name}_{w}.log"), start, end))
               for w in WORKERS)


def read_profile(profile_dir):
    """
    One dict per window that has an ok run of both controllers:
    {window, offset_s, seed, reactive, proactive, gain} (speeds in steps/s, gain in %).
    """
    speeds = {}   # (window, controller) -> steps/s
    for row in read_csv(os.path.join(profile_dir, "runs.csv")):
        if row["status"] == "ok":
            speeds[(int(row["repeat"]), row["controller"])] = run_speed(profile_dir, row)
    windows = []
    for w in read_csv(os.path.join(profile_dir, "windows.csv")):
        window = int(w["window"])
        if not all((window, c) in speeds for c in CONTROLLERS):
            print(f"{w['profile']} window {window}: not both runs ok, left out")
            continue
        reactive, proactive = speeds[(window, "reactive")], speeds[(window, "proactive")]
        windows.append({"window": window, "offset_s": int(w["offset_s"]), "seed": w["seed"],
                        "reactive": reactive, "proactive": proactive,
                        "gain": (proactive - reactive) / reactive * 100})
    return windows


# ----------------------------------------------------------------------
# 2. Numbers per profile
# ----------------------------------------------------------------------
def sd(values):
    return statistics.stdev(values) if len(values) > 1 else float("nan")


def summarize(windows):
    """Mean ± sd per controller, mean/min/max gain and proactive's wins."""
    gains = [w["gain"] for w in windows]
    return {
        "n": len(windows),
        **{c: (statistics.mean(w[c] for w in windows), sd([w[c] for w in windows]))
           for c in CONTROLLERS},
        "gain_mean": statistics.mean(gains),
        "gain_sd": sd(gains),
        # The earlier reports (compare_runs.py) give the gain of the means instead
        "gain_of_means": (statistics.mean(w["proactive"] for w in windows)
                          / statistics.mean(w["reactive"] for w in windows) - 1) * 100,
        "gain_min": min(gains),
        "gain_max": max(gains),
        "wins": sum(w["proactive"] > w["reactive"] for w in windows),
    }


# ----------------------------------------------------------------------
# 3. Output: tables, CSV and box plots
# ----------------------------------------------------------------------
def profile_tables(profile, windows, s):
    seed = windows[0]["seed"]
    lines = [f"## {profile}", "",
             f"{s['n']} windows, offsets drawn with seed {seed} "
             f"(`{profile}_windows.csv`). Training speed = both workers' steps/s added up.", "",
             "| Controller | Training speed (steps/s), mean ± sd |", "|---|---|"]
    for c in CONTROLLERS:
        lines.append(f"| {TITLES[c]} | {s[c][0]:.1f} ± {s[c][1]:.1f} |")
    lines += ["",
              "| Mean gain ± sd | Min gain | Max gain | Proactive faster |", "|---|---|---|---|",
              f"| {s['gain_mean']:+.1f}% ± {s['gain_sd']:.1f} | {s['gain_min']:+.1f}% | "
              f"{s['gain_max']:+.1f}% | {s['wins']} of {s['n']} |", "",
              "| Window | Offset (s) | Reactive (steps/s) | Proactive (steps/s) | Gain |",
              "|---|---|---|---|---|"]
    for w in windows:
        lines.append(f"| {w['window']} | {w['offset_s']} | {w['reactive']:.1f} | "
                     f"{w['proactive']:.1f} | {w['gain']:+.1f}% |")
    return lines + [""]


FIXED_GAIN = re.compile(r"^\| Training speed \(steps/s\) \|.*\(([+-]\d+)%\) \|$", re.M)


def fixed_window_gain(profile):
    """
    The training-speed gain of the earlier fixed-window runs (profile from
    t = 0), as text like "+26%", from results/<profile>/comparison.md; "-" if missing.
    """
    try:
        with open(os.path.join(ROOT, "results", profile, "comparison.md")) as f:
            match = FIXED_GAIN.search(f.read())
    except FileNotFoundError:
        return "-"
    return f"{match.group(1)}%" if match else "-"


def write_summary(path, results):
    lines = ["# Random windows: proactive vs reactive", "",
             "Written by `analysis/random_windows.py` from the runs of "
             "`scripts/run_random_windows.py`. Each window starts its load profile at a "
             "random offset; reactive and proactive run on the same window (paired), "
             "gain = (proactive - reactive) / reactive per window. \"Gain of means\" is "
             "computed like the earlier reports (proactive mean / reactive mean), so it "
             "compares directly with the fixed window: all earlier runs started the "
             "profile at t = 0 (`results/<profile>/comparison.md`).", "",
             "| Profile | Windows | Reactive (steps/s) | Proactive (steps/s) | Mean gain | "
             "Min gain | Max gain | Proactive faster | Gain of means | Fixed window |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for profile, (windows, s) in results.items():
        lines.append(f"| {profile} | {s['n']} | {s['reactive'][0]:.1f} ± {s['reactive'][1]:.1f} | "
                     f"{s['proactive'][0]:.1f} ± {s['proactive'][1]:.1f} | "
                     f"{s['gain_mean']:+.1f}% | {s['gain_min']:+.1f}% | {s['gain_max']:+.1f}% | "
                     f"{s['wins']} of {s['n']} | {s['gain_of_means']:+.1f}% | "
                     f"{fixed_window_gain(profile)} |")
    lines.append("")
    for profile, (windows, s) in results.items():
        lines += profile_tables(profile, windows, s)
    with open(path, "w") as f:
        f.write("\n".join(lines))


def write_windows_csv(path, profile, windows):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=WINDOW_COLUMNS)
        writer.writeheader()
        for w in windows:
            writer.writerow({"profile": profile, "window": w["window"], "offset_s": w["offset_s"],
                             "seed": w["seed"], "reactive_steps_s": f"{w['reactive']:.2f}",
                             "proactive_steps_s": f"{w['proactive']:.2f}",
                             "gain_pct": f"{w['gain']:.2f}"})


def plot_box(figures_dir, profile, windows, s):
    """
    One box per controller (training speed over the windows). Each window's two
    runs are dots joined by a thin gray line, so the pairing stays visible.
    """
    fig, ax = plt.subplots(figsize=(4.2, 3.4))
    data = [[w[c] for w in windows] for c in CONTROLLERS]
    boxes = ax.boxplot(data, positions=[1, 2], widths=0.45, patch_artist=True,
                       showfliers=False, medianprops={"color": INK, "linewidth": 1.6},
                       whiskerprops={"color": MUTED}, capprops={"color": MUTED})
    for box, c in zip(boxes["boxes"], CONTROLLERS):
        box.set(facecolor=COLORS[c], alpha=0.25, edgecolor=COLORS[c], linewidth=1.2)
    for w in windows:
        ax.plot([1, 2], [w["reactive"], w["proactive"]], color=MUTED, linewidth=0.8,
                alpha=0.7, zorder=2)
    for x, c in zip([1, 2], CONTROLLERS):
        ax.scatter([x] * len(windows), [w[c] for w in windows], s=22, color=COLORS[c],
                   edgecolor="white", linewidth=0.8, zorder=3)
    ax.set_xticks([1, 2], [TITLES[c] for c in CONTROLLERS])
    ax.set_xlim(0.5, 2.5)
    ax.set_ylabel("Training speed (steps/s)")
    ax.set_title(f"{profile}, {s['n']} random windows\nmean gain {s['gain_mean']:+.0f}%, "
                 f"proactive faster in {s['wins']} of {s['n']}", fontsize=9, color=INK)
    ax.grid(axis="x", visible=False)
    fig.tight_layout()
    for ext in ("pdf", "png"):
        fig.savefig(os.path.join(figures_dir, f"{profile}_boxplot.{ext}"), dpi=150)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description="Paired comparison over random windows.")
    parser.add_argument("--runs-dir", default=RUNS_DIR, help="folder with one folder per profile")
    parser.add_argument("--results-dir", default=RESULTS_DIR, help="where the results go")
    args = parser.parse_args()

    style()
    figures_dir = os.path.join(args.results_dir, "figures")
    os.makedirs(figures_dir, exist_ok=True)
    results = {}
    for profile in PROFILES:
        profile_dir = os.path.join(args.runs_dir, profile)
        if not os.path.exists(os.path.join(profile_dir, "runs.csv")):
            continue
        windows = read_profile(profile_dir)
        if not windows:
            print(f"{profile}: no complete windows")
            continue
        s = summarize(windows)
        results[profile] = (windows, s)
        write_windows_csv(os.path.join(args.results_dir, f"{profile}_windows.csv"), profile, windows)
        plot_box(figures_dir, profile, windows, s)
        print(f"{profile}: {s['n']} windows, mean gain {s['gain_mean']:+.1f}% "
              f"({s['gain_min']:+.1f}% to {s['gain_max']:+.1f}%), proactive faster in "
              f"{s['wins']} of {s['n']}")
    write_summary(os.path.join(args.results_dir, "summary.md"), results)
    print(f"Wrote {os.path.join(args.results_dir, 'summary.md')}")


if __name__ == "__main__":
    main()
