"""
Build the FIFA World Cup 98 workload: total HTTP requests per minute.

This is the time series of Dogani & Khunjush (2024), Section 6.1. The logs
come from https://ita.ee.lbl.gov/html/contrib/WorldCup.html

Usage:
    .venv/bin/python scripts/fifa_workload.py --start-day 6 --end-day 6   (one day)
    .venv/bin/python scripts/fifa_workload.py                             (days 5 to 92)

1. DOWNLOAD every wc_day<X>_<Y>.gz of the chosen days into data/raw/fifa/.
   Files that are already there are skipped, so a re-run is cheap.
2. COUNT the requests per minute, one file at a time, so memory stays small
   even for all ~1.35 billion requests.
3. SAVE data/fifa_requests_per_minute_days<start>-<end>.csv with the columns
   minute_utc, minute_paris, requests: one row per minute, missing minutes = 0.
4. PRINT a summary.
"""
import argparse
import gzip
import os
import re
import sys
import urllib.request
from collections import Counter

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RAW_DIR = os.path.join(ROOT, "data", "raw", "fifa")
OUT_DIR = os.path.join(ROOT, "data")

INDEX_URL = "https://ita.ee.lbl.gov/html/contrib/WorldCup.html"
# The same files on two servers: HTTPS first, FTP if HTTPS fails.
MIRRORS = ["https://ita.ee.lbl.gov/traces/WorldCup/",
           "ftp://ita.ee.lbl.gov/traces/WorldCup/"]

# One request in the binary log: 20 bytes, big endian (">").
REQUEST = np.dtype([
    ("timestamp", ">u4"),   # seconds since 1970-01-01, GMT
    ("client_id", ">u4"),
    ("object_id", ">u4"),
    ("size", ">u4"),        # bytes sent
    ("method", "u1"),
    ("status", "u1"),
    ("type", "u1"),
    ("server", "u1"),
])
CHUNK_REQUESTS = 1_000_000  # requests read at a time (20 MB)

PARIS_OFFSET = np.timedelta64(2, "h")  # Paris summer time = GMT + 2 hours


# ----------------------------------------------------------------------
# 1. Download
# ----------------------------------------------------------------------
def list_files(start_day, end_day):
    """
    The log files of the chosen days, as listed on the dataset's web page.
    Days have 1 to 11 parts, so the page is the only reliable list. A copy of
    the page is kept in data/raw/fifa/, so re-runs work offline too.
    """
    page_copy = os.path.join(RAW_DIR, "WorldCup.html")
    try:
        with urllib.request.urlopen(INDEX_URL, timeout=60) as response:
            page = response.read().decode("latin-1")
        with open(page_copy, "w") as f:
            f.write(page)
    except OSError as error:
        if not os.path.exists(page_copy):
            sys.exit(f"could not read the file list from {INDEX_URL}: {error}")
        print(f"File list: {INDEX_URL} unreachable ({error}), using the saved copy.")
        with open(page_copy) as f:
            page = f.read()

    files = set()
    for day, part in re.findall(r"wc_day(\d+)_(\d+)\.gz", page):
        if start_day <= int(day) <= end_day:
            files.add((int(day), int(part)))
    return [f"wc_day{day}_{part}.gz" for day, part in sorted(files)]


def download(name):
    """Download one file into RAW_DIR, unless it is there already. Returns its path."""
    path = os.path.join(RAW_DIR, name)
    if os.path.exists(path):
        return path
    for mirror in MIRRORS:
        try:
            # Save as .part first and rename at the end: a download that stops
            # halfway never looks like a finished file.
            urllib.request.urlretrieve(mirror + name, path + ".part")
            os.replace(path + ".part", path)
            print(f"  downloaded {name} from {mirror} ({os.path.getsize(path) / 1e6:.1f} MB)")
            return path
        except OSError as error:
            print(f"  {mirror + name} failed: {error}")
    sys.exit(f"could not download {name} from any mirror")


