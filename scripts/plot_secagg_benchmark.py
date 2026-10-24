"""
The chart of results/secagg_benchmark/report.md: the aggregator's CPU time per
round, measured on the Raspberry Pi 5 (fognode1) with scripts/secagg_benchmark.py.

    .venv/bin/python -I scripts/plot_secagg_benchmark.py

Reads results/secagg_benchmark/pi5/timings.csv, writes
results/secagg_benchmark/server_cost.png.
"""
import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")                       # files only, no window
import matplotlib.pyplot as plt             # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "secagg_benchmark"

# (method, key_bits) -> label and line style
LINES = [
    (("fedavg", ""), "FedAvg (no protection)", "-", "o"),
    (("masking", ""), "Pairwise masking", "-", "s"),
    (("masking_10pct_dropout", ""), "Pairwise masking, 10% dropout", "--", "s"),
    (("paillier", "2048"), "Paillier 2048, 6 ciphertexts", "-", "^"),
    (("paillier_packed", "2048"), "Paillier 2048, packed", "--", "^"),
    (("paillier", "3072"), "Paillier 3072, 6 ciphertexts", "-", "D"),
    (("paillier_packed", "3072"), "Paillier 3072, packed", "--", "D"),
]


def main():
    with open(OUT / "pi5" / "timings.csv", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["side"] == "server"]

    fig, ax = plt.subplots(figsize=(10, 5))
    for (method, bits), label, style, marker in LINES:
        points = sorted((int(r["clients"]), float(r["cpu_ms"]))
                        for r in rows if r["method"] == method and r["key_bits"] == bits)
        ax.plot([p[0] for p in points], [p[1] for p in points], style, marker=marker, label=label)

    # One round per second: 10 ms = 1% and 100 ms = 10% of one Pi 5 core
    for ms, text, y in ((10, "1% of one Pi 5 core at 1 round/s", 7.6),
                        (100, "10% of one Pi 5 core at 1 round/s", 118)):
        ax.axhline(ms, color="grey", linewidth=0.8, linestyle=":")
        ax.text(4.2, y, text, color="grey", fontsize=8, ha="left")   # left, in a gap between lines

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xticks([4, 7, 10, 20, 50])
    ax.set_xticklabels(["4", "7", "10", "20", "50"])
    ax.set_xlabel("Clients per round")
    ax.set_ylabel("Aggregator CPU time per round [ms]")
    ax.set_title("Aggregation cost per round on the Raspberry Pi 5 (measured), 5-weight model")
    ax.grid(True, which="major", alpha=0.3)
    ax.legend(fontsize=8, loc="upper left", bbox_to_anchor=(1.01, 1))   # outside: no line hidden
    fig.tight_layout()
    fig.savefig(OUT / "server_cost.png", dpi=150)
    print(f"wrote {OUT / 'server_cost.png'}")


if __name__ == "__main__":
    main()
