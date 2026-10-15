"""
Plot the FIFA World Cup 98 workload made by scripts/fifa_workload.py.

Usage:
    .venv/bin/python scripts/plot_fifa_workload.py
    .venv/bin/python scripts/plot_fifa_workload.py --csv data/fifa_requests_per_minute_days6-6.csv

Saves the plot next to the CSV, with .png instead of .csv.
"""
import argparse
import os

import matplotlib
matplotlib.use("Agg")   # draw to a file, no window needed
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_CSV = os.path.join(ROOT, "data", "fifa_requests_per_minute_days5-92.csv")


def read_csv(path):
    """(minutes in Paris time, requests) from the CSV."""
    data = np.genfromtxt(path, delimiter=",", names=True, dtype=None, encoding="utf-8",
                         usecols=("minute_paris", "requests"))
    return data["minute_paris"].astype("datetime64[m]"), data["requests"]


def main():
    parser = argparse.ArgumentParser(description="Plot requests per minute.")
    parser.add_argument("--csv", default=DEFAULT_CSV, help="CSV from fifa_workload.py")
    args = parser.parse_args()

    minutes, requests = read_csv(args.csv)

    fig, ax = plt.subplots(figsize=(14, 4.5))
    ax.plot(minutes.astype("datetime64[s]").astype(object), requests, linewidth=0.4, color="#3987e5")
    ax.set_title("FIFA World Cup 98: HTTP requests per minute", loc="left")
    ax.set_xlabel("Paris time (GMT + 2), 1998")
    ax.set_ylabel("requests per minute")
    ax.set_ylim(bottom=0)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    # Ticks that fit the range: days for many days, hours for a single day.
    locator = mdates.AutoDateLocator()
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    ax.grid(axis="y", color="#e5e7eb", linewidth=0.8)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    fig.tight_layout()

    out = os.path.splitext(args.csv)[0] + ".png"
    fig.savefig(out, dpi=150)
    print(f"Saved: {os.path.relpath(out, ROOT)}")


if __name__ == "__main__":
    main()
