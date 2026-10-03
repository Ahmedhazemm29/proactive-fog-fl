"""
Experiment runner: repeat the reactive vs proactive comparison.

For every run, alternating reactive, proactive, reactive, ... so that slow
drift (other load on the machine, temperature, ...) affects both equally:
    1. reset both workers to START_LIMIT CPU and wait for the warm-up
    2. start the controller as a subprocess and let it run
    3. stop it with SIGINT, the same signal Ctrl+C sends, so it exits cleanly
    4. move its CSV log to <out-dir>/<controller>_<n>.csv and add a row
       to <out-dir>/runs.csv

Full experiment in the background (keeps running if the terminal closes):
    mkdir -p data/runs
    nohup .venv/bin/python scripts/run_experiments.py > /dev/null 2>> data/runs/runner.log &

Watch progress:            tail -f data/runs/runner.log
Stop early (cleanly):      kill $(cat data/runs/runner.pid)

Short test run:
    python scripts/run_experiments.py --repeats 2 --minutes 1 --warmup 20 --out-dir data/runs_test
"""
import argparse
import csv
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta

import requests

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "controller"))
from reactive import PROMETHEUS_URL, WORKERS  # noqa: E402
from set_cpu import set_cpus  # noqa: E402


# ----------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------
CONTROLLERS = ["reactive", "proactive"]  # run order inside each repeat
START_LIMIT = 0.5          # CPU per worker at the start of every run
STOP_TIMEOUT_SECONDS = 20  # how long a controller gets to exit after SIGINT
RUNS_COLUMNS = ["run", "controller", "repeat", "start", "end", "duration_s", "csv", "status"]


def controller_script(name):
    return os.path.join(ROOT, "controller", f"{name}.py")


def controller_log(name):
    """Where the controller itself writes its CSV (its LOG_FILE)."""
    return os.path.join(ROOT, "data", f"{name}_log.csv")


# ----------------------------------------------------------------------
# Logging: every message goes to the screen and to runner.log
# ----------------------------------------------------------------------
LOG_PATH = None


def log(message):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}"
    print(line, flush=True)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


