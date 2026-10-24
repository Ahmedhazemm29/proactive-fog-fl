"""
Copy the FL aggregator's run data from the Pi to data/fl-runs/ on the laptop.

    python3 pi/pull_runs.py

pi/deploy.sh calls it before every deploy, so no run is only on the Pi when a
new one starts, and with --wait again when the new run has finished.

Read-only on the Pi: rsync only reads there and never deletes anything.
On the Pi (~/fog/pi/fl-data/):
    <run>/rounds.csv, updates.csv    one folder per run (since join/leave)
    rounds.csv, updates.csv          the runs before that, all in one pair of files
On the laptop (data/fl-runs/ of the main checkout, git-ignored):
    .pi-mirror/                      an exact copy of the Pi's folder
    <date>_<run>/rounds.csv, updates.csv
    <date>_<run>/control.csv         the run's join/leave commands from
                                     hardware/tools/fl_control.py, also those
                                     sent before the run started
A run folder's rounds.csv and updates.csv are copied again on every pull while
they grow. Runs split out of the old shared files are written once and never
overwritten.
"""
import argparse
import csv
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PI_DATA = "pi5@fognode1.local:fog/pi/fl-data/"
HERE = Path(__file__).resolve().parent


def default_runs_dir():
    """data/fl-runs of the main checkout, also from a git worktree (as in fl_control.py)."""
    try:
        common = subprocess.run(["git", "-C", str(HERE), "rev-parse", "--path-format=absolute",
                                 "--git-common-dir"], capture_output=True, text=True, check=True)
        return Path(common.stdout.strip()).parent / "data" / "fl-runs"
    except (OSError, subprocess.CalledProcessError):
        return HERE.parent / "data" / "fl-runs"


def run_folder_name(run):
    """<date>_<run>, the date of the run's start (the run ID is its start time)."""
    return f"{datetime.fromtimestamp(int(run)):%Y-%m-%d}_{run}"


def run_of_folder(folder):
    """The run ID of a run folder such as 2026-10-23_1792772831, or None."""
    last = folder.name.rsplit("_", 1)[-1]
    return int(last) if folder.is_dir() and "_" in folder.name and last.isdigit() else None


# ----------------------------------------------------------------------
# Steps
# ----------------------------------------------------------------------
def mirror(source, mirror_dir):
    """Copy the Pi's fl-data folder into mirror_dir with rsync (it only reads on the Pi)."""
    mirror_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["rsync", "-a", source, f"{mirror_dir}/"], check=True)


def organize(mirror_dir, runs_dir):
    """One folder per run in runs_dir, from the mirror. Returns {run: what was done}."""
    done = {}
    # One folder per run on the Pi: copy its files again, they grow while the run goes on
    for folder in sorted(mirror_dir.iterdir()):
        if folder.is_dir() and folder.name.isdigit():
            target = runs_dir / run_folder_name(folder.name)
            target.mkdir(parents=True, exist_ok=True)
            for name in ("rounds.csv", "updates.csv"):
                if (folder / name).exists():
                    shutil.copy2(folder / name, target / name)
            done[folder.name] = "copied"

    # The old shared files: split them by run; write each run's file once, never overwrite
    for name in ("rounds.csv", "updates.csv"):
        path = mirror_dir / name
        if not path.exists():
            continue
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            by_run = {}
            for row in reader:
                by_run.setdefault(row["run"], []).append(row)
            fields = reader.fieldnames
        for run, rows in by_run.items():
            target = runs_dir / run_folder_name(run) / name
            if target.exists():
                done.setdefault(run, "already there, kept as it is")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            done[run] = "split from the shared files"
    return done


def last_round_time(folder):
    """
    Epoch time of the run's last round in its rounds.csv, or None without
    rounds. The aggregator writes the time in UTC (the container's clock).
    """
    path = folder / "rounds.csv"
    if not path.exists():
        return None
    with open(path, newline="") as f:
        times = [row.get("time", "") for row in csv.DictReader(f)]
    try:
        last = datetime.fromisoformat(times[-1]).replace(tzinfo=timezone.utc)
    except (IndexError, ValueError):
        return None
    return last.timestamp()


def run_of_command(row, starts, ends):
    """
    The run a command belongs to. Its "run" column if fl_control.py knew the
    run. Otherwise (no global model yet: the run was still waiting for its
    first clients, or no run at all) the run going on at that time: started
    before the command and had a round at or after it. Else the next run that
    started after it, or None if there is none yet. A run without rounds never
    claims a command: it was replaced before its joins took effect.
    """
    if row["run"]:
        return int(row["run"])
    epoch = float(row["epoch"])
    for start in starts:
        if start <= epoch and ends.get(start) is not None and epoch <= ends[start]:
            return start
    return next((start for start in starts if start >= epoch), None)


def assign_commands(runs_dir):
    """
    Write each run folder's control.csv from data/fl-runs/control.csv, the log
    of hardware/tools/fl_control.py (see run_of_command for which run a
    command belongs to). Returns {run: number of commands}.
    """
    log = runs_dir / "control.csv"
    if not log.exists():
        return {}
    with open(log, newline="") as f:
        reader = csv.DictReader(f)
        rows, fields = list(reader), reader.fieldnames
    folders = {run_of_folder(folder): folder for folder in runs_dir.iterdir()}
    starts = sorted(run for run in folders if run is not None)
    ends = {run: last_round_time(folders[run]) for run in starts}
    per_run = {}
    for row in rows:
        run = run_of_command(row, starts, ends)
        if run is not None:
            per_run.setdefault(run, []).append(row)   # None: the run hasn't started yet
    counts = {}
    for run, run_rows in per_run.items():
        target = runs_dir / run_folder_name(run) / "control.csv"
        if not target.parent.exists():
            continue                                  # the run's data isn't here yet
        with open(target, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(run_rows)
        counts[run] = len(run_rows)
    return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description="Copy the FL run data from the Pi to data/fl-runs/.")
    parser.add_argument("--source", default=PI_DATA, help=f"rsync source (default {PI_DATA})")
    parser.add_argument("--data", type=Path, default=None,
                        help="target folder (default data/fl-runs of the main checkout)")
    args = parser.parse_args(argv)
    runs_dir = args.data or default_runs_dir()
    mirror_dir = runs_dir / ".pi-mirror"

    try:
        mirror(args.source, mirror_dir)
    except (OSError, subprocess.CalledProcessError) as error:
        sys.exit(f"pull_runs: could not copy {args.source} ({error})")
    done = organize(mirror_dir, runs_dir)
    commands = assign_commands(runs_dir)

    if not done:
        print(f"pull_runs: no runs in {args.source} yet")
    for run, what in sorted(done.items()):
        print(f"pull_runs: run {run}: {what} ({runs_dir / run_folder_name(run)})")
    for run, count in sorted(commands.items()):
        print(f"pull_runs: run {run}: {count} join/leave command(s) in control.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
