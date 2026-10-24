"""
Tests for pi/pull_runs.py (copying the FL run data from the Pi to data/fl-runs/).
No Pi: the "Pi" is a local folder, and rsync copies it like a remote one.
"""
import contextlib
import csv
import io
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pi"))

import pull_runs                                  # noqa: E402

R1, R2, R3 = 1792700000, 1792750000, 1792800000
ROUNDS = ["run", "round", "time", "clients", "missed", "round_s", "global_loss", "avg_loss", "weights"]
UPDATES = ["run", "round", "client", "num_samples", "loss", "loss_before"]


def utc(epoch):
    """A time as the aggregator writes it in rounds.csv: ISO, UTC, no zone."""
    return datetime.fromtimestamp(epoch, timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def round_row(run, number):
    return {"run": run, "round": number, "time": "t", "clients": 2, "missed": 0, "round_s": 0.1,
            "global_loss": 0.5, "avg_loss": 0.1, "weights": "[0.1, 0.2, 0.3, 0.4, 0.5]"}


def update_row(run, number, client):
    return {"run": run, "round": number, "client": client, "num_samples": 150, "loss": 0.1,
            "loss_before": 0.2}


def make_pi_folder(folder):
    """The Pi's fl-data: two old runs in the shared files, one run in its own folder."""
    write_csv(folder / "rounds.csv", ROUNDS, [round_row(R1, 1), round_row(R1, 2), round_row(R2, 1)])
    write_csv(folder / "updates.csv", UPDATES, [update_row(R1, 1, "esp32-0001"),
                                                update_row(R2, 1, "esp32-0001")])
    write_csv(folder / str(R3) / "rounds.csv", ROUNDS + ["active"], [{**round_row(R3, 1), "active": 3}])
    write_csv(folder / str(R3) / "updates.csv", UPDATES, [update_row(R3, 1, "esp32-0002")])


class Organize(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mirror, self.runs = Path(self.tmp.name) / "mirror", Path(self.tmp.name) / "runs"
        make_pi_folder(self.mirror)

    def tearDown(self):
        self.tmp.cleanup()

    def folder(self, run):
        return self.runs / pull_runs.run_folder_name(run)

    def test_one_folder_per_run(self):
        done = pull_runs.organize(self.mirror, self.runs)
        self.assertEqual(done, {str(R1): "split from the shared files", str(R2): "split from the shared files",
                                str(R3): "copied"})
        self.assertEqual(len(read_csv(self.folder(R1) / "rounds.csv")), 2)
        self.assertEqual(len(read_csv(self.folder(R2) / "updates.csv")), 1)
        self.assertEqual(read_csv(self.folder(R3) / "rounds.csv")[0]["active"], "3")

    def test_split_runs_are_never_overwritten(self):
        kept = self.folder(R1) / "rounds.csv"
        kept.parent.mkdir(parents=True)
        kept.write_text("copied by hand, keep\n")
        done = pull_runs.organize(self.mirror, self.runs)
        self.assertEqual(kept.read_text(), "copied by hand, keep\n")
        self.assertEqual(len(read_csv(self.folder(R1) / "updates.csv")), 1)   # the missing file is added
        self.assertNotEqual(done[str(R1)], "copied")

    def test_a_run_folder_is_copied_again_while_it_grows(self):
        pull_runs.organize(self.mirror, self.runs)
        write_csv(self.mirror / str(R3) / "rounds.csv", ROUNDS + ["active"],
                  [{**round_row(R3, 1), "active": 3}, {**round_row(R3, 2), "active": 4}])
        pull_runs.organize(self.mirror, self.runs)
        self.assertEqual(len(read_csv(self.folder(R3) / "rounds.csv")), 2)


class Commands(unittest.TestCase):

    def test_commands_go_to_their_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            for run in (R1, R2):
                (runs / pull_runs.run_folder_name(run)).mkdir()
            fields = ["time", "epoch", "run", "command", "board", "fl_id", "result", "answer_s"]
            rows = [
                {"epoch": R1 + 60, "run": R1, "command": "leave", "board": "ESP-2"},   # during run 1
                {"epoch": R2 - 30, "run": "", "command": "join", "board": "ESP-5"},    # before run 2
                {"epoch": R2 + 90, "run": R2, "command": "leave", "board": "ESP-1"},   # during run 2
                {"epoch": R3 + 10, "run": "", "command": "join", "board": "ESP-3"},    # no run after it yet
            ]
            write_csv(runs / "control.csv", fields, rows)
            self.assertEqual(pull_runs.assign_commands(runs), {R1: 1, R2: 2})
            second = read_csv(runs / pull_runs.run_folder_name(R2) / "control.csv")
            self.assertEqual([r["board"] for r in second], ["ESP-5", "ESP-1"])

    def test_commands_while_a_run_waits_for_its_first_clients(self):
        # 2026-10-24: the run was deployed first and the boards joined while it
        # waited (no model yet, so no run in the log). Those joins belong to it,
        # not to the next run.
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            for run, first, last in ((R1, R1 + 12, R1 + 19), (R2, R2 + 5, R2 + 10)):
                write_csv(runs / pull_runs.run_folder_name(run) / "rounds.csv", ["run", "round", "time"],
                          [{"run": run, "round": 1, "time": utc(first)},
                           {"run": run, "round": 2, "time": utc(last)}])
            (runs / pull_runs.run_folder_name(R3)).mkdir()                      # no rounds yet
            fields = ["time", "epoch", "run", "command", "board", "fl_id", "result", "answer_s"]
            rows = [
                {"epoch": R1 + 7, "run": "", "command": "join", "board": "ESP-1"},    # R1 waiting
                {"epoch": R1 + 15, "run": R1, "command": "join", "board": "ESP-5"},   # R1 running
                {"epoch": R1 + 300, "run": "", "command": "join", "board": "ESP-2"},  # R1 done: next run
                {"epoch": R3 + 4, "run": "", "command": "join", "board": "ESP-3"},    # R3 waiting, no rounds
            ]
            write_csv(runs / "control.csv", fields, rows)
            self.assertEqual(pull_runs.assign_commands(runs), {R1: 2, R2: 1})
            first = read_csv(runs / pull_runs.run_folder_name(R1) / "control.csv")
            self.assertEqual([r["board"] for r in first], ["ESP-1", "ESP-5"])
            # Once R3 has rounds, the join sent while it waited goes to R3
            write_csv(runs / pull_runs.run_folder_name(R3) / "rounds.csv", ["run", "round", "time"],
                      [{"run": R3, "round": 1, "time": utc(R3 + 9)}])
            self.assertEqual(pull_runs.assign_commands(runs), {R1: 2, R2: 1, R3: 1})

    def test_last_round_time_is_utc(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            self.assertIsNone(pull_runs.last_round_time(folder))
            write_csv(folder / "rounds.csv", ["run", "round", "time"],
                      [{"run": R1, "round": 1, "time": "2026-10-24T10:12:06"}])
            self.assertEqual(pull_runs.last_round_time(folder), 1792836726)


class EndToEnd(unittest.TestCase):

    def test_main_with_a_local_folder_as_the_pi(self):
        with tempfile.TemporaryDirectory() as tmp:
            pi, runs = Path(tmp) / "pi", Path(tmp) / "runs"
            make_pi_folder(pi)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(pull_runs.main(["--source", f"{pi}/", "--data", str(runs)]), 0)
            self.assertTrue((runs / ".pi-mirror" / str(R3) / "rounds.csv").exists())
            names = sorted(p.name for p in runs.iterdir() if not p.name.startswith("."))
            self.assertEqual(names, sorted(pull_runs.run_folder_name(r) for r in (R1, R2, R3)))


if __name__ == "__main__":
    unittest.main()
