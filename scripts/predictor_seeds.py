"""
Seed check of Table 8: how much do the predictor results change with the
random seed?

scripts/train_predictors.py was run again with other seeds and the settings
of the Table 8 run (results/predictors/report.json: seed 0, W = 30,
patience 10, 16 nodes), each into results/predictors/seeds/seed_<n>/:

    .venv/bin/python scripts/train_predictors.py --seed 1 --windows 30 --patience 10 \\
        --traces <the traces of the Table 8 run> \\
        --out-dir results/predictors/seeds/seed_1 --weights-dir data/predictors/seeds/seed_1

Every seed is scored on the same test part as Table 8 (last 20% of every node).
This script reads those metrics.csv files and the Table 8 one (seed 0) and
writes results/predictors/seeds/summary.md and summary.csv:
    1. mean ± sd over all seeds (seed 0 included), per model, metric and step
    2. every seed's MAPE, seed 0 included
    3. BiGRU vs LSTM per seed, for the FedAvg pair and the central pair: which
       one has the lower error in each metric and step, and how many of these
       9 cells agree with seed 0 and with Dogani's Table 8
A note on seeds that were left out can be put in seeds/skipped.txt; it is
copied into the summary.

Usage:  python scripts/predictor_seeds.py
"""
import csv
import glob
import json
import os
import re
import statistics
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from train_predictors import DOGANI_TABLE8, EVAL_STEPS, MODELS  # noqa: E402

TABLE8_DIR = os.path.join(ROOT, "results", "predictors")
SEEDS_DIR = os.path.join(TABLE8_DIR, "seeds")
METRICS = [("mape", "MAPE (%)"), ("mae", "MAE"), ("rmse", "RMSE")]
STEPS = [f"t+{s}" for s in EVAL_STEPS]
PAIRS = [("FedAvg", "FedAvg-BiGRU", "FedAvg-LSTM"), ("Central", "CentralBiGRU", "CentralLSTM")]
CELLS = [(metric, step) for metric, _ in METRICS for step in STEPS]   # 9 per pair


# ----------------------------------------------------------------------
# Reading
# ----------------------------------------------------------------------
def read_metrics(folder):
    """{(model, step, metric): value} from <folder>/metrics.csv."""
    values = {}
    with open(os.path.join(folder, "metrics.csv")) as f:
        for row in csv.DictReader(f):
            for metric, _ in METRICS:
                values[(row["model"], row["step"], metric)] = float(row[metric])
    return values


def read_report(folder):
    with open(os.path.join(folder, "report.json")) as f:
        return json.load(f)


def seed_folders(seeds_dir=SEEDS_DIR):
    """{seed: folder} of the finished seed runs (those with a metrics.csv)."""
    found = {}
    for folder in glob.glob(os.path.join(seeds_dir, "seed_*")):
        match = re.fullmatch(r"seed_(\d+)", os.path.basename(folder))
        if match and os.path.exists(os.path.join(folder, "metrics.csv")):
            found[int(match.group(1))] = folder
    return dict(sorted(found.items()))


def dogani_values():
    """Dogani's Table 8 as {(model, step, metric): value}. Each list holds MAPE, MAE, RMSE at t+3..t+5."""
    return {(model, step, metric): row[m * len(STEPS) + s]
            for model, row in DOGANI_TABLE8.items()
            for m, (metric, _) in enumerate(METRICS)
            for s, step in enumerate(STEPS)}


# ----------------------------------------------------------------------
# Numbers
# ----------------------------------------------------------------------
def mean_sd(values):
    sd = statistics.stdev(values) if len(values) > 1 else float("nan")
    return statistics.mean(values), sd


def winners(values, bigru, lstm):
    """For each of the 9 cells: 'BiGRU' or 'LSTM', whichever has the lower error."""
    return ["BiGRU" if values[(bigru, step, metric)] < values[(lstm, step, metric)] else "LSTM"
            for metric, step in CELLS]


def ranking_rows(runs):
    """
    One row per seed and pair: the winner of each cell, how many of the 9
    cells BiGRU wins, and how many cells agree with seed 0 and with Dogani.
    """
    paper = dogani_values()
    rows = []
    for seed, values in runs.items():
        for pair, bigru, lstm in PAIRS:
            wins = winners(values, bigru, lstm)
            base = winners(runs[0], bigru, lstm)
            theirs = winners(paper, bigru, lstm)
            rows.append({"seed": seed, "pair": pair, "wins": wins,
                         "bigru_wins": wins.count("BiGRU"),
                         "same_as_seed0": sum(a == b for a, b in zip(wins, base)),
                         "same_as_dogani": sum(a == b for a, b in zip(wins, theirs))})
    return rows


