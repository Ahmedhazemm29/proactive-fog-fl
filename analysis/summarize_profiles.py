"""
Compare reactive vs proactive across load profiles (tables for results/profiles_summary.md).

Reads, for every profile:
    1. the per-run totals that analysis/compare_runs.py wrote to its
       comparison.md ("Every run" table): training speed, CPU used, unmet demand
    2. the workers' intended load (ground truth from the worker logs), to
       describe each profile: how busy each worker is, whether the two workers
       peak together, and how often their total is above the 1.0 CPU budget
    3. the controllers' CSV logs, to show where they put the CPU: the limit a
       worker had while it was busy and while it was almost idle
Prints markdown tables. Each metric gets mean ± sd over the repeats, the
proactive minus reactive difference, and whether the runs overlap: "no"
means every proactive run was on the same side of every reactive run.

Usage:  python analysis/summarize_profiles.py
"""
import csv
import os
import re
import statistics
from datetime import datetime

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
WORKERS = ["fl-worker-1", "fl-worker-2"]
BUDGET = 1.0   # CPU shared by both workers

# name: (comparison.md, folder with runs.csv, worker logs)
PROFILES = {
    # 2 October runs, before load profiles existed: the old built-in sine.
    # Their worker logs only survive in the backups made on 2026-10-04.
    "sine": ("results/comparison.md", "data/runs", "data/worker_logs/{worker}_until_2026-10-04.log"),
    "bursts": ("results/bursts/comparison.md", "data/runs/bursts",
               "data/runs/bursts/{run}_{worker}.log"),
    "noisy_sine": ("results/noisy_sine/comparison.md", "data/runs/noisy_sine",
                   "data/runs/noisy_sine/{run}_{worker}.log"),
}
METRICS = [  # column in the "Every run" table, title, digits, higher is better?
    ("Training speed (steps/s)", "Training speed (steps/s)", 1, True),
    ("CPU used (CPU)", "CPU used (CPU)", 3, True),
    ("Unmet demand (CPU)", "Unmet demand (CPU)", 3, False),
]


# ----------------------------------------------------------------------
# 1. The tables compare_runs.py wrote to its results file
# ----------------------------------------------------------------------
def read_table(path, heading):
    """Return the markdown table under `## heading` as a list of {column: cell} dicts."""
    section = open(os.path.join(ROOT, path)).read().split(f"## {heading}")[1]
    lines = [l for l in section.split("\n## ")[0].splitlines() if l.startswith("|")]
    header = [c.strip() for c in lines[0].strip("|").split("|")]
    return [dict(zip(header, (c.strip() for c in l.strip("|").split("|")))) for l in lines[2:]]


def read_results(path):
    """
    Returns the numbers of one profile:
      totals[controller][column]  "mean ± sd" text, exactly as in comparison.md
      diffs[column]               "+0.075 (+13%)" text, exactly as in comparison.md
      runs[controller][column]    list of the per-run totals (for the overlap check)
    """
    totals, diffs, runs = {}, {}, {}
    for row in read_table(path, "Mean ± standard deviation"):
        if row["Worker"] == "**Total**":
            totals[row["Controller"]] = row
    for row in read_table(path, "Proactive compared with reactive"):
        diffs[row["Metric (total)"]] = row["Difference"]
    for row in read_table(path, "Every run (totals)"):
        per_run = runs.setdefault(row["Controller"], {})
        for column, _, _, _ in METRICS:
            per_run.setdefault(column, []).append(float(row[column]))
    return totals, diffs, runs


# ----------------------------------------------------------------------
# 2. The intended load, from the worker logs
# ----------------------------------------------------------------------
NEW_LINE = re.compile(r"^(\S+) load t=(\d+) mode=\S+ intensity=([\d.]+)")   # every second
OLD_LINE = re.compile(r"^(\S+) t=\s*\d+s intensity=([\d.]+) steps/s")        # old, every 10 s


def stamp(text):
    """docker time stamp (UTC, nanoseconds) -> Unix seconds"""
    return datetime.fromisoformat(text[:26] + "+00:00").timestamp()


def runs_of(profile):
    """The rows of the profile's runs.csv (only runs that ended ok)."""
    path = os.path.join(ROOT, PROFILES[profile][1], "runs.csv")
    return [row for row in csv.DictReader(open(path)) if row["status"] == "ok"]


def intended_load(profile, row, worker):
    """
    {key: (time, intended load)} of one worker during the controlled part of
    one run (warm-up excluded). The key pairs the two workers' readings: the
    profile second (new logs, one line per second) or the 10 s slot (old logs).
    """
    start = datetime.fromisoformat(row["start"]).timestamp()
    end = datetime.fromisoformat(row["end"]).timestamp()
    path = os.path.join(ROOT, PROFILES[profile][2].format(
        run=f"{row['controller']}_{row['repeat']}", worker=worker))
    loads = {}
    for line in open(path):
        new, old = NEW_LINE.match(line), OLD_LINE.match(line)
        if new and start <= stamp(new.group(1)) <= end:
            loads[int(new.group(2))] = (stamp(new.group(1)), float(new.group(3)))
        elif old and start <= stamp(old.group(1)) <= end:
            loads[round(stamp(old.group(1)) / 10)] = (stamp(old.group(1)), float(old.group(2)))
    return loads