# ----------------------------------------------------------------------
# 2. Count requests per minute
# ----------------------------------------------------------------------
def count_minutes(path, counts):
    """Add one file's requests per minute to `counts` (minute -> requests)."""
    requests_in_file = 0
    with gzip.open(path, "rb") as f:
        while True:
            data = f.read(CHUNK_REQUESTS * REQUEST.itemsize)
            if not data:
                break
            if len(data) % REQUEST.itemsize:
                sys.exit(f"{path}: the file length is not a multiple of 20 bytes")
            requests = np.frombuffer(data, dtype=REQUEST)
            # Minute number since 1970 for every request, then how often each occurs.
            minutes, n = np.unique(requests["timestamp"] // 60, return_counts=True)
            counts.update(dict(zip(minutes.tolist(), n.tolist())))
            requests_in_file += len(requests)
    return requests_in_file


# ----------------------------------------------------------------------
# 3. Save and 4. summarize
# ----------------------------------------------------------------------
def to_series(counts):
    """(minutes, requests) from the first to the last minute, missing minutes as 0."""
    first, last = min(counts), max(counts)
    minute_numbers = np.arange(first, last + 1)
    requests = np.array([counts.get(m, 0) for m in minute_numbers.tolist()], dtype=np.int64)
    minutes_utc = minute_numbers.astype("datetime64[m]")
    return minutes_utc, requests


def save_csv(path, minutes_utc, requests):
    utc_text = np.datetime_as_string(minutes_utc, unit="m")
    paris_text = np.datetime_as_string(minutes_utc + PARIS_OFFSET, unit="m")
    with open(path, "w") as f:
        f.write("minute_utc,minute_paris,requests\n")
        for utc, paris, n in zip(utc_text, paris_text, requests.tolist()):
            f.write(f"{utc},{paris},{n}\n")


def print_summary(minutes_utc, requests, n_files, path):
    print(f"\nFiles:        {n_files}")
    print(f"Minutes:      {len(requests)}")
    print(f"From (UTC):   {minutes_utc[0]}   Paris {minutes_utc[0] + PARIS_OFFSET}")
    print(f"To (UTC):     {minutes_utc[-1]}   Paris {minutes_utc[-1] + PARIS_OFFSET}")
    print(f"Requests per minute: min {requests.min()}, mean {requests.mean():.1f}, "
          f"max {requests.max()}")
    print(f"Minutes with 0 requests: {int((requests == 0).sum())}")
    print(f"Total requests: {int(requests.sum())}")
    print(f"Saved: {os.path.relpath(path, ROOT)}")


def main():
    parser = argparse.ArgumentParser(description="FIFA World Cup 98 logs -> requests per minute.")
    parser.add_argument("--start-day", type=int, default=5, help="first day (default 5)")
    parser.add_argument("--end-day", type=int, default=92, help="last day (default 92)")
    args = parser.parse_args()
    if not 1 <= args.start_day <= args.end_day <= 92:
        parser.error("days must satisfy 1 <= --start-day <= --end-day <= 92")

    os.makedirs(RAW_DIR, exist_ok=True)
    files = list_files(args.start_day, args.end_day)
    print(f"Days {args.start_day} to {args.end_day}: {len(files)} files")

    counts = Counter()   # minute number since 1970 -> requests
    for name in files:
        path = download(name)
        n = count_minutes(path, counts)
        print(f"  counted {name}: {n} requests")
    if not counts:
        sys.exit("no requests found (days 1 to 4 are empty)")

    minutes_utc, requests = to_series(counts)
    out = os.path.join(OUT_DIR, f"fifa_requests_per_minute_days{args.start_day}-{args.end_day}.csv")
    save_csv(out, minutes_utc, requests)
    print_summary(minutes_utc, requests, len(files), out)


if __name__ == "__main__":
    main()
