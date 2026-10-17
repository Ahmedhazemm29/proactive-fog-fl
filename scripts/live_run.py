"""
Live run of one scaler (step 4B): real worker containers, real FIFA traffic.

Usage:
    .venv/bin/python scripts/live_run.py --scaler khpa
    .venv/bin/python scripts/live_run.py --scaler planner --first-step 60 --steps 30 --tag demo

Scalers: none (fixed pods = the window's mean demand), khpa (CPU from
Prometheus), planner (Algorithm 3 on FedAvg-BiGRU's forecasts).

Time: one step = one trace minute = --step-seconds real seconds (default 10).
Cooldowns are in steps, as in step 4A: 3 after a scale-up (30 s), 5 after a
scale-down (50 s). Each step:
  1. read every worker's CPU from its cgroup: the CPU of the step that ended
  2. the scaler decides the workers for this step; the runner starts or
     stops containers (in the background, the load keeps going). KHPA
     first waits until Prometheus has stored a scrape from after the step
     start, so its CPU value is complete. Step 0 starts 0.5 s before a
     scrape, so that wait is about 1 s in every run (decision 4B.14)
  3. the load generator sends this step's requests, evenly spread
--warmup steps (default 3) before the first one replay the minutes before it,
with the start pods and no scaling, so KHPA has a last step to look at.

Outputs in --out-dir (default results/autoscaler_live/):
  steps_<scaler>[_<tag>].csv  one row per step
  run_<scaler>[_<tag>].json   settings and totals
The response time of every request goes to data/autoscaler_live/ (not in git).
All live containers are removed at the end, also after an error or Ctrl+C.
"""
import argparse
import asyncio
import csv
import json
import os
import signal
import sys
import time

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from autoscaler import cluster  # noqa: E402
from autoscaler.live import Stepper, cpu_per_step, cpu_share, fresh_cpu, khpa_pods, pods_for_cpu  # noqa: E402
from autoscaler.loadgen import BROKEN, HTTP_ERROR, OK, TIMEOUT, Replay  # noqa: E402
from autoscaler.scalers import Settings, planner_step, requested_pods  # noqa: E402

THRESHOLD = 0.7


def log(text):
    print(text, flush=True)


def read_window(path):
    with open(path) as f:
        rows = list(csv.DictReader(f))
    steps = np.array([int(r["step"]) for r in rows])
    requests = np.array([int(r["requests"]) for r in rows])
    forecasts = np.array([[float(r[f"f{h}"]) for h in range(1, 6)] for r in rows])
    return steps, [r["minute"] for r in rows], requests, forecasts


def settings(scaler, workload_pod, fixed_pods):
    """Table 3 settings with workload_pod from the calibration (requests per step at 70% CPU)."""
    pods_min = {"none": fixed_pods, "khpa": 1, "planner": 5}[scaler]
    # workload_pod x threshold must be the calibrated 70% rate, so workload_pod = rate / 0.7
    return Settings(workload_pod=workload_pod / THRESHOLD, pods_min=pods_min, cdt_up=3, cdt_down=5, sdr=0.3,
                    fixed_pods=fixed_pods, threshold=THRESHOLD, pods_max=cluster.MAX_WORKERS)


async def sleep_until(moment):
    await asyncio.sleep(max(0.0, moment - time.monotonic()))


def first_step_delay(args, lead=1.0, before=0.5):
    """
    Seconds from now to the start of step 0: at least `lead`, and `before`
    seconds before a cAdvisor scrape. A step lasts a multiple of the 5 s scrape
    interval, so then every step start is followed by a scrape 0.5 s later, and
    KHPA's fresh read waits about 1 s in every run (decision 4B.14). Without
    Prometheus the delay is just `lead`.
    """
    try:
        scrape = cluster.last_scrape(args.prometheus)
    except OSError:
        return lead
    now = time.time()
    if not np.isfinite(scrape) or args.step_seconds % cluster.SCRAPE_SECONDS:
        return lead
    boundary = scrape - before
    while boundary < now + lead:
        boundary += cluster.SCRAPE_SECONDS
    return boundary - now


async def read_prometheus(args, step_start):
    """
    KHPA's CPU from Prometheus for the step that starts at step_start (wall
    clock). fresh_cpu() waits for a scrape from after the step start and reads
    a complete window. Returns (cores, seconds waited, fresh); the cores are
    nan when Prometheus does not answer.
    """
    try:
        cpu, _, waited, fresh = await asyncio.to_thread(
            fresh_cpu, lambda: cluster.last_scrape(args.prometheus),
            lambda at: cluster.prometheus_cpu(args.prometheus, args.prom_window, at), step_start)
        return cpu, waited, fresh
    except OSError:
        return float("nan"), 0.0, False


