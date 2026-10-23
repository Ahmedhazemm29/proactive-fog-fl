"""
The chart of results/secagg_benchmark/report.md: the aggregator's CPU time per
round on a Raspberry Pi 5, estimated from the laptop timings of
scripts/secagg_benchmark.py (laptop time x PI5_FACTOR).

    .venv/bin/python -I scripts/plot_secagg_benchmark.py

Reads results/secagg_benchmark/timings.csv, writes server_cost.png next to it.
"""
import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")                       # files only, no window
import matplotlib.pyplot as plt             # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "secagg_benchmark"
PI5_FACTOR = 3.5     # laptop core (i7-13620H) vs Pi 5 core, single-core Geekbench 6 (see the report)

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
    with open(OUT / "timings.csv", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["side"] == "server"]

    fig, ax = plt.subplots(figsize=(10, 5))
    for (method, bits), label, style, marker in LINES:
        points = sorted((int(r["clients"]), float(r["cpu_ms"]) * PI5_FACTOR)
                        for r in rows if r["method"] == method and r["key_bits"] == bits)
        ax.plot([p[0] for p in points], [p[1] for p in points], style, marker=marker, label=label)

    # One round per second: 10 ms = 1% and 100 ms = 10% of one Pi 5 core
    for ms, text, y in ((10, "1% of one Pi 5 core at 1 round/s", 11.5),
                        (100, "10% of one Pi 5 core at 1 round/s", 82)):
        ax.axhline(ms, color="grey", linewidth=0.8, linestyle=":")
        ax.text(13, y, text, color="grey", fontsize=8, ha="center")

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xticks([4, 7, 10, 20, 50])
    ax.set_xticklabels(["4", "7", "10", "20", "50"])
    ax.set_xlabel("Clients per round")
    ax.set_ylabel(f"Aggregator CPU time per round on a Pi 5 [ms]\n(estimate: laptop x {PI5_FACTOR})")
    ax.set_title("Aggregation cost per round, 5-weight model")
    ax.grid(True, which="major", alpha=0.3)
    ax.legend(fontsize=8, loc="upper left", bbox_to_anchor=(1.01, 1))   # outside: no line hidden
    fig.tight_layout()
    fig.savefig(OUT / "server_cost.png", dpi=150)
    print(f"wrote {OUT / 'server_cost.png'}")


if __name__ == "__main__":
    main()
