"""
Milan: 4 areas with clearly different peak times, from internet activity.

Exploration on the 4 processed days in data/raw/milan/ (2013-11-01 to 11-04,
made by scripts/download_milan.py, not yet in the repo: one row per square
and 10 minutes, summed over all country codes). Only the internet column is
used.

Steps:
  1. read the 4 days: one value per square and 10-minute slot, time in Rome
     local time; empty cells and missing rows are kept apart (NaN)
  2. hourly profiles, two ways: empty = 0 (main) and empty = missing
  3. drop the squares with very low activity (for the shape clustering)
  4. A: shape clustering, k-means on z-scored 11-04 profiles, 4 groups
  5. B: compact areas, the grid tiled into 5x5 and 10x10 blocks; pick the 4
     blocks whose 11-04 peaks are furthest apart with comparable demand
  6. per area: peak hours, peak/mean, demand share, overlap of peaks, and
     whether the area is one connected region
  7. figures and tables in results/milan/areas/

Usage:
    .venv/bin/python scripts/milan_areas.py [--data-dir data/raw/milan]

Needs numpy, scipy and matplotlib only.
"""
import argparse
import csv
import gzip
import itertools
import json
import os
import warnings
from datetime import datetime
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")  # write PNGs, no window
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import PolyCollection
from scipy import ndimage

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(ROOT, "data", "raw", "milan")
OUT_DIR = os.path.join(ROOT, "results", "milan", "areas")
DAYS = ["2013-11-01", "2013-11-02", "2013-11-03", "2013-11-04"]
WEEKDAY = "2013-11-04"        # the only normal working day of the 4 (see docs/milan_areas.md)
ROME = ZoneInfo("Europe/Rome")
SIDE = 100                    # the grid is 100 x 100 squares
N_SQUARES = SIDE * SIDE
SLOTS = 144                   # 10-minute slots per day

# Choices, explained in docs/milan_areas.md
LOW_SHARE = 0.01              # drop the quietest squares that together hold 1% of all activity
K = 4                         # number of areas
KMEANS_RESTARTS = 20
KMEANS_SEED = 0
BLOCK_SIZES = [5, 10]         # block sides in squares
MAX_DEMAND_RATIO = 2.0        # the 4 blocks: largest total at most 2 x the smallest
PEAK_BAND = 0.9               # an hour is "in the peak" if it is >= 90% of the area's maximum

# Landmark squares named in Barlacchi et al. (2015), "Usage Notes"
LANDMARKS = {5060: "Duomo", 4259: "Bocconi", 4456: "Navigli"}
COLOURS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"]   # matplotlib's first 4 colours


# ----------------------------------------------------------------------
# 1. Reading
# ----------------------------------------------------------------------
def read_grid(path):
    """Polygons and (row, col) of every square, checked against the geometry.

    Square ids run west to east along a row, then rows go south to north:
    id = row * 100 + col + 1 with row 0 in the south. This is checked from
    the square centres, not assumed.
    """
    with open(path) as f:
        features = json.load(f)["features"]
    polygons = [None] * N_SQUARES
    centres = np.zeros((N_SQUARES, 2))
    for feature in features:
        index = feature["properties"]["cellId"] - 1
        corners = feature["geometry"]["coordinates"][0]
        polygons[index] = corners
        centres[index] = np.mean(corners[:4], axis=0)       # the 5th corner repeats the 1st
    rows, cols = np.divmod(np.arange(N_SQUARES), SIDE)
    lon = centres[:, 0].reshape(SIDE, SIDE)
    lat = centres[:, 1].reshape(SIDE, SIDE)
    if not (np.all(np.diff(lon, axis=1) > 0) and np.all(np.diff(lat, axis=0) > 0)):
        raise SystemExit("grid layout is not id = row * 100 + col + 1 (south-west first)")
    return polygons, rows, cols, centres