async def control(c, args, s, counts, forecasts, warmup, rows, start):
    """The step loop: measure the step that ended, decide, scale. Fills `rows`."""
    stepper = Stepper(s.fixed_pods, s.cdt_up, s.cdt_down, s.pods_max)
    action = None
    before, before_time = c.cpu_stat(), time.monotonic()
    for k in range(len(counts) + 1):
        await sleep_until(start + k * args.step_seconds)
        step_start = time.time()                         # wall clock, like Prometheus' timestamps
        now = time.monotonic()
        after = c.cpu_stat()
        if k > 0:                                        # 1. CPU of step k-1
            used = cpu_per_step(before, after, now - before_time)
            cpu = [u[0] for u in used.values()]
            rows[k - 1].update(cpu_total=sum(cpu), cpu_per_worker=np.mean(cpu) if cpu else 0.0,
                               cpu_max_worker=max(cpu, default=0.0),
                               throttled_total=sum(u[1] for u in used.values()),
                               workers_on=len(used), load1=os.getloadavg()[0])
        before, before_time = after, now
        if k == len(counts):
            break
        if args.scaler == "khpa":                        # KHPA needs the CPU before it decides
            prom, waited, fresh = await read_prometheus(args, step_start)
        t = k - warmup                                   # 2. decide (not during the warm-up)
        if t >= 0:
            if args.scaler == "khpa":
                cpu_in = prom if np.isfinite(prom) else rows[k - 1]["cpu_total"]   # fall back to the cgroup
                decide = lambda current: khpa_pods(cpu_in, cluster.CPU_LIMIT, THRESHOLD, s.pods_min)  # noqa: E731
            elif args.scaler == "planner":
                decide = lambda current: planner_step(forecasts[k], current, s)  # noqa: E731
            else:
                decide = lambda current: current  # noqa: E731
            old = stepper.pods
            pods = stepper.step(t, decide)
            if pods != old:
                if action is not None:
                    await action                         # the last change must be done first
                action = asyncio.create_task(asyncio.to_thread(c.scale_to, pods))
                rows[k]["action"] = "up" if pods > old else "down"
        if args.scaler != "khpa":                        # the others only log it, after their decision
            prom, waited, fresh = await read_prometheus(args, step_start)
        rows[k].update(pods=stepper.pods, prom_cpu=prom, prom_wait_s=waited, prom_fresh=int(fresh))
    if action is not None:
        await action
    return stepper


