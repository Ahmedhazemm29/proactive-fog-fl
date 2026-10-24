"""
Make small, shareable samples of the two raw datasets in data/samples/:

  milan_2013-11-04_internet_4squares.csv / .png
      Milan, 2013-11-04 (Monday), internet activity of 4 squares
  bitbrains_week1_cpu_4vms.csv / .png
      Bitbrains fastStorage, first week, CPU usage [%] of 4 VMs

Needs data/raw/milan/ (from scripts/download_milan.py, plus milano-grid.geojson)
and data/raw/bitbrains/fastStorage/ (unpacked GWA-T-12 zip).

    .venv/bin/python scripts/make_samples.py
"""
import csv
import gzip
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")                      # write PNGs, no window
import matplotlib.pyplot as plt

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RAW = os.path.join(ROOT, "data", "raw")
OUT = os.path.join(ROOT, "data", "samples")

# Milan squares, found by looking up each place's coordinates in
# milano-grid.geojson (cell 1 is the south-west corner of the grid).
MILAN_DAY = "sms-call-internet-mi-2013-11-04.csv.gz"   # Monday, a normal working day
MILAN_SQUARES = {
    5060: "Duomo (busy centre)",
    4555: "Navigli/Darsena (nightlife)",
    5772: "Politecnico Leonardo (university)",
    1745: "Outskirts (quiet, ~10th percentile)",
}
MILAN_TZ = ZoneInfo("Europe/Rome")         # timestamps are UTC; plot local time

# Bitbrains VMs, picked by scoring all fastStorage VMs over the first week
# (mean, spread, day-to-day correlation, peak-to-median ratio).
BB_DIR = os.path.join(RAW, "bitbrains", "fastStorage", "2013-8")
BB_VMS = {
    591: "VM 591 (steady, ~54 %)",
    871: "VM 871 (daily, 23:00-01:00 UTC)",
    996: "VM 996 (daily, 16:00-19:00 UTC)",
    211: "VM 211 (bursty)",
}
BB_WEEK = 7 * 24 * 3600                    # seconds


# ----------------------------------------------------------------------
# Milan: one day, internet activity per square
# ----------------------------------------------------------------------
def milan_sample():
    """Pick the 4 squares out of MILAN_DAY and return {square: [(time_ms, internet)]}."""
    series = {sq: [] for sq in MILAN_SQUARES}
    with gzip.open(os.path.join(RAW, "milan", MILAN_DAY), "rt") as f:
        for row in csv.DictReader(f):
            sq = int(row["square_id"])
            if sq in series and row["internet"] != "":
                series[sq].append((int(row["time_ms"]), float(row["internet"])))
    return series


def save_milan(series):
    path = os.path.join(OUT, "milan_2013-11-04_internet_4squares.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["square_id", "label", "time_ms_utc", "time_local", "internet"])
        for sq, points in series.items():
            for t, v in points:
                local = datetime.fromtimestamp(t / 1000, MILAN_TZ).strftime("%Y-%m-%d %H:%M")
                w.writerow([sq, MILAN_SQUARES[sq], t, local, v])

    fig, ax = plt.subplots(figsize=(10, 5))
    for sq, points in series.items():
        times = [datetime.fromtimestamp(t / 1000, MILAN_TZ) for t, _ in points]
        ax.plot(times, [v for _, v in points], label=f"{sq}: {MILAN_SQUARES[sq]}")
    # The squares differ by ~100x, so a log axis keeps the quiet one visible.
    ax.set_yscale("log")
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%H:%M", tz=MILAN_TZ))
    ax.set_xlabel("Local time, Mon 4 Nov 2013")
    ax.set_ylabel("Internet activity per 10 min (log scale)")
    ax.set_title("Telecom Italia Milan: internet activity of 4 squares")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "milan_2013-11-04_internet_4squares.png"), dpi=120)
    plt.close(fig)


# ----------------------------------------------------------------------
# Bitbrains: first week, CPU usage [%] per VM
# ----------------------------------------------------------------------
def bitbrains_sample():
    """Return {vm: [(timestamp_s, cpu_pct)]} for the first week of the trace."""
    series = {}
    for vm in BB_VMS:
        points = []
        with open(os.path.join(BB_DIR, f"{vm}.csv")) as f:
            next(f)                        # header ("Timestamp [ms]" is really seconds)
            for line in f:
                parts = line.split(";")
                points.append((int(parts[0]), float(parts[4])))
        series[vm] = points
    # One common start for all VMs: the earliest timestamp among them.
    start = min(p[0][0] for p in series.values())
    return {vm: [(t, v) for t, v in pts if start <= t < start + BB_WEEK]
            for vm, pts in series.items()}


def save_bitbrains(series):
    path = os.path.join(OUT, "bitbrains_week1_cpu_4vms.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["vm", "label", "timestamp_s", "time_utc", "cpu_usage_pct"])
        for vm, points in series.items():
            for t, v in points:
                utc = datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M")
                w.writerow([vm, BB_VMS[vm], t, utc, f"{v:.4g}"])

    fig, ax = plt.subplots(figsize=(12, 5))
    for vm, points in series.items():
        times = [datetime.fromtimestamp(t, timezone.utc) for t, _ in points]
        ax.plot(times, [v for _, v in points], linewidth=0.8, label=BB_VMS[vm])
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%a %d %b", tz=timezone.utc))
    ax.set_xlabel("Time (UTC), 12-19 Aug 2013")
    ax.set_ylabel("CPU usage [%]")
    ax.set_ylim(0, 110)                    # usage can exceed 100 % slightly in this trace
    ax.set_title("Bitbrains fastStorage: CPU usage of 4 VMs, first week")
    ax.legend(loc="upper right")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "bitbrains_week1_cpu_4vms.png"), dpi=120)
    plt.close(fig)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    save_milan(milan_sample())
    save_bitbrains(bitbrains_sample())
    for name in sorted(os.listdir(OUT)):
        print(f"{name}: {os.path.getsize(os.path.join(OUT, name)) / 1000:.1f} kB")
