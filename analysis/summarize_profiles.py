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

A second block of tables compares the two sine runs, with the workers'
waves 20 s apart (2 October) and 60 s apart (sine profile), with the others.

A third block is the prediction-off test on the sine profile: reactive,
proactive_nopred (proactive with --predict-ahead 0) and proactive, plus one
reactive and one proactive run from the same session as proactive_nopred.

Usage:  python analysis/summarize_profiles.py
"""
import cmath
import csv
import math
import os
import re
import statistics
from datetime import datetime

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
WORKERS = ["fl-worker-1", "fl-worker-2"]
BUDGET = 1.0   # CPU shared by both workers
PERIOD = 120   # seconds per wave in the sine loads

# name: (comparison.md, folder with runs.csv, worker logs)
PROFILES = {
    # 2 October runs, before load profiles existed: the old built-in sine.
    # Their worker logs only survive in the backups made on 2026-10-04.
    "sine": ("results/comparison.md", "data/runs", "data/worker_logs/{worker}_until_2026-10-04.log"),
    "bursts": ("results/bursts/comparison.md", "data/runs/bursts",
               "data/runs/bursts/{run}_{worker}.log"),
    "noisy_sine": ("results/noisy_sine/comparison.md", "data/runs/noisy_sine",
                   "data/runs/noisy_sine/{run}_{worker}.log"),
    # The sine profile (load/profiles/sine.json): waves half a period apart.
    "sine_60s": ("results/sine/comparison.md", "data/runs/sine", "data/runs/sine/{run}_{worker}.log"),
    # The same profile some hours later: 3 runs without prediction (proactive_nopred)
    # and, in between, 1 reactive and 1 proactive run to check the session.
    "sine_ablation": ("results/sine_ablation/comparison.md", "data/runs/sine_ablation",
                      "data/runs/sine_ablation/{run}_{worker}.log"),
}
# The first tables keep the names above; the sine comparison uses clearer ones.
FIRST_TABLES = ["sine", "bursts", "noisy_sine"]
OFFSET_TABLES = {"sine": "sine, 20 s apart (2 Oct)", "sine_60s": "sine, 60 s apart",
                 "noisy_sine": "noisy_sine", "bursts": "bursts"}
# The prediction-off test: (label, profile, controller), in the order of the steps.
ABLATION = [("reactive", "sine_60s", "reactive"),
            ("proactive_nopred", "sine_ablation", "proactive_nopred"),
            ("proactive", "sine_60s", "proactive")]
SAME_SESSION = [("reactive, same session", "sine_ablation", "reactive"),
                ("proactive, same session", "sine_ablation", "proactive")]
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
    every_second, every_10s = {}, {}
    for line in open(path):
        new, old = NEW_LINE.match(line), OLD_LINE.match(line)
        if new and start <= stamp(new.group(1)) <= end:
            every_second[int(new.group(2))] = (stamp(new.group(1)), float(new.group(3)))
        elif old and start <= stamp(old.group(1)) <= end:
            every_10s[round(stamp(old.group(1)) / 10)] = (stamp(old.group(1)), float(old.group(2)))
    # New logs also have a training-speed line every 10 s that looks like the
    # old format, so the 10 s lines are only used for old logs (nothing else there).
    return every_second or every_10s


def load_pairs(profile):
    """Intended load of both workers at the same moments, as pairs (worker 1, worker 2)."""
    pairs = []
    for row in runs_of(profile):
        w1, w2 = (intended_load(profile, row, w) for w in WORKERS)
        pairs += [(w1[k][1], w2[k][1]) for k in sorted(w1) if k in w2]
    return pairs


def decisions_of(row):
    """{worker: [(time, new limit), ...]}: the decisions in one run's controller CSV."""
    decisions = {w: [] for w in WORKERS}
    for d in csv.DictReader(open(os.path.join(ROOT, row["csv"]))):
        decisions[d["worker"]].append((datetime.fromisoformat(d["timestamp"]).timestamp(),
                                       float(d["new_limit"])))
    return decisions


def limit_at(decisions, t):
    """The limit in force at time t: it holds until the controller's next decision."""
    before = [limit for when, limit in decisions if when <= t]
    return before[-1] if before else 0.5    # runs start at 0.5 CPU each