def read_day(path):
    """Internet activity as an array (10000 squares, 144 slots); NaN = empty cell or missing row.

    Also returns the start time of every slot in Rome local time, and how many
    cells were empty and how many rows were missing.
    """
    values = np.full((N_SQUARES, SLOTS), np.nan)
    times = {}
    empty = 0
    with gzip.open(path, "rt") as f:
        reader = csv.DictReader(f)
        rows_seen = 0
        for row in reader:
            time_ms = int(row["time_ms"])
            slot = times.setdefault(time_ms, len(times))
            rows_seen += 1
            if row["internet"] == "":
                empty += 1
            else:
                values[int(row["square_id"]) - 1, slot] = float(row["internet"])
    starts = sorted(times)
    if len(starts) != SLOTS or any(b - a != 600_000 for a, b in zip(starts, starts[1:])):
        raise SystemExit(f"{path}: expected 144 slots 10 minutes apart")
    if [times[t] for t in starts] != list(range(SLOTS)):
        values = values[:, [times[t] for t in starts]]        # put slots in time order
    local = [datetime.fromtimestamp(t / 1000, ROME) for t in starts]
    return values, local, {"empty_cells": empty, "missing_rows": N_SQUARES * SLOTS - rows_seen}


# ----------------------------------------------------------------------
# 2. Hourly profiles
# ----------------------------------------------------------------------
def hourly(values, empty_as):
    """(squares, 24) hourly sums of the 10-minute values.

    empty_as="zero":    an empty cell or missing row counts as 0
    empty_as="missing": the hour is the mean of its known slots x 6
                        (NaN if all 6 are unknown)
    """
    by_hour = values.reshape(len(values), 24, 6)
    if empty_as == "zero":
        return np.nan_to_num(by_hour).sum(axis=2)
    with warnings.catch_warnings():               # all-NaN hours stay NaN, on purpose
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmean(by_hour, axis=2) * 6


def low_activity_cut(totals, share):
    """Ids (0-based) of the quietest squares that together hold at most `share` of the total."""
    order = np.argsort(totals)
    cumulative = np.cumsum(totals[order])
    n_drop = int(np.searchsorted(cumulative, share * totals.sum(), side="right"))
    return order[:n_drop], (totals[order[n_drop - 1]] if n_drop else 0.0)


# ----------------------------------------------------------------------
# 3. A: shape clustering
# ----------------------------------------------------------------------
def zscore(profiles):
    """Each row minus its mean, divided by its sd: only the shape over the day is left."""
    mean = profiles.mean(axis=1, keepdims=True)
    sd = profiles.std(axis=1, keepdims=True)
    return (profiles - mean) / sd


def kmeans(X, k, restarts, seed):
    """Plain k-means with k-means++ starts; the run with the lowest within-group distance wins."""
    rng = np.random.default_rng(seed)
    best = None
    for _ in range(restarts):
        # k-means++: first centre at random, each next one far from the chosen ones
        centres = [X[rng.integers(len(X))]]
        for _ in range(k - 1):
            d = np.min([((X - c) ** 2).sum(axis=1) for c in centres], axis=0)
            centres.append(X[rng.choice(len(X), p=d / d.sum())])
        centres = np.array(centres)
        for _ in range(300):
            distances = ((X[:, None, :] - centres[None, :, :]) ** 2).sum(axis=2)
            labels = distances.argmin(axis=1)
            new = np.array([X[labels == j].mean(axis=0) if np.any(labels == j) else centres[j]
                            for j in range(k)])
            if np.allclose(new, centres):
                break
            centres = new
        inertia = distances[np.arange(len(X)), labels].sum()
        if best is None or inertia < best[0]:
            best = (inertia, labels, centres)
    return best[1], best[2]


def shape_clusters(weekday_profiles, keep):
    """Areas of method A: {area number: square ids}, numbered by the hour of the centre's peak."""
    if np.isnan(weekday_profiles[keep]).any():
        raise SystemExit("a kept square has an unknown hour on 11-04; k-means needs full profiles")
    labels, centres = kmeans(zscore(weekday_profiles[keep]), K, KMEANS_RESTARTS, KMEANS_SEED)
    order = np.argsort(centres.argmax(axis=1), kind="stable")   # earliest peak first
    return [keep[labels == j] for j in order]