# ----------------------------------------------------------------------
# Writing
# ----------------------------------------------------------------------
def write_summary(path, runs, reports, skipped_note):
    new = [s for s in runs if s != 0]
    lines = ["# Table 8 seed check", "",
             f"All 4 Table 8 models trained again with seed {', '.join(map(str, new))}, "
             "with the data and settings of the Table 8 run (seed 0, W = 30, patience 10, "
             "16 nodes), and scored on the same test part (last 20% of every node). "
             "Written by `scripts/predictor_seeds.py`; each seed's own `table8.md` is in "
             "`seed_<n>/`.", ""]
    times = ", ".join(f"seed {s} {reports[s]['total_seconds'] / 60:.1f} min" for s in runs)
    lines += [f"Training time of all 4 models: {times}.", ""]
    if skipped_note:
        lines += [skipped_note, ""]

    lines += [f"## Mean ± sd over seed {', '.join(map(str, runs))}", "",
              "Seed 0 is the Table 8 run, so it counts as one of the seeds. The values of "
              "each seed are in the next section.", ""]
    for metric, title in METRICS:
        digits = 2 if metric == "mape" else 1
        lines += [f"**{title}**", "", "| Model | " + " | ".join(STEPS) + " |",
                  "|---|" + "---|" * len(STEPS)]
        for model in MODELS:
            cells = [mean_sd([runs[s][(model, step, metric)] for s in runs]) for step in STEPS]
            lines.append(f"| {model} | " + " | ".join(f"{m:.{digits}f} ± {sd:.{digits}f}"
                                                      for m, sd in cells) + " |")
        lines.append("")

    paper = dogani_values()
    lines += ["## MAPE (%) of every seed", "",
              "| Model | Step | " + " | ".join(f"Seed {s}" + (" (Table 8)" if s == 0 else "")
                                             for s in runs) + " | Dogani |",
              "|---|---|" + "---|" * (len(runs) + 1)]
    for model in MODELS:
        for step in STEPS:
            lines.append(f"| {model} | {step} | "
                         + " | ".join(f"{runs[s][(model, step, 'mape')]:.2f}" for s in runs)
                         + f" | {paper[(model, step, 'mape')]} |")
    lines.append("")

    rows = ranking_rows(runs)
    header = [f"{name} {step}" for name in ("MAPE", "MAE", "RMSE") for step in STEPS]
    lines += ["## BiGRU vs LSTM per seed", "",
              "The model with the lower error in each cell: B = BiGRU, L = LSTM. "
              "Dogani's own winners are in the last two rows. \"Same as seed 0\" and "
              "\"same as Dogani\" count the cells, of 9, with the same winner.", "",
              "| Seed | Pair | " + " | ".join(header)
              + " | BiGRU lower | Same as seed 0 | Same as Dogani |",
              "|---|---|" + "---|" * (len(header) + 3)]
    for r in rows:
        lines.append(f"| {r['seed']} | {r['pair']} | " + " | ".join(w[0] for w in r["wins"])
                     + f" | {r['bigru_wins']} of 9 | {r['same_as_seed0']} of 9 "
                       f"| {r['same_as_dogani']} of 9 |")
    for pair, bigru, lstm in PAIRS:
        theirs = winners(paper, bigru, lstm)
        lines.append(f"| Dogani | {pair} | " + " | ".join(w[0] for w in theirs)
                     + f" | {theirs.count('BiGRU')} of 9 | | |")
    lines.append("")
    with open(path, "w") as f:
        f.write("\n".join(lines))
    return rows


def write_csv(path, runs):
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["seed", "model", "step", "mape", "mae", "rmse"])
        for seed, values in runs.items():
            for model in MODELS:
                for step in STEPS:
                    writer.writerow([seed, model, step] + [f"{values[(model, step, m)]:.4f}"
                                                           for m, _ in METRICS])


def main():
    folders = seed_folders()
    runs = {0: read_metrics(TABLE8_DIR), **{s: read_metrics(f) for s, f in folders.items()}}
    reports = {0: read_report(TABLE8_DIR), **{s: read_report(f) for s, f in folders.items()}}
    note_path = os.path.join(SEEDS_DIR, "skipped.txt")
    note = open(note_path).read().strip() if os.path.exists(note_path) else ""
    rows = write_summary(os.path.join(SEEDS_DIR, "summary.md"), runs, reports, note)
    write_csv(os.path.join(SEEDS_DIR, "summary.csv"), runs)
    for r in rows:
        print(f"seed {r['seed']} {r['pair']:7s}: BiGRU lower in {r['bigru_wins']} of 9, "
              f"same as seed 0 in {r['same_as_seed0']}, same as Dogani in {r['same_as_dogani']}")
    print(f"Wrote {os.path.join(SEEDS_DIR, 'summary.md')}")


if __name__ == "__main__":
    main()