def limit_while(profile, controller):
    """
    How the controller handed out CPU: the average total of both limits, and
    a worker's average limit while it was busy (load >= 0.7) and while it was
    almost idle (load <= 0.3).
    """
    busy, idle, totals = [], [], []
    for row in runs_of(profile):
        if row["controller"] != controller:
            continue
        decisions = decisions_of(row)
        for w in WORKERS:
            for t, load in intended_load(profile, row, w).values():
                limit = limit_at(decisions[w], t)
                if load >= 0.7:
                    busy.append(limit)
                elif load <= 0.3:
                    idle.append(limit)
        totals += [a + b for (_, a), (_, b) in zip(*decisions.values())]
    return statistics.mean(totals), statistics.mean(busy), statistics.mean(idle)


def wave_shift(samples):
    """
    Where a worker's wave sits in time. Its load is about
    mean + amplitude * sin(2 * pi * (t - shift) / PERIOD). Multiplying the load
    by a 120 s wave and adding it all up (one Fourier coefficient) gives `shift`.
    """
    mean = statistics.mean(load for _, load in samples)
    z = sum((load - mean) * cmath.exp(-2j * math.pi * t / PERIOD) for t, load in samples)
    return -cmath.phase(z * 1j) * PERIOD / (2 * math.pi)


def wave_offset(profile, row):
    """Seconds between the two workers' waves in one run (0 = together, 60 = half a period)."""
    shift_1, shift_2 = (wave_shift(list(intended_load(profile, row, w).values()))
                        for w in WORKERS)
    offset = (shift_2 - shift_1) % PERIOD
    return min(offset, PERIOD - offset)   # how far apart, whichever worker is ahead


def wave_size(samples):
    """Half the swing of the 2-minute wave in the samples (the same sum as wave_shift)."""
    mean = statistics.mean(value for _, value in samples)
    z = sum((value - mean) * cmath.exp(-2j * math.pi * t / PERIOD) for t, value in samples)
    return 2 * abs(z) / len(samples)


def limit_delay(profile, controller):
    """
    How many seconds a worker's CPU limit trails its load, on average over the
    runs and both workers: the shift of the limit's 2-minute wave minus the
    shift of the load's wave. Also returns the size of the limit's wave
    (wave_size), because a limit that hardly moves has no clear shift.
    """
    delays, sizes = [], []
    for row in runs_of(profile):
        if row["controller"] != controller:
            continue
        decisions = decisions_of(row)
        for w in WORKERS:
            load = list(intended_load(profile, row, w).values())
            limits = [(t, limit_at(decisions[w], t)) for t, _ in load]
            delay = (wave_shift(limits) - wave_shift(load)) % PERIOD
            delays.append((delay + PERIOD / 2) % PERIOD - PERIOD / 2)   # between -60 and +60 s
            sizes.append(wave_size(limits))
    return statistics.mean(delays), statistics.mean(sizes)


def overlaps(reactive, proactive):
    """Do the two controllers' runs overlap? Yes if the lowest top is above the highest bottom."""
    return max(min(reactive), min(proactive)) <= min(max(reactive), max(proactive))


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


def limits_table(profiles, labels=None):
    lines = ["| Profile | Controller | Both limits together | Limit while busy | Limit while idle |",
             "|---|---|---:|---:|---:|"]
    for p in profiles:
        for c in ("reactive", "proactive"):
            total, busy, idle = limit_while(p, c)
            lines.append(f"| {labels[p] if labels else p} | {c} | {total:.2f} | {busy:.2f} | {idle:.2f} |")
    return "\n".join(lines)


def offset_load_table(profiles, labels):
    """The loads of the sine comparison, with the measured distance between the two waves."""
    lines = ["| Load | Waves apart (s) | Correlation of the two loads | Total load | "
             "Time total is above 1.0 CPU |",
             "|---|---:|---:|---:|---:|"]
    for p in profiles:
        pairs = load_pairs(p)
        total = [a + b for a, b in pairs]
        over = sum(t > BUDGET for t in total) / len(total)
        if "sine" in p:   # only the wave loads have an offset; range over the runs
            offsets = [wave_offset(p, row) for row in runs_of(p)]
            apart = f"{min(offsets):.1f} to {max(offsets):.1f}"
        else:
            apart = "-"
        lines.append(f"| {labels[p]} | {apart} | "
                     f"{statistics.correlation([a for a, _ in pairs], [b for _, b in pairs]):+.2f} | "
                     f"{statistics.mean(total):.2f} ({min(total):.2f} to {max(total):.2f}) | {over:.0%} |")
    return "\n".join(lines)