# ----------------------------------------------------------------------
# 4. B: compact blocks
# ----------------------------------------------------------------------
def blocks(rows, cols, size):
    """Every size x size block of the grid as an array of square ids, with its (block row, block col)."""
    result = {}
    for square in range(N_SQUARES):
        result.setdefault((rows[square] // size, cols[square] // size), []).append(square)
    return {key: np.array(ids) for key, ids in result.items()}


def circular_gap(hours):
    """Smallest distance between any two of the hours on a 24-hour clock."""
    return min(min(abs(a - b), 24 - abs(a - b)) for a, b in itertools.combinations(hours, 2))


def pick_blocks(block_ids, weekday, totals):
    """The 4 blocks whose 11-04 peak hours are furthest apart, with comparable demand.

    Candidates: blocks with at least the median block demand (so no empty
    fields at the edge of the grid). Among all sets of 4 whose largest total
    is at most MAX_DEMAND_RATIO x the smallest: the largest smallest gap
    between peak hours wins, then the smallest demand ratio.
    """
    keys = list(block_ids)
    demand = np.array([totals[block_ids[k]].sum() for k in keys])
    peak = np.array([area_profile(weekday, block_ids[k]).argmax() for k in keys])
    candidates = np.where(demand >= np.median(demand))[0]
    by_hour = {}
    for i in candidates:
        by_hour.setdefault(int(peak[i]), []).append(i)

    # Try the sets of 4 peak hours from the widest gap down; stop at the first
    # gap for which some set has 4 blocks within the demand ratio.
    hour_sets = sorted(itertools.combinations(sorted(by_hour), K), key=circular_gap, reverse=True)
    best = None
    for hours in hour_sets:
        gap = circular_gap(hours)
        if best is not None and gap < best[0]:
            break
        choice, ratio = closest_demands([by_hour[h] for h in hours], demand)
        if ratio <= MAX_DEMAND_RATIO and (best is None or ratio < best[1]):
            best = (gap, ratio, choice)
    if best is None:
        raise SystemExit("no 4 blocks meet the demand ratio")
    chosen = sorted(best[2], key=lambda i: peak[i])
    return [block_ids[keys[i]] for i in chosen], [keys[i] for i in chosen], best[0], best[1]


def closest_demands(groups, demand):
    """One block from each group, with the smallest largest/smallest demand ratio.

    Sweep over all blocks sorted by demand and keep the shortest stretch that
    holds a block of every group; the stretch's first and last block give the ratio.
    """
    items = sorted((demand[i], g, i) for g, group in enumerate(groups) for i in group)
    latest = {}                       # group -> position of its latest block in the sweep
    best = (np.inf, None)
    for pos, (d, g, _) in enumerate(items):
        latest[g] = pos
        if len(latest) == len(groups):
            first = min(latest.values())
            ratio = d / items[first][0]
            if ratio < best[0]:
                best = (ratio, [items[p][2] for p in latest.values()])
    return best[1], best[0]


# ----------------------------------------------------------------------
# 5. Describing a set of 4 areas
# ----------------------------------------------------------------------
def area_profile(profiles, squares):
    """Hourly activity of an area: the sum over its squares (unknown hours of a square count as 0)."""
    return np.nansum(profiles[squares], axis=0)


def components(squares, rows, cols):
    """Number of connected regions (squares sharing a side) and the share of the largest one."""
    mask = np.zeros((SIDE, SIDE), bool)
    mask[rows[squares], cols[squares]] = True
    labels, n = ndimage.label(mask)                 # default structure = 4 neighbours
    sizes = np.bincount(labels.ravel())[1:]
    return n, sizes.max() / sizes.sum()


def peak_hours_together(profiles):
    """Hours of the day in which 2 or more areas are within PEAK_BAND of their own maximum."""
    in_peak = np.array([p >= PEAK_BAND * p.max() for p in profiles])
    return [h for h in range(24) if in_peak[:, h].sum() >= 2]


def describe(areas, profiles_by_day, totals, rows, cols):
    """Numbers of step 6 for one set of 4 areas."""
    city = totals.sum()
    area_totals = [totals[a].sum() for a in areas]
    weekday = [area_profile(profiles_by_day[WEEKDAY], a) for a in areas]
    others = [np.mean([area_profile(profiles_by_day[d], a) for d in DAYS if d != WEEKDAY], axis=0)
              for a in areas]
    four = [np.mean([area_profile(profiles_by_day[d], a) for d in DAYS], axis=0) for a in areas]
    rows_out = []
    for i, area in enumerate(areas):
        n, largest = components(area, rows, cols)
        rows_out.append({
            "area": i + 1, "squares": int(len(area)),
            "peak_weekday": int(weekday[i].argmax()), "peak_other3": int(others[i].argmax()),
            "peak_4day": int(four[i].argmax()),
            "peak_mean_weekday": float(weekday[i].max() / weekday[i].mean()),
            "band_hours_weekday": int((weekday[i] >= PEAK_BAND * weekday[i].max()).sum()),
            "peak_mean_4day": float(four[i].max() / four[i].mean()),
            "share_city": float(area_totals[i] / city),
            "share_of_4": float(area_totals[i] / sum(area_totals)),
            "regions": int(n), "largest_region_share": float(largest),
            "landmarks": [name for sq, name in LANDMARKS.items() if sq - 1 in set(area.tolist())],
        })
    return {"areas": rows_out,
            "together_weekday": peak_hours_together(weekday),
            "together_4day": peak_hours_together(four),
            "profiles": {"weekday": weekday, "other3": others, "four": four}}


# ----------------------------------------------------------------------
# 6. Figures
# ----------------------------------------------------------------------
def style():
    plt.rcParams.update({
        "font.size": 12, "axes.titlesize": 13, "legend.fontsize": 11,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": "#e4e4e0", "grid.linewidth": 0.6,
    })


def draw_map(ax, polygons, centres, totals, areas, title, outline):
    """Grey squares (darker = more activity), the 4 areas in colour, landmarks as black dots."""
    shade = np.log10(np.maximum(totals, 1))
    shade = (shade - shade.min()) / (shade.max() - shade.min())
    greys = [(1 - 0.35 * s,) * 3 for s in shade]
    ax.add_collection(PolyCollection(polygons, facecolors=greys, edgecolors="none"))
    for i, area in enumerate(areas):
        ax.add_collection(PolyCollection([polygons[s] for s in area], facecolors=COLOURS[i],
                                         edgecolors=COLOURS[i] if not outline else "black",
                                         linewidths=0.8 if outline else 0, alpha=0.9,
                                         label=f"area {i + 1}"))
    for square, name in LANDMARKS.items():
        lon, lat = centres[square - 1]
        ax.plot(lon, lat, "o", color="black", markersize=4)
        ax.annotate(name, (lon, lat), xytext=(4, 4), textcoords="offset points", fontsize=9)
    ax.set_xlim(centres[:, 0].min() - 0.002, centres[:, 0].max() + 0.002)
    ax.set_ylim(centres[:, 1].min() - 0.002, centres[:, 1].max() + 0.002)
    ax.set_aspect(1 / np.cos(np.radians(centres[:, 1].mean())))   # metres look square
    ax.set_title(title, loc="left")
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    ax.grid(False)


def plot_profiles(path, described, title):
    """Each area's hourly profile divided by its own mean: 11-04 left, the other 3 days right."""
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8), sharey=True)
    for ax, key, label in ((axes[0], "weekday", "Mon 2013-11-04 (working day)"),
                           (axes[1], "other3", "Mean of Fri 11-01 (holiday), Sat 11-02, Sun 11-03")):
        for i, profile in enumerate(described["profiles"][key]):
            shape = profile / profile.mean()
            ax.plot(np.arange(24) + 0.5, shape, color=COLOURS[i], linewidth=2, label=f"area {i + 1}")
            ax.plot(shape.argmax() + 0.5, shape.max(), "o", color=COLOURS[i], markersize=8)
        ax.set_title(label, loc="left")
        ax.set_xticks(range(0, 25, 3))
        ax.set_xlim(0, 24)
        ax.set_xlabel("hour of day (Rome)")
    axes[0].set_ylabel("activity / daily mean")
    axes[0].legend(frameon=False)
    fig.suptitle(title, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_timeline(path, sets):
    """24-hour timeline: per area its peak band (bar), 11-04 peak (filled) and 4-day peak (hollow)."""
    n_rows = sum(len(d["areas"]) for _, d in sets) + len(sets) - 1
    fig, ax = plt.subplots(figsize=(13, 0.45 * n_rows + 1.6))
    y, ticks, labels = 0, [], []
    for name, described in sets:
        for i, (area, profile) in enumerate(zip(described["areas"], described["profiles"]["weekday"])):
            band = np.where(profile >= PEAK_BAND * profile.max())[0]
            for h in band:
                ax.barh(y, 1, left=h, height=0.6, color=COLOURS[i], alpha=0.35, edgecolor="none")
            ax.plot(area["peak_weekday"] + 0.5, y, "o", color=COLOURS[i], markersize=10)
            ax.plot(area["peak_4day"] + 0.5, y, "o", markerfacecolor="white",
                    markeredgecolor=COLOURS[i], markeredgewidth=2, markersize=10)
            ticks.append(y)
            labels.append(f"{name}, area {i + 1}")
            y += 1
        y += 1
    ax.set_yticks(ticks, labels)
    ax.invert_yaxis()
    ax.set_xlim(0, 24)
    ax.set_xticks(range(25))
    ax.set_xlabel("hour of day (Rome)")
    ax.grid(axis="y", visible=False)
    handles = [plt.Line2D([], [], marker="o", linestyle="none", color="0.3", markersize=9,
                          label="peak hour, 11-04"),
               plt.Line2D([], [], marker="o", linestyle="none", markerfacecolor="white",
                          markeredgecolor="0.3", markeredgewidth=2, markersize=9,
                          label="peak hour, 4-day mean"),
               plt.Rectangle((0, 0), 1, 1, color="0.3", alpha=0.35,
                             label=f"11-04 hours >= {PEAK_BAND:.0%} of the area's peak")]
    ax.legend(handles=handles, ncol=3, frameon=False, loc="lower center", bbox_to_anchor=(0.5, 1.0))
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# ----------------------------------------------------------------------
# 7. Tables
# ----------------------------------------------------------------------
def table(described):
    lines = ["| Area | Squares | Peak 11-04 | Peak other 3 days | Peak 4-day mean | Peak/mean 11-04 "
             "| Peak/mean 4-day | Hours >= 90% of peak, 11-04 | Share of city | Share of the 4 "
             "| Connected regions (largest) | Landmarks |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for a in described["areas"]:
        lines.append(f"| {a['area']} | {a['squares']} | {a['peak_weekday']:02d}:00 | {a['peak_other3']:02d}:00 "
                     f"| {a['peak_4day']:02d}:00 | {a['peak_mean_weekday']:.2f} | {a['peak_mean_4day']:.2f} "
                     f"| {a['band_hours_weekday']} "
                     f"| {100 * a['share_city']:.1f}% | {100 * a['share_of_4']:.1f}% "
                     f"| {a['regions']} ({100 * a['largest_region_share']:.0f}%) "
                     f"| {', '.join(a['landmarks']) or '-'} |")
    hours = lambda hs: f"{len(hs)} ({', '.join(f'{h:02d}' for h in hs) or 'none'})"
    lines += ["", f"Hours in which 2 or more areas are within {PEAK_BAND:.0%} of their own peak: "
                  f"11-04: {hours(described['together_weekday'])}; "
                  f"4-day mean: {hours(described['together_4day'])}."]
    return "\n".join(lines)


# ----------------------------------------------------------------------
# 8. Main
# ----------------------------------------------------------------------
def run(profiles_by_day, totals, rows, cols):
    """Both methods for one way of treating empty cells."""
    dropped, cut = low_activity_cut(totals, LOW_SHARE)
    keep = np.setdiff1d(np.arange(N_SQUARES), dropped)
    weekday = profiles_by_day[WEEKDAY]
    result = {"dropped": dropped, "cut": cut, "keep": keep,
              "A": shape_clusters(weekday, keep)}
    for size in BLOCK_SIZES:
        areas, keys, gap, ratio = pick_blocks(blocks(rows, cols, size), weekday, totals)
        result[f"B{size}"] = areas
        result[f"B{size}_info"] = {"blocks": keys, "gap": gap, "ratio": ratio}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", default=DATA_DIR, help="folder with the 4 .csv.gz days and the grid")
    parser.add_argument("--out-dir", default=OUT_DIR)
    args = parser.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    polygons, rows, cols, centres = read_grid(os.path.join(args.data_dir, "milano-grid.geojson"))
    raw, counts = {}, {}
    for day in DAYS:
        values, local, counts[day] = read_day(os.path.join(args.data_dir, f"sms-call-internet-mi-{day}.csv.gz"))
        if local[0].strftime("%Y-%m-%d %H:%M") != f"{day} 00:00" or local[-1].strftime("%H:%M") != "23:50":
            raise SystemExit(f"{day}: slots run {local[0]} to {local[-1]} in Rome time")
        raw[day] = values
        counts[day]["squares_with_gaps"] = int(np.isnan(values).any(axis=1).sum())
        counts[day]["squares_with_gaps_ids"] = [int(s) + 1 for s in np.where(np.isnan(values).any(axis=1))[0]]

    # Both ways of reading an empty cell
    results = {}
    for empty_as in ("zero", "missing"):
        profiles = {day: hourly(raw[day], empty_as) for day in DAYS}
        totals = sum(np.nansum(p, axis=1) for p in profiles.values())
        results[empty_as] = (profiles, totals, run(profiles, totals, rows, cols))

    profiles, totals, main_run = results["zero"]
    _, _, alt_run = results["missing"]
    gaps = sorted({s for d in DAYS for s in counts[d]["squares_with_gaps_ids"]})
    nan_hours = {day: int(np.isnan(results["missing"][0][day]).any(axis=1).sum()) for day in DAYS}
    same = {name: all(np.array_equal(a, b) for a, b in zip(main_run[name], alt_run[name]))
            for name in ("A", "B5", "B10")}

    described = {"A": describe(main_run["A"], profiles, totals, rows, cols)}
    for size in BLOCK_SIZES:
        described[f"B{size}"] = describe(main_run[f"B{size}"], profiles, totals, rows, cols)

    # Figures
    style()
    fig, ax = plt.subplots(figsize=(9, 9))
    draw_map(ax, polygons, centres, totals, main_run["A"],
             "A: shape clusters (k-means on 11-04 profiles)", outline=False)
    dropped = main_run["dropped"]
    ax.add_collection(PolyCollection([polygons[s] for s in dropped], facecolors="white",
                                     edgecolors="0.85", linewidths=0.2))
    ax.legend(loc="lower right", frameon=True)
    fig.tight_layout()
    fig.savefig(os.path.join(args.out_dir, "map_A.png"), dpi=150)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(16, 8.5))
    for ax, size in zip(axes, BLOCK_SIZES):
        draw_map(ax, polygons, centres, totals, main_run[f"B{size}"],
                 f"B: {size}x{size} blocks ({size * 235} m side, approx.)", outline=True)
        ax.legend(loc="lower right", frameon=True)
    fig.tight_layout()
    fig.savefig(os.path.join(args.out_dir, "map_B.png"), dpi=150)
    plt.close(fig)

    plot_profiles(os.path.join(args.out_dir, "profiles_A.png"), described["A"], "A: shape clusters")
    for size in BLOCK_SIZES:
        plot_profiles(os.path.join(args.out_dir, f"profiles_B{size}.png"), described[f"B{size}"],
                      f"B: {size}x{size} blocks")
    plot_timeline(os.path.join(args.out_dir, "timeline.png"),
                  [("A", described["A"]), ("B 5x5", described["B5"]), ("B 10x10", described["B10"])])

    # Tables and numbers
    n_drop = len(dropped)
    lines = ["<!-- Written by scripts/milan_areas.py; do not edit by hand. -->", "",
             "### Data", "",
             "| Day | Empty internet cells | Missing rows | Squares with a gap |",
             "|---|---|---|---|"]
    for day in DAYS:
        c = counts[day]
        lines.append(f"| {day} | {c['empty_cells']} | {c['missing_rows']} | {c['squares_with_gaps']} |")
    lines += ["", f"Squares with a gap on any day: {len(gaps)} ({', '.join(map(str, gaps))}). "
              f"Of these, {len(set(g - 1 for g in gaps) & set(dropped.tolist()))} fall under the "
              "low-activity cut-off.",
              f"Empty = missing leaves {', '.join(f'{d}: {nan_hours[d]}' for d in DAYS)} squares with an "
              "hour that has no known slot at all.",
              f"Same areas with empty = 0 and empty = missing: A {same['A']}, 5x5 {same['B5']}, "
              f"10x10 {same['B10']}.", "",
              "### Low-activity cut-off", "",
              f"Dropped: the {n_drop} quietest squares, which together hold {LOW_SHARE:.0%} of all internet "
              f"activity of the 4 days (each has a 4-day total of at most {main_run['cut']:.1f}). "
              f"Kept: {N_SQUARES - n_drop}. Median 4-day total of all squares: {np.median(totals):.1f}.", ""]
    for name, title in (("A", "A: shape clusters"), ("B5", "B: 5x5 blocks"), ("B10", "B: 10x10 blocks")):
        lines += [f"### {title}", ""]
        if name != "A":
            info = main_run[f"{name}_info"]
            lines += [f"Blocks (block row, block col from the south-west): "
                      f"{', '.join(str(tuple(int(v) for v in k)) for k in info['blocks'])}. "
                      f"Smallest gap between the 11-04 peak hours: {info['gap']} h. "
                      f"Largest / smallest 4-day demand: {info['ratio']:.2f}.", ""]
        lines += [table(described[name]), ""]
        if not same[name]:
            # The other reading of empty cells picks other areas: show their peaks too
            alt_profiles, alt_totals, _ = results["missing"]
            alt = describe(alt_run[name], alt_profiles, alt_totals, rows, cols)["areas"]
            extra = ""
            if name != "A":
                keys = ", ".join(str(tuple(int(v) for v in k)) for k in alt_run[name + "_info"]["blocks"])
                extra = f" (blocks {keys})"
            weekday_peaks = ", ".join("%02d:00" % a["peak_weekday"] for a in alt)
            four_peaks = ", ".join("%02d:00" % a["peak_4day"] for a in alt)
            lines += [f"With empty = missing, other areas are picked{extra}: peaks on 11-04 at "
                      f"{weekday_peaks}, 4-day mean at {four_peaks}.", ""]
    with open(os.path.join(args.out_dir, "tables.md"), "w") as f:
        f.write("\n".join(lines))

    summary = {name: [{k: v for k, v in a.items()} for a in d["areas"]] for name, d in described.items()}
    summary["dropped_squares"] = n_drop
    summary["cut_total"] = float(main_run["cut"])
    summary["counts"] = counts
    summary["same_areas_both_ways"] = same
    summary["B_info"] = {f"B{s}": {"blocks": [[int(v) for v in k] for k in main_run[f'B{s}_info']['blocks']],
                                    "gap": int(main_run[f'B{s}_info']['gap']),
                                    "ratio": float(main_run[f'B{s}_info']['ratio'])} for s in BLOCK_SIZES}
    summary["A_squares"] = [[int(s) + 1 for s in area] for area in main_run["A"]]
    with open(os.path.join(args.out_dir, "areas.json"), "w") as f:
        json.dump(summary, f, indent=1)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