def now_iso():
    """Local time with its UTC offset, e.g. 2026-10-02T21:30:00+03:00."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


# ----------------------------------------------------------------------
# Checks before starting
# ----------------------------------------------------------------------
def preflight(out_dir):
    """Return a list of problems. The experiment only starts if it is empty."""
    problems = []
    pid_file = os.path.join(out_dir, "runner.pid")
    if os.path.exists(pid_file):
        try:
            os.kill(int(open(pid_file).read()), 0)  # signal 0 only checks it exists
            problems.append(f"another runner is still running (pid in {pid_file}).")
        except (OSError, ValueError):
            pass  # left over from a runner that is gone
    if os.path.exists(os.path.join(out_dir, "runs.csv")):
        problems.append(f"{out_dir}/runs.csv already exists. Use another --out-dir "
                        "or move the old runs away.")
    for name in CONTROLLERS:
        if os.path.exists(controller_log(name)):
            problems.append(f"{controller_log(name)} exists. The controller would append "
                            "to it, so move it away first (for example into data/old/).")
    # Another controller changing the limits would spoil every run.
    found = subprocess.run(["pgrep", "-af", r"controller/(reactive|proactive)\.py"],
                           capture_output=True, text=True).stdout.strip()
    if found:
        problems.append(f"a controller is already running:\n{found}")
    try:
        requests.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": "up"},
                     timeout=5).raise_for_status()
    except requests.RequestException as error:
        problems.append(f"Prometheus is not reachable at {PROMETHEUS_URL}: {error}")
    return problems


# ----------------------------------------------------------------------
# One run
# ----------------------------------------------------------------------
def reset_workers():
    for worker in WORKERS:
        set_cpus(worker, START_LIMIT)


def run_one(run, controller, repeat, warmup, run_seconds, out_dir):
    """Warm up, run one controller, stop it, file its CSV. Returns its runs.csv row."""
    log(f"run {run}: {controller} #{repeat}. Workers reset to {START_LIMIT} CPU, "
        f"warming up for {warmup} s")
    reset_workers()
    time.sleep(warmup)

    output_path = os.path.join(out_dir, f"{controller}_{repeat}_output.txt")
    start = now_iso()
    # -u: unbuffered, so the controller's printout reaches the file right away.
    with open(output_path, "w") as output:
        process = subprocess.Popen([sys.executable, "-u", controller_script(controller)],
                                   cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
    log(f"run {run}: {controller} started (pid {process.pid}), running {run_seconds / 60:g} min")

    status = "ok"
    interrupted = False
    try:
        # Wait, but notice if the controller dies early. Report every minute.
        deadline = time.time() + run_seconds
        next_report = time.time() + 60
        while time.time() < deadline:
            if process.poll() is not None:
                status = f"exited early with code {process.returncode}"
                log(f"run {run}: {controller} {status}, see {output_path}")
                break
            if time.time() >= next_report:
                minutes_left = (deadline - time.time()) / 60
                log(f"run {run}: {controller} running, {minutes_left:.0f} min left")
                next_report += 60
            time.sleep(1)
    except KeyboardInterrupt:
        interrupted = True
        status = "interrupted"

    # Stop it the way Ctrl+C would, so it finishes its current step and exits.
    end = now_iso()
    if process.poll() is None:
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=STOP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            log(f"run {run}: {controller} ignored SIGINT, terminating it")
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            if status == "ok":
                status = "had to be terminated"

    # File the controller's CSV under its run name.
    target = os.path.join(out_dir, f"{controller}_{repeat}.csv")
    if os.path.exists(controller_log(controller)):
        os.replace(controller_log(controller), target)
        with open(target) as f:
            rows = sum(1 for _ in f) - 1
        log(f"run {run}: {controller} stopped ({status}), {rows} CSV rows saved to "
            f"{os.path.relpath(target, ROOT)}")
    else:
        status = f"{status}, no CSV written"
        log(f"run {run}: {controller} stopped ({status})")

    row = {"run": run, "controller": controller, "repeat": repeat, "start": start,
           "end": end, "csv": os.path.relpath(target, ROOT), "status": status,
           "duration_s": round((datetime.fromisoformat(end)
                                - datetime.fromisoformat(start)).total_seconds())}
    runs_csv = os.path.join(out_dir, "runs.csv")
    is_new = not os.path.exists(runs_csv)
    with open(runs_csv, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RUNS_COLUMNS)
        if is_new:
            writer.writeheader()
        writer.writerow(row)

    if interrupted:
        raise KeyboardInterrupt
    return row


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def stop_on_sigterm(signum, frame):
    """Treat `kill <pid>` like Ctrl+C, so the running controller is stopped too."""
    raise KeyboardInterrupt


def main():
    global LOG_PATH
    parser = argparse.ArgumentParser(description="Repeat the reactive vs proactive runs.")
    parser.add_argument("--repeats", type=int, default=3, help="runs per controller (default 3)")
    parser.add_argument("--minutes", type=float, default=10, help="length of each run (default 10)")
    parser.add_argument("--warmup", type=int, default=60, help="seconds at 0.5/0.5 before each run")
    parser.add_argument("--out-dir", default=os.path.join(ROOT, "data", "runs"))
    args = parser.parse_args()

    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    LOG_PATH = os.path.join(out_dir, "runner.log")

    # When started in the background (nohup ... &) the shell makes this process
    # ignore Ctrl+C, and the controllers would inherit that and ignore our SIGINT.
    # Installing handlers here gives the controllers the normal Ctrl+C behavior.
    signal.signal(signal.SIGINT, signal.default_int_handler)
    signal.signal(signal.SIGTERM, stop_on_sigterm)

    problems = preflight(out_dir)
    if problems:
        for problem in problems:
            log(f"cannot start: {problem}")
        sys.exit(1)

    # Remember our pid, so the run can be stopped with: kill $(cat <out-dir>/runner.pid)
    pid_file = os.path.join(out_dir, "runner.pid")
    with open(pid_file, "w") as f:
        f.write(str(os.getpid()))

    plan = [(controller, repeat) for repeat in range(1, args.repeats + 1)
            for controller in CONTROLLERS]
    run_seconds = round(args.minutes * 60)
    total = len(plan) * (args.warmup + run_seconds)
    finish = datetime.now() + timedelta(seconds=total)
    log(f"starting {len(plan)} runs ({args.repeats} x {', '.join(CONTROLLERS)}), "
        f"{args.minutes:g} min each after {args.warmup} s warm-up. "
        f"About {total / 60:.0f} min, done around {finish:%H:%M}. pid {os.getpid()}")

    results = []
    try:
        for run, (controller, repeat) in enumerate(plan, start=1):
            results.append(run_one(run, controller, repeat, args.warmup, run_seconds, out_dir))
    except KeyboardInterrupt:
        log("stopped by user before all runs were done")
    finally:
        reset_workers()
        log(f"workers reset to {START_LIMIT} CPU")
        os.remove(pid_file)

    ok = sum(r["status"] == "ok" for r in results)
    log(f"finished: {ok} of {len(plan)} runs ok. Runs listed in "
        f"{os.path.relpath(os.path.join(out_dir, 'runs.csv'), ROOT)}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Under nohup nobody sees the screen, so put crashes in the log too.
        import traceback
        if LOG_PATH:
            log("runner crashed:\n" + traceback.format_exc())
        raise