def offset_results_table(profiles, results, labels):
    """Training speed of both controllers and the proactive minus reactive differences."""
    speed = METRICS[0][0]
    lines = ["| Load | Training speed, reactive | Training speed, proactive | Speed difference | "
             "CPU used difference | Unmet demand difference | Runs overlap? |",
             "|---|---:|---:|---:|---:|---:|---|"]
    for p in profiles:
        totals, diffs, runs = results[p]
        overlapping = [title for column, title, _, _ in METRICS
                       if overlaps(runs["reactive"][column], runs["proactive"][column])]
        verdict = "yes: " + ", ".join(overlapping) if overlapping else "no"
        lines.append(f"| {labels[p]} | {totals['reactive'][speed]} | {totals['proactive'][speed]} | "
                     + " | ".join(diffs[column] for column, _, _, _ in METRICS) + f" | {verdict} |")
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
            better = (float(diffs[column].split()[0]) > 0) == higher_is_better
            verdict = "yes" if overlaps(r, a) else ("no, proactive better" if better else "no, reactive better")
            fmt = lambda v: f"{v:.{digits}f}"
            lines.append(f"| {p} | {title} | {fmt(min(r))} to {fmt(max(r))} | "
                         f"{fmt(min(a))} to {fmt(max(a))} | {diffs[column]} | {verdict} |")
    return "\n".join(lines)


# ----------------------------------------------------------------------
# 4. The prediction-off test (sine profile, waves 60 s apart)
# ----------------------------------------------------------------------
def mean_of(text):
    """'322.9 ± 3.8' -> 322.9"""
    return float(text.split(" ± ")[0])


def session(profile, controller):
    """When these runs happened, e.g. '00:06 to 01:12'."""
    rows = [row for row in runs_of(profile) if row["controller"] == controller]
    first = min(datetime.fromisoformat(row["start"]) for row in rows)
    last = max(datetime.fromisoformat(row["end"]) for row in rows)
    return f"{first:%H:%M} to {last:%H:%M}"