def main():
    parser = argparse.ArgumentParser(description="Live run of one scaler on the replay window.")
    parser.add_argument("--scaler", choices=["none", "khpa", "planner"], required=True)
    parser.add_argument("--first-step", type=int, default=0, help="first window step to replay (default 0)")
    parser.add_argument("--steps", type=int, default=None, help="steps to replay (default: to the end)")
    parser.add_argument("--step-seconds", type=float, default=10, help="real seconds per trace minute (default 10)")
    parser.add_argument("--warmup", type=int, default=3, help="steps replayed before, not measured (default 3)")
    parser.add_argument("--timeout", type=float, default=2.0, help="seconds until a request fails (default 2)")
    parser.add_argument("--prometheus", default="http://localhost:9090")
    parser.add_argument("--prom-window", default="15s", help="rate() window of KHPA's CPU query (default 15s)")
    parser.add_argument("--tag", default="", help="added to the output names, e.g. demo")
    parser.add_argument("--window-dir", default=os.path.join(ROOT, "results", "autoscaler_live"))
    parser.add_argument("--out-dir", default=os.path.join(ROOT, "results", "autoscaler_live"))
    parser.add_argument("--data-dir", default=os.path.join(ROOT, "data", "autoscaler_live"))
    args = parser.parse_args()
    name = args.scaler + (f"_{args.tag}" if args.tag else "")
    os.makedirs(args.out_dir, exist_ok=True)
    os.makedirs(args.data_dir, exist_ok=True)

    info = json.load(open(os.path.join(args.window_dir, "window.json")))
    steps, minutes, requests, forecasts = read_window(os.path.join(args.window_dir, "window.csv"))
    first = int(np.flatnonzero(steps == args.first_step)[0])
    last = len(steps) if args.steps is None else first + args.steps
    picked = np.arange(first - args.warmup, last)
    assert picked[0] >= 0 and last <= len(steps), "not enough steps in window.csv for this warm-up or length"
    assert args.warmup >= 1, "KHPA needs at least one warm-up step to look at"
    counts, forecasts = requests[picked], forecasts[picked]
    s = settings(args.scaler, info["workload_pod"], info["fixed_pods"])
    rows = [{"step": int(steps[i]), "minute": minutes[i], "phase": "warmup" if j < args.warmup else "run",
             "traffic": int(requests[i]), "action": ""} for j, i in enumerate(picked)]
    log(f"{args.scaler}: {len(picked) - args.warmup} steps of {args.step_seconds:g} s "
        f"(+{args.warmup} warm-up), start {s.fixed_pods} workers, capacity {s.capacity:g} requests per step")

    # Ctrl+C or `kill` still runs the cleanup below
    def stop(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    c = cluster.Cluster(args.data_dir, log)
    started = time.time()
    try:
        c.setup()
        c.scale_to(s.fixed_pods)
        replay = Replay("127.0.0.1", cluster.LB_PORT, counts, args.step_seconds, args.timeout)

        async def both():
            start = time.monotonic() + first_step_delay(args)       # just before a scrape
            sender = asyncio.create_task(replay.run(start))
            stepper = await control(c, args, s, counts, forecasts, args.warmup, rows, start)
            await sender
            return stepper

        stepper = asyncio.run(both())
    finally:
        cluster.cleanup(log)
    wall = time.time() - started

    # Per-step load results and the requested workers
    for row, load in zip(rows, replay.per_step(len(rows))):
        row.update(load)
    for row in rows:
        row["requested_cpu"] = max(pods_for_cpu(row["cpu_total"], cluster.CPU_LIMIT, THRESHOLD), 1)
        row["requested_traffic"] = int(requested_pods([row["traffic"]], s.capacity)[0])
    fields = ["step", "minute", "phase", "traffic", "sent", "failed", "rejected", "timeouts", "p50_ms", "p95_ms", "pods",
              "workers_on", "action", "requested_cpu", "requested_traffic", "cpu_total", "cpu_per_worker",
              "cpu_max_worker", "throttled_total", "prom_cpu", "prom_wait_s", "prom_fresh", "load1"]
    with open(os.path.join(args.out_dir, f"steps_{name}.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in row.items() if k in fields})
    np.savez_compressed(os.path.join(args.data_dir, f"requests_{name}.npz"), step=replay.steps,
                        planned=replay.times, outcome=replay.outcome, latency=replay.latency,
                        queue_delay=replay.queue_delay, send_delay=replay.send_delay)

    measured = replay.steps >= args.warmup
    ok = measured & (replay.outcome == OK)
    ms = replay.latency[ok] * 1000
    total = {
        "scaler": args.scaler, "tag": args.tag, "first_step": args.first_step, "steps": len(picked) - args.warmup,
        "step_seconds": args.step_seconds, "warmup": args.warmup, "timeout_s": args.timeout,
        "prom_window": args.prom_window, "settings": vars(s), "capacity": s.capacity,
        "sent": int(measured.sum()), "failed": int((measured & (replay.outcome != OK)).sum()),
        "rejected": int((measured & (replay.outcome == HTTP_ERROR)).sum()),
        "timeouts": int((measured & (replay.outcome == TIMEOUT)).sum()),
        "broken": int((measured & (replay.outcome == BROKEN)).sum()), "broken_reasons": dict(replay.errors),
        "p50_ms": float(np.median(ms)), "p95_ms": float(np.percentile(ms, 95)), "p99_ms": float(np.percentile(ms, 99)),
        "queue_delay_p99_ms": float(np.percentile(replay.queue_delay, 99) * 1000),
        "queue_delay_max_ms": float(np.max(replay.queue_delay) * 1000),
        "send_delay_p99_ms": float(np.nanpercentile(replay.send_delay, 99) * 1000),
        "send_delay_max_ms": float(np.nanmax(replay.send_delay) * 1000),
        "scale_ups": stepper.ups, "scale_downs": stepper.downs,
        "prom_missing": int(sum(not np.isfinite(r["prom_cpu"]) for r in rows)),
        "prom_stale": int(sum(np.isfinite(r["prom_cpu"]) and not r["prom_fresh"] for r in rows)),
        "prom_wait_mean_s": float(np.mean([r["prom_wait_s"] for r in rows])),
        "prom_wait_max_s": float(np.max([r["prom_wait_s"] for r in rows])),
        "load1_max": max(r["load1"] for r in rows), "wall_seconds": round(wall, 1),
    }
    run = [r for r in rows if r["phase"] == "run"]
    # Check: the share of the real CPU (cgroup) that the Prometheus reading saw, 1.0 = all of it
    total["prom_share_of_real_cpu"] = cpu_share([r["prom_cpu"] for r in run], [r["cpu_total"] for r in run])
    total["failed_pct"] = 100 * total["failed"] / max(total["sent"], 1)
    with open(os.path.join(args.out_dir, f"run_{name}.json"), "w") as f:
        json.dump(total, f, indent=2)
    log(f"Done in {wall / 60:.1f} min: sent {total['sent']}, failed {total['failed']} ({total['failed_pct']:.2f}%), "
        f"p95 {total['p95_ms']:.1f} ms, {stepper.ups} ups, {stepper.downs} downs, "
        f"Prometheus saw {100 * total['prom_share_of_real_cpu']:.1f}% of the real CPU")


if __name__ == "__main__":
    main()
