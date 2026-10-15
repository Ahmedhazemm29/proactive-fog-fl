"""
Calibration of the live demo (step 4B): how many requests one worker handles at 70% CPU.

Usage:
    .venv/bin/python scripts/live_calibrate.py

1. --workers workers (0.5 CPU each, default 18) behind HAProxy. Send each a
   constant rate for --seconds seconds, for each rate in --rates, and read the
   CPU of every worker from its cgroup. Stop once they are busy above 95% of
   their limit. 18 workers, because a request needs more CPU time when the
   laptop is busier (about 20% more with 18 workers than with 8), and the
   busiest minute of the window is scaled to need 18 workers.
2. The rate at 70% (0.35 CPU): read off the measured curve, on a straight
   line between the two rates around it. With 18 workers the curve bends up
   (the laptop gets busier), so one straight line through all points is wrong.
3. Check that rate per worker with each count in --check-workers (default 1
   and 8). With fewer workers a request is cheaper, so CPU ends below 70%.

workload_pod = requests per step (10 s = one trace minute) at 70% CPU.
Output: --out (default results/autoscaler_live/calibration.json).
All live containers are removed at the end, also after an error.
"""
import argparse
import asyncio
import json
import math
import os
import sys
import time

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from autoscaler import cluster  # noqa: E402
from autoscaler.loadgen import Replay  # noqa: E402

TARGET = 0.7


def log(text):
    print(text, flush=True)


def measure(c, rate, seconds, workers):
    """Send `rate` requests per second (to all workers together) for `seconds` s. CPU per worker and latency."""
    replay = Replay("127.0.0.1", cluster.LB_PORT, [int(round(rate))] * seconds, 1.0)
    before = c.cpu_stat()
    started = time.monotonic()
    asyncio.run(replay.run(time.monotonic() + 0.05))
    after = c.cpu_stat()
    wall = time.monotonic() - started
    cpu = np.array([(after[i][0] - before[i][0]) / wall for i in after])
    ms = replay.latency[~np.isnan(replay.latency)] * 1000
    return {
        "rate_per_second": rate, "workers": workers, "seconds": round(wall, 2),
        "cpu_per_worker": round(float(cpu.mean()), 4),
        "cpu_min": round(float(cpu.min()), 4), "cpu_max": round(float(cpu.max()), 4),
        "use_of_limit": round(float(cpu.mean()) / cluster.CPU_LIMIT, 4),
        "sent": len(replay.times), "failed": int((replay.outcome != 1).sum()),
        "p50_ms": round(float(np.median(ms)), 2), "p95_ms": round(float(np.percentile(ms, 95)), 2),
        "send_delay_p99_ms": round(float(np.nanpercentile(replay.send_delay, 99)) * 1000, 2),
    }


def main():
    parser = argparse.ArgumentParser(description="Requests per step one worker handles at 70% CPU.")
    parser.add_argument("--rates", default="50,100,140,160,170,180,190,200", help="requests per second per worker")
    parser.add_argument("--workers", type=int, default=18, help="workers during the sweep (default 18)")
    parser.add_argument("--seconds", type=int, default=20, help="seconds per rate (default 20)")
    parser.add_argument("--step-seconds", type=float, default=10, help="real seconds per trace minute (default 10)")
    parser.add_argument("--check-workers", default="1,8", help="worker counts of the check (default 1,8)")
    parser.add_argument("--out", default=os.path.join(ROOT, "results", "autoscaler_live", "calibration.json"))
    parser.add_argument("--config-dir", default=os.path.join(ROOT, "data", "autoscaler_live"))
    args = parser.parse_args()
    started = time.time()
    c = cluster.Cluster(args.config_dir, log)
    try:
        c.setup()
        c.scale_to(args.workers)
        measure(c, 20 * args.workers, 5, args.workers)         # warm-up, not kept
        points = []
        for rate in [float(r) for r in args.rates.split(",")]:
            point = measure(c, rate * args.workers, args.seconds, args.workers)
            point["rate_per_worker"] = rate
            points.append(point)
            log(f"  {rate:5.0f} req/s: CPU {point['cpu_per_worker']:.3f} ({100 * point['use_of_limit']:.0f}% of 0.5), "
                f"p95 {point['p95_ms']:.1f} ms, failed {point['failed']}")
            if point["use_of_limit"] > 0.95:
                break
            if point["use_of_limit"] > 0.9:
                break                                          # the next rate would overload them

        # Straight line between the two measured points around 0.35 CPU
        cpu = [p["cpu_per_worker"] for p in points]
        if max(cpu) < TARGET * cluster.CPU_LIMIT:
            raise RuntimeError("no rate reached 70% CPU: add higher --rates")
        rate70 = float(np.interp(TARGET * cluster.CPU_LIMIT, cpu, [p["rate_per_worker"] for p in points]))
        workload_pod = math.floor(rate70 * args.step_seconds)
        log(f"70% CPU at {rate70:.1f} req/s per worker = {workload_pod} requests per step")

        checks = []
        for n in [args.workers] + [int(v) for v in args.check_workers.split(",")]:
            c.scale_to(n)
            rate = n * workload_pod / args.step_seconds
            measure(c, rate, 5, n)                             # warm-up, not kept
            check = measure(c, rate, 30, n)
            checks.append(check)
            log(f"  check, {n} workers: CPU {100 * check['use_of_limit']:.1f}% of the limit "
                f"({check['cpu_min']:.3f} to {check['cpu_max']:.3f}), p95 {check['p95_ms']} ms, "
                f"failed {check['failed']}, send delay p99 {check['send_delay_p99_ms']} ms")
    finally:
        cluster.cleanup(log)

    report = {
        "cpu_limit": cluster.CPU_LIMIT, "target": TARGET, "step_seconds": args.step_seconds,
        "sweep_workers": args.workers,
        "rate70_per_second": rate70,
        "workload_pod": workload_pod,                         # requests per step (trace minute) at 70%
        "workload_pod_per_real_minute": round(rate70 * 60),
        "points": points, "checks": checks,
        "seconds": round(time.time() - started, 1),
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(report, f, indent=2)
    log(f"Saved {args.out}")


if __name__ == "__main__":
    main()