def ablation_table(results):
    """Reactive, proactive without prediction and proactive: mean ± sd, then every run."""
    lines = ["| Controller | Runs on 5 Oct | " + " | ".join(t for _, t, _, _ in METRICS) + " |",
             "|---|---|" + "---:|" * len(METRICS)]
    for label, profile, controller in ABLATION:
        totals, _, runs = results[profile]
        cells = [f"{totals[controller][column]} "
                 f"({', '.join(f'{value:.{digits}f}' for value in runs[controller][column])})"
                 for column, _, digits, _ in METRICS]
        lines.append(f"| {label} | {session(profile, controller)} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def steps_table(results):
    """
    What each step adds: from reactive to the full-budget split without
    prediction, and from there to the split with prediction. "Runs overlap?"
    as in the other tables, between the runs of the two ends of a step.
    """
    (_, p_reactive, reactive), (_, p_nopred, nopred), (_, p_proactive, proactive) = ABLATION
    steps = [("reactive to proactive_nopred", (p_reactive, reactive), (p_nopred, nopred)),
             ("proactive_nopred to proactive", (p_nopred, nopred), (p_proactive, proactive)),
             ("reactive to proactive", (p_reactive, reactive), (p_proactive, proactive))]
    lines = ["| Step | " + " | ".join(t for _, t, _, _ in METRICS) + " | Runs overlap? |",
             "|---|" + "---:|" * len(METRICS) + "---|"]
    for name, (profile_a, a), (profile_b, b) in steps:
        cells, overlapping = [], []
        for column, title, digits, _ in METRICS:
            mean_a = mean_of(results[profile_a][0][a][column])
            mean_b = mean_of(results[profile_b][0][b][column])
            cells.append(f"{mean_b - mean_a:+.{digits}f} ({(mean_b - mean_a) / mean_a:+.0%})")
            if overlaps(results[profile_a][2][a][column], results[profile_b][2][b][column]):
                overlapping.append(title)
        verdict = "yes: " + ", ".join(overlapping) if overlapping else "no"
        lines.append(f"| {name} | " + " | ".join(cells) + f" | {verdict} |")
    return "\n".join(lines)


def gain_share(results):
    """
    How much of proactive's gain over reactive proactive_nopred already
    reaches: once against the earlier 3 + 3 runs, once against the reactive
    and proactive run of its own session.
    """
    (_, p_reactive, reactive), (_, p_nopred, nopred), (_, p_proactive, proactive) = ABLATION
    baselines = [("the earlier runs (3 reactive, 3 proactive)", p_reactive, p_proactive),
                 ("the same-session runs (1 reactive, 1 proactive)", "sine_ablation", "sine_ablation")]
    lines = ["| Share of proactive's gain reached without prediction, against | "
             + " | ".join(t for _, t, _, _ in METRICS) + " |",
             "|---|" + "---:|" * len(METRICS)]
    for name, profile_r, profile_p in baselines:
        cells = []
        for column, _, _, _ in METRICS:
            r = mean_of(results[profile_r][0][reactive][column])
            n = mean_of(results[p_nopred][0][nopred][column])
            p = mean_of(results[profile_p][0][proactive][column])
            cells.append(f"{(n - r) / (p - r):.0%}")
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def same_session_table(results):
    """The one reactive and one proactive run of the new session against the 3 earlier runs."""
    lines = ["| Controller | Metric | Earlier session, 3 runs | This session, 1 run | "
             "Difference to the earlier mean |",
             "|---|---|---:|---:|---:|"]
    for _, profile, controller in SAME_SESSION:
        earlier_mean = results["sine_60s"][0][controller]
        earlier_runs = results["sine_60s"][2][controller]
        for column, title, digits, _ in METRICS:
            value = results[profile][2][controller][column][0]
            mean = mean_of(earlier_mean[column])
            fmt = lambda v: f"{v:.{digits}f}"
            lines.append(f"| {controller} | {title} | {fmt(min(earlier_runs[column]))} to "
                         f"{fmt(max(earlier_runs[column]))} | {fmt(value)} | "
                         f"{value - mean:+.{digits}f} ({(value - mean) / mean:+.1%}) |")
    return "\n".join(lines)


def ablation_limits_table():
    """Where each controller put the CPU, and how far its limits trail the load."""
    lines = ["| Controller | Both limits together | Limit while busy | Limit while idle | "
             "Size of the limit's wave | Limit trails the load by |",
             "|---|---:|---:|---:|---:|---:|"]
    for label, profile, controller in ABLATION + SAME_SESSION:
        total, busy, idle = limit_while(profile, controller)
        delay, size = limit_delay(profile, controller)
        trails = f"{delay:.0f} s" if size >= 0.1 else "-"   # a limit that hardly moves has no clear delay
        lines.append(f"| {label} | {total:.2f} | {busy:.2f} | {idle:.2f} | {size:.2f} | {trails} |")
    return "\n".join(lines)


def main():
    available = [p for p, (path, _, _) in PROFILES.items() if os.path.exists(os.path.join(ROOT, path))]
    missing = [p for p in PROFILES if p not in available]
    if missing:
        print(f"(no results yet for: {', '.join(missing)})\n")
    results = {p: read_results(PROFILES[p][0]) for p in available}

    first = [p for p in FIRST_TABLES if p in available]
    print("## Load per profile\n\n" + load_table(first) + "\n")
    print("## Results (mean ± sd over 3 runs each)\n\n" + results_table(first, results) + "\n")
    print("## Proactive compared with reactive\n\n" + difference_table(first, results) + "\n")
    print("## Where the controllers put the CPU (CPU limit, cores)\n\n" + limits_table(first))

    if "sine_60s" in available:
        second = [p for p in OFFSET_TABLES if p in available]
        print("\n## Sine with the waves 20 s apart vs 60 s apart\n")
        print("### Load\n\n" + offset_load_table(second, OFFSET_TABLES) + "\n")
        print("### Proactive compared with reactive\n\n"
              + offset_results_table(second, results, OFFSET_TABLES) + "\n")
        print("### Where the controllers put the CPU (CPU limit, cores)\n\n"
              + limits_table(second, OFFSET_TABLES))

    if "sine_ablation" in available and "sine_60s" in available:
        print("\n## Prediction on or off (sine, waves 60 s apart)\n")
        offsets = [wave_offset("sine_ablation", row) for row in runs_of("sine_ablation")]
        print(f"Waves apart in the new runs: {min(offsets):.1f} to {max(offsets):.1f} s\n")
        print("### Results (totals of both workers)\n\n" + ablation_table(results) + "\n")
        print("### What each step adds\n\n" + steps_table(results) + "\n\n" + gain_share(results) + "\n")
        print("### Same session check\n\n" + same_session_table(results) + "\n")
        print("### Where the controllers put the CPU (CPU limit, cores)\n\n" + ablation_limits_table())


if __name__ == "__main__":
    main()
