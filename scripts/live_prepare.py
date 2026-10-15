"""
The replay window of the live demo (step 4B), with FedAvg-BiGRU's forecasts.

Usage (after scripts/live_calibrate.py):
    .venv/bin/python scripts/live_prepare.py

1. Node 0's test period, and the trained FedAvg-BiGRU predictions of step 3
   (data/predictors/, no new training), aligned as in step 4A.
2. The window: --minutes minutes (default 180 = 3 h) centred on the busiest
   half hour of the test period, so it has a rise and a drop. Plus --warmup
   minutes before it: they are replayed first, so KHPA has a last minute to
   look at, but they are not measured.
3. One scale factor for traffic and forecasts: the busiest minute of the
   window needs --peak-workers workers (default 18) at workload_pod requests
   per worker and step (from calibration.json).

Outputs in --out-dir (default results/autoscaler_live/):
  window.csv   step, minute, raw and scaled requests, scaled forecasts f1 .. f5
               (f1 = the forecast of this step, made one step earlier)
  window.json  factor, workload_pod, fixed pods (the mean demand), and so on
The live runner only reads these two files, so a demo needs no PyTorch.
"""
import argparse
import csv
import json
import math
import os
import sys

import numpy as np
import torch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import simulate_autoscaler as sim  # noqa: E402
from predictors.data import HORIZON, NodeData, french_holidays, load_node  # noqa: E402

PREDICTOR = "FedAvg-BiGRU"


def main():
    parser = argparse.ArgumentParser(description="Pick the replay window and scale it.")
    parser.add_argument("--trace", default=os.path.join(ROOT, "data", "synthetic", "node_00.csv"))
    parser.add_argument("--weights-dir", default=os.path.join(ROOT, "data", "predictors"))
    parser.add_argument("--predictors-report", default=os.path.join(ROOT, "results", "predictors", "report.json"))
    parser.add_argument("--calibration", default=os.path.join(ROOT, "results", "autoscaler_live", "calibration.json"))
    parser.add_argument("--minutes", type=int, default=180)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--peak-workers", type=int, default=18)
    parser.add_argument("--out-dir", default=os.path.join(ROOT, "results", "autoscaler_live"))
    args = parser.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    # 1. Test minutes and forecasts of node 0, as in step 4A
    trained = json.load(open(args.predictors_report))
    window = trained["chosen_window"]
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = {PREDICTOR: sim.load_model(PREDICTOR, trained["settings"], args.weights_dir, window, device)}
    stamps, requests = load_node(args.trace)[:2]
    node = NodeData(args.trace, window, french_holidays(stamps), device)
    minutes, forecasts = sim.node_inputs(node, requests, model)
    forecast = forecasts[PREDICTOR]                  # row t: minutes t .. t+4, made at t-1

    # 2. The busiest half hour (30-minute moving mean) is the middle of the window
    traffic = requests[minutes]
    centre = int(np.argmax(np.convolve(traffic, np.ones(30) / 30, "valid"))) + 15
    first = centre - args.minutes // 2
    rows = np.arange(first - args.warmup, first + args.minutes)
    assert rows[0] >= 0 and rows[-1] < len(minutes), "window leaves the test period"

    # 3. Scale: the busiest minute of the window needs peak_workers workers
    workload_pod = json.load(open(args.calibration))["workload_pod"]
    in_window = traffic[first:first + args.minutes]
    factor = args.peak_workers * workload_pod / in_window.max()
    scaled = np.round(traffic[rows] * factor).astype(np.int64)
    fixed_pods = int(round(scaled[args.warmup:].mean() / workload_pod))

    with open(os.path.join(args.out_dir, "window.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["step", "minute", "raw_requests", "requests"] + [f"f{h + 1}" for h in range(HORIZON)])
        for k, r in enumerate(rows):
            writer.writerow([k - args.warmup, node.minutes[minutes[r]], int(traffic[r]), int(scaled[k])]
                            + [round(float(v) * factor, 2) for v in forecast[r]])
    info = {
        "node": node.name, "predictor": PREDICTOR, "first_minute": str(node.minutes[minutes[first]]),
        "last_minute": str(node.minutes[minutes[first + args.minutes - 1]]),
        "minutes": args.minutes, "warmup": args.warmup, "factor": factor, "workload_pod": workload_pod,
        "peak_workers": args.peak_workers, "fixed_pods": fixed_pods,
        "mean_demand_workers": float(scaled[args.warmup:].mean() / workload_pod),
        "requested_traffic_max": int(math.ceil(scaled[args.warmup:].max() / workload_pod)),
        "raw_mean": float(in_window.mean()), "raw_max": float(in_window.max()),
    }
    with open(os.path.join(args.out_dir, "window.json"), "w") as f:
        json.dump(info, f, indent=2)
    print(f"Window {info['first_minute']} .. {info['last_minute']}: factor {factor:.5f}, "
          f"mean demand {info['mean_demand_workers']:.2f} workers, fixed pods {fixed_pods}")


if __name__ == "__main__":
    main()
