"""
Random windows: does proactive's gain over reactive hold across other parts
of the load, not just the one segment the experiments used so far?

scripts/run_experiments.py starts the profile at t = 0 for every run, so all
runs saw the same segment (t = 60-660 s, after the 60 s warm-up). Here every
load profile gets N windows, each starting at its own random offset into the
profile. The offsets come from --seed, so the same command gives the same
windows. In each window reactive and proactive run on exactly the same load
(paired), and the order alternates from window to window (reactive first in
window 1, proactive first in window 2, ...), so slow drift of the machine
affects both equally.

Each run is one run of run_experiments.py (run_one): reset both workers to
0.5 CPU, start the profile at t = offset, warm up, run the controller, save
its CSV and the workers' logs. A run's number is its window: reactive_3.csv
and proactive_3.csv are window 3.

Output per profile in data/runs/random_windows/<profile>/ (git-ignored):
    windows.csv   profile, window, offset_s, seed, first (written before the runs)
    runs.csv, runner.log and per run <controller>_<window>.csv, _output.txt
    and _fl-worker-N.log, as with run_experiments.py
Analyse with analysis/random_windows.py.

Full experiment in the background (3 profiles x 10 windows x 2 runs of 11 min, about 11 h):
    mkdir -p data/runs/random_windows
    nohup .venv/bin/python scripts/run_random_windows.py > /dev/null 2>> data/runs/random_windows/runner.err &

Watch progress:          tail -f data/runs/random_windows/*/runner.log
Stop early (cleanly):    kill $(cat data/runs/random_windows/runner.pid)

Short test run:
    python scripts/run_random_windows.py --profiles bursts --windows 2 --minutes 1 --warmup 20 --out-dir data/runs_test/random_windows
"""
import argparse
import csv
import os
import random
import signal
import sys
from datetime import datetime, timedelta

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import run_experiments as rx  # noqa: E402  (scripts/run_experiments.py)

PROFILES = ["sine", "noisy_sine", "bursts"]
CONTROLLERS = ["reactive", "proactive"]
WINDOWS_COLUMNS = ["profile", "window", "offset_s", "seed", "first"]


# ----------------------------------------------------------------------
# The windows
# ----------------------------------------------------------------------
def draw_offsets(seed, profile, count, max_offset):
    """
    `count` whole-second offsets from 0 to max_offset - 1. The random generator
    is made from the seed and the profile name, so each profile gets its own
    offsets and the same seed always gives the same ones.
    """
    rng = random.Random(f"{seed}-{profile}")
    return [rng.randrange(max_offset) for _ in range(count)]


def window_order(window):
    """Run order inside a window: reactive first in odd windows, proactive first in even ones."""
    return CONTROLLERS if window % 2 == 1 else CONTROLLERS[::-1]


def write_windows(path, profile, offsets, seed):
    """Save the windows of one profile, before any run starts."""
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=WINDOWS_COLUMNS)
        writer.writeheader()
        for window, offset in enumerate(offsets, start=1):
            writer.writerow({"profile": profile, "window": window, "offset_s": offset,
                             "seed": seed, "first": window_order(window)[0]})


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Paired reactive/proactive runs on random windows.")
    parser.add_argument("--profiles", type=lambda text: text.split(","), default=PROFILES,
                        help=f"comma-separated (default {','.join(PROFILES)})")
    parser.add_argument("--windows", type=int, default=10, help="windows per profile (default 10)")
    parser.add_argument("--seed", type=int, default=1, help="seed of the offsets (default 1)")
    parser.add_argument("--max-offset", type=int, default=3600,
                        help="offsets are drawn from 0 to this many seconds (default 3600)")
    parser.add_argument("--minutes", type=float, default=10, help="length of each run (default 10)")
    parser.add_argument("--warmup", type=int, default=60, help="seconds at 0.5/0.5 before each run")
    parser.add_argument("--out-dir", default=os.path.join(ROOT, "data", "runs", "random_windows"),
                        help="results go to <out-dir>/<profile>/")
    args = parser.parse_args()

    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    rx.LOG_PATH = os.path.join(out_dir, "runner.log")

    # As in run_experiments.py: Ctrl+C and `kill` stop the running controller cleanly.
    signal.signal(signal.SIGINT, signal.default_int_handler)
    signal.signal(signal.SIGTERM, rx.stop_on_sigterm)

    # Check every profile before the first run, so a problem shows up now and
    # not hours later. Also refuse if another runner is still going.
    problems = []
    pid_file = os.path.join(out_dir, "runner.pid")
    if os.path.exists(pid_file):
        try:
            os.kill(int(open(pid_file).read()), 0)
            problems.append(f"another runner is still running (pid in {pid_file}).")
        except (OSError, ValueError):
            pass
    for profile in args.profiles:
        profile_dir = os.path.join(out_dir, profile)
        os.makedirs(profile_dir, exist_ok=True)
        problems += [f"{profile}: {p}" for p in rx.preflight(profile_dir, profile, CONTROLLERS)]
    if problems:
        for problem in problems:
            rx.log(f"cannot start: {problem}")
        sys.exit(1)

    # The control page sees this file (any runner.pid under data/runs/) and
    # refuses load changes while the runs go on.
    with open(pid_file, "w") as f:
        f.write(str(os.getpid()))

    run_seconds = round(args.minutes * 60)
    runs_total = len(args.profiles) * args.windows * len(CONTROLLERS)
    total = runs_total * (args.warmup + run_seconds)
    finish = datetime.now() + timedelta(seconds=total)
    rx.log(f"starting {runs_total} runs: {args.windows} random windows (seed {args.seed}, "
           f"offsets 0-{args.max_offset} s) x {', '.join(CONTROLLERS)} for "
           f"{', '.join(args.profiles)}, {args.minutes:g} min each after {args.warmup} s "
           f"warm-up. About {total / 3600:.1f} h, done around {finish:%a %H:%M}. pid {os.getpid()}")

    ok = 0
    try:
        for profile in args.profiles:
            profile_dir = os.path.join(out_dir, profile)
            offsets = draw_offsets(args.seed, profile, args.windows, args.max_offset)
            write_windows(os.path.join(profile_dir, "windows.csv"), profile, offsets, args.seed)
            rx.LOG_PATH = os.path.join(profile_dir, "runner.log")
            rx.log(f"profile {profile!r}: offsets {offsets} (seed {args.seed})")
            run = 0
            for window, offset in enumerate(offsets, start=1):
                for controller in window_order(window):
                    run += 1
                    row = rx.run_one(run, controller, window, profile, args.warmup,
                                     run_seconds, profile_dir, offset=offset)
                    ok += row["status"] == "ok"
    except KeyboardInterrupt:
        rx.log("stopped by user before all runs were done")
    finally:
        rx.reset_workers()
        rx.log(f"workers reset to {rx.START_LIMIT} CPU")
        os.remove(pid_file)

    rx.LOG_PATH = os.path.join(out_dir, "runner.log")
    rx.log(f"finished: {ok} of {runs_total} runs ok. Analyse with "
           f"analysis/random_windows.py --runs-dir {os.path.relpath(out_dir, ROOT)}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Under nohup nobody sees the screen, so put crashes in the log too.
        import traceback
        if rx.LOG_PATH:
            rx.log("runner crashed:\n" + traceback.format_exc())
        raise
