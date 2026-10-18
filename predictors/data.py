"""
From a node's per-minute trace to model inputs (paper Sections 5.2 and 6.1).

Features per minute (5): requests, day of week, hour, minute, holiday.
Each node is scaled on its own with min-max, fitted on its training part only,
to [0, 1] (Eq. 8) or, as an option, to [-1, 1] (Section 6.2, decision 3.12).
Split per node in time order: 60% train, 20% validation, 20% test.

Windows are not stored: a node keeps its whole feature table on the GPU, and
a batch is cut out of it by start positions. Input = W minutes of all 5
features, target = requests in the next HORIZON minutes. A window never
crosses a split border.
"""
import os

import holidays
import numpy as np
import torch

FEATURES = ["requests", "day_of_week", "hour", "minute", "holiday"]
HORIZON = 5                       # predict t+1 .. t+5
SPLITS = {"train": (0.0, 0.6), "val": (0.6, 0.8), "test": (0.8, 1.0)}


def french_holidays(minutes):
    """The French public holidays (holidays package) on the days in `minutes`."""
    days = np.unique(minutes.astype("datetime64[D]"))
    years = sorted({int(str(d)[:4]) for d in days})
    fr = holidays.France(years=years)
    return sorted(np.datetime64(d) for d in fr if np.datetime64(d) in set(days))


def load_node(path):
    """Minutes (datetime64[m], Paris time) and requests of one node's CSV."""
    data = np.genfromtxt(path, delimiter=",", names=True, dtype=None, encoding="utf-8")
    return data["minute_paris"].astype("datetime64[m]"), data["requests"].astype(np.float64)


def feature_table(minutes, requests, holiday_days):
    """(n minutes x 5) table: requests, day of week (Monday 0), hour, minute, holiday (0/1)."""
    days = minutes.astype("datetime64[D]")
    day_of_week = (days.astype(np.int64) + 3) % 7           # 1970-01-01 was a Thursday (3)
    minute_of_day = (minutes - days).astype(np.int64)
    holiday = np.isin(days, np.array(holiday_days, dtype="datetime64[D]")).astype(np.float64)
    return np.column_stack([requests, day_of_week, minute_of_day // 60, minute_of_day % 60, holiday])


def split_bounds(n):
    """{"train": (first, end), ...}: minute indexes of each split, end excluded."""
    return {name: (int(round(a * n)), int(round(b * n))) for name, (a, b) in SPLITS.items()}


class MinMax:
    """
    x' = a + (b - a) (x - min) / (max - min) per feature, fitted on training
    rows. Range (a, b) = (0, 1) is paper Eq. 8, (-1, 1) is Section 6.2.
    """

    def __init__(self, train_rows, scale_range=(0.0, 1.0)):
        self.low = train_rows.min(axis=0)
        span = train_rows.max(axis=0) - self.low
        self.span = np.where(span > 0, span, 1.0)          # a constant feature stays at a
        self.a, self.b = scale_range

    def scale(self, rows):
        return self.a + (self.b - self.a) * (rows - self.low) / self.span

    def unscale_requests(self, values):
        """Back from scaled to real requests (feature 0)."""
        return (values - self.a) / (self.b - self.a) * self.span[0] + self.low[0]


class NodeData:
    """One node: scaled features on the device, its scaler, and the window starts of each split."""

    def __init__(self, path, window, holiday_days, device, scale_range=(0.0, 1.0)):
        self.name = os.path.splitext(os.path.basename(path))[0]
        self.minutes, requests = load_node(path)
        table = feature_table(self.minutes, requests, holiday_days)
        self.bounds = split_bounds(len(table))
        first, end = self.bounds["train"]
        self.scaler = MinMax(table[first:end], scale_range)
        self.series = torch.tensor(self.scaler.scale(table), dtype=torch.float32, device=device)
        self.window = window
        # A window starting at s uses minutes s .. s+W-1 and predicts s+W .. s+W+HORIZON-1.
        self.starts = {name: torch.arange(a, b - window - HORIZON + 1, device=device)
                       for name, (a, b) in self.bounds.items()}

    def count(self, split):
        return len(self.starts[split])

    def batch(self, starts):
        """Inputs (B, W, 5) and targets (B, HORIZON) for the given window starts."""
        steps = torch.arange(self.window, device=starts.device)
        ahead = torch.arange(HORIZON, device=starts.device)
        x = self.series[starts[:, None] + steps]
        y = self.series[starts[:, None] + self.window + ahead, 0]
        return x, y

    def batches(self, split, batch_size, shuffle, generator=None):
        """All windows of a split, in batches of batch_size (shuffled if asked)."""
        starts = self.starts[split]
        if shuffle:
            starts = starts[torch.randperm(len(starts), device=starts.device, generator=generator)]
        for i in range(0, len(starts), batch_size):
            yield self.batch(starts[i:i + batch_size])

    def target_minutes(self, split):
        """The minute of each window's first predicted step (t+1)."""
        starts = self.starts[split].cpu().numpy()
        return self.minutes[starts + self.window]


class PooledData:
    """All nodes' windows of one split together, for the central models."""

    def __init__(self, nodes):
        self.nodes = nodes

    def count(self, split):
        return sum(node.count(split) for node in self.nodes)

    def batches(self, split, batch_size, shuffle, generator=None):
        # (node number, start) for every window of every node
        device = self.nodes[0].series.device
        which = torch.cat([torch.full((n.count(split),), i, device=device) for i, n in enumerate(self.nodes)])
        starts = torch.cat([n.starts[split] for n in self.nodes])
        if shuffle:
            order = torch.randperm(len(starts), device=device, generator=generator)
            which, starts = which[order], starts[order]
        series = torch.stack([n.series for n in self.nodes])        # all nodes have the same length
        window = self.nodes[0].window
        steps = torch.arange(window, device=device)
        ahead = torch.arange(HORIZON, device=device)
        for i in range(0, len(starts), batch_size):
            w, s = which[i:i + batch_size, None], starts[i:i + batch_size, None]
            yield series[w, s + steps], series[w, s + window + ahead, 0]