def load_pairs(profile):
    """Intended load of both workers at the same moments, as pairs (worker 1, worker 2)."""
    pairs = []
    for row in runs_of(profile):
        w1, w2 = (intended_load(profile, row, w) for w in WORKERS)
        pairs += [(w1[k][1], w2[k][1]) for k in sorted(w1) if k in w2]
    return pairs


def limit_while(profile, controller):
    """
    How the controller handed out CPU: the average total of both limits, and
    a worker's average limit while it was busy (load >= 0.7) and while it was
    almost idle (load <= 0.3). A limit holds until the controller's next decision.
    """
    busy, idle, totals = [], [], []
    for row in runs_of(profile):
        if row["controller"] != controller:
            continue
        decisions = {w: [] for w in WORKERS}   # (time, new limit) from the controller's CSV
        for d in csv.DictReader(open(os.path.join(ROOT, row["csv"]))):
            decisions[d["worker"]].append((datetime.fromisoformat(d["timestamp"]).timestamp(),
                                           float(d["new_limit"])))
        for w in WORKERS:
            for t, load in intended_load(profile, row, w).values():
                before = [limit for when, limit in decisions[w] if when <= t]
                limit = before[-1] if before else 0.5    # runs start at 0.5 CPU each
                if load >= 0.7:
                    busy.append(limit)
                elif load <= 0.3:
                    idle.append(limit)
        totals += [a + b for (_, a), (_, b) in zip(*decisions.values())]
    return statistics.mean(totals), statistics.mean(busy), statistics.mean(idle)


# ----------------------------------------------------------------------
# 3. Tables
# ----------------------------------------------------------------------
def load_table(profiles):
    lines = ["| Profile | Worker 1 load | Worker 2 load | Correlation of the two loads | "
             "Total load | Time total is above 1.0 CPU |",
             "|---|---:|---:|---:|---:|---:|"]
    for p in profiles:
        pairs = load_pairs(p)
        w1, w2 = [a for a, _ in pairs], [b for _, b in pairs]
        total = [a + b for a, b in pairs]
        over = sum(t > BUDGET for t in total) / len(total)
        lines.append(f"| {p} | {statistics.mean(w1):.2f} | {statistics.mean(w2):.2f} | "
                     f"{statistics.correlation(w1, w2):+.2f} | {statistics.mean(total):.2f} "
                     f"({min(total):.2f} to {max(total):.2f}) | {over:.0%} |")
    return "\n".join(lines)


def limits_table(profiles):
    lines = ["| Profile | Controller | Both limits together | Limit while busy | Limit while idle |",
             "|---|---|---:|---:|---:|"]
    for p in profiles:
        for c in ("reactive", "proactive"):
            total, busy, idle = limit_while(p, c)
            lines.append(f"| {p} | {c} | {total:.2f} | {busy:.2f} | {idle:.2f} |")
    return "\n".join(lines)


def results_table(profiles, results):
    lines = ["| Profile | Controller | " + " | ".join(t for _, t, _, _ in METRICS) + " |",
             "|---|---|" + "---:|" * len(METRICS)]
    for p in profiles:
        totals, _, _ = results[p]
        for c in ("reactive", "proactive"):
            cells = [totals[c][column] for column, _, _, _ in METRICS]
            lines.append(f"| {p} | {c} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def difference_table(profiles, results):
    lines = ["| Profile | Metric | Reactive runs | Proactive runs | Proactive − reactive | "
             "Runs overlap? |",
             "|---|---|---|---|---:|---|"]
    for p in profiles:
        _, diffs, runs = results[p]
        for column, title, digits, higher_is_better in METRICS:
            r, a = runs["reactive"][column], runs["proactive"][column]
            # The ranges overlap if the lowest top is above the highest bottom.
            overlap = max(min(r), min(a)) <= min(max(r), max(a))
            better = (float(diffs[column].split()[0]) > 0) == higher_is_better
            verdict = "yes" if overlap else ("no, proactive better" if better else "no, reactive better")
            fmt = lambda v: f"{v:.{digits}f}"
            lines.append(f"| {p} | {title} | {fmt(min(r))} to {fmt(max(r))} | "
                         f"{fmt(min(a))} to {fmt(max(a))} | {diffs[column]} | {verdict} |")
    return "\n".join(lines)


def main():
    profiles = [p for p, (path, _, _) in PROFILES.items() if os.path.exists(os.path.join(ROOT, path))]
    missing = [p for p in PROFILES if p not in profiles]
    if missing:
        print(f"(no results yet for: {', '.join(missing)})\n")
    results = {p: read_results(PROFILES[p][0]) for p in profiles}
    print("## Load per profile\n\n" + load_table(profiles) + "\n")
    print("## Results (mean ± sd over 3 runs each)\n\n" + results_table(profiles, results) + "\n")
    print("## Proactive compared with reactive\n\n" + difference_table(profiles, results) + "\n")
    print("## Where the controllers put the CPU (CPU limit, cores)\n\n" + limits_table(profiles))


if __name__ == "__main__":
    main()
