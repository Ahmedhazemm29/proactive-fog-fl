"""
Tests for pi/aggregator/aggregator.py (the FL aggregator on the Pi). Run all tests with:

    .venv/bin/python -m unittest discover -s tests -v

No broker needed: paho-mqtt is replaced by a stand-in, and the message
parsing, FedAvg and the round state are called directly.
"""
import contextlib
import csv
import io
import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))


def load_aggregator():
    """Import aggregator.py with a stand-in for paho-mqtt."""
    stand_ins = {name: mock.MagicMock() for name in ("paho", "paho.mqtt", "paho.mqtt.client")}
    module = types.ModuleType("aggregator")
    with open(os.path.join(ROOT, "pi", "aggregator", "aggregator.py")) as f:
        source = f.read()
    with mock.patch.dict(sys.modules, stand_ins):
        exec(compile(source, "aggregator.py", "exec"), module.__dict__)
    return module


agg = load_aggregator()


def update(weights, num_samples, loss=0.1, loss_before=0.2, run=7, round_number=1):
    return {"run": run, "round": round_number, "weights": weights,
            "num_samples": num_samples, "loss": loss, "loss_before": loss_before}


class Messages(unittest.TestCase):

    def test_client_of(self):
        self.assertEqual(agg.client_of("fog/esp32-a1b2/update"), "esp32-a1b2")

    def test_parse_update(self):
        good = update([0.1, 0.2, 0.3, 0.4, 0.5], 200)
        self.assertEqual(agg.parse_update(json.dumps(good).encode()), good)
        for bad in (b"not json", b"{}", json.dumps(update([1, 2, 3], 200)).encode(),
                    json.dumps(update([1, 2, 3, 4, 5], 0)).encode(),
                    json.dumps(update([1, 2, "x", 4, 5], 10)).encode()):
            self.assertIsNone(agg.parse_update(bad), bad)


class FedAvg(unittest.TestCase):

    def test_weighted_by_num_samples(self):
        updates = [update([1, 1, 1, 1, 1], 100, loss=0.4), update([4, 4, 4, 4, 0], 300, loss=0.0)]
        self.assertEqual(agg.fedavg(updates), [3.25, 3.25, 3.25, 3.25, 0.25])
        self.assertAlmostEqual(agg.weighted_mean(updates, "loss"), 0.1)

    def test_one_client_keeps_its_weights(self):
        self.assertEqual(agg.fedavg([update([0.5, -1, 2, 0, 3], 50)]), [0.5, -1, 2, 0, 3])


A, B, C, D = "esp32-000a", "esp32-000b", "esp32-000c", "esp32-000d"


class Statuses(unittest.TestCase):

    def test_active_standby_offline_and_old_firmware(self):
        state = agg.RoundState(run=7)
        state.on_status(A, "online-active")
        state.on_status(B, "online")                # old firmware: always trained, counts as active
        state.on_status(C, "online-standby")
        state.on_status(D, "online-active")
        state.on_status(D, "offline")               # the Last Will
        self.assertEqual(state.active, {A, B})

    def test_on_status_reports_only_changes(self):
        state = agg.RoundState(run=7)
        self.assertFalse(state.on_status(A, "online-standby"))   # was not active, still isn't
        self.assertTrue(state.on_status(A, "online-active"))     # join
        self.assertFalse(state.on_status(A, "online-active"))    # the same again
        self.assertTrue(state.on_status(A, "online-standby"))    # leave


class Rounds(unittest.TestCase):

    def setUp(self):
        self.state = agg.RoundState(run=7)
        self.state.on_status(A, "online-active")
        self.state.on_status(B, "online-active")
        self.state.on_status(C, "online-standby")
        self.participants = self.state.start_round(1)

    def test_participants_are_the_active_clients_at_the_start(self):
        self.assertEqual(self.participants, {A, B})
        self.assertEqual(self.state.missing(), {A, B})

    def test_only_participants_updates_of_this_run_and_round_count(self):
        self.assertFalse(self.state.on_update(A, update([0] * 5, 10, round_number=0)))
        self.assertFalse(self.state.on_update(A, update([0] * 5, 10, run=6)))
        self.assertFalse(self.state.on_update(C, update([0] * 5, 10)))       # standby
        self.assertTrue(self.state.on_update(A, update([0] * 5, 10)))
        self.assertEqual(self.state.missing(), {B})

    def test_a_join_waits_for_the_next_round(self):
        self.state.on_status(C, "online-active")
        self.assertEqual(self.state.missing(), {A, B})                       # not waited for now
        self.assertFalse(self.state.on_update(C, update([0] * 5, 10)))
        self.assertEqual(self.state.start_round(2), {A, B, C})

    def test_a_leave_drops_the_client_and_its_update(self):
        self.assertTrue(self.state.on_update(A, update([1] * 5, 10)))
        self.state.on_status(A, "online-standby")
        self.assertEqual(self.state.updates, {})
        self.assertEqual(self.state.dropped, {A})
        self.assertEqual(self.state.missing(), {B})
        self.assertEqual(self.state.start_round(2), {B})                     # a new round: no A
        self.assertEqual(self.state.dropped, set())

    def test_a_new_round_forgets_the_old_updates(self):
        self.state.on_update(A, update([0] * 5, 10))
        self.state.start_round(2)
        self.assertEqual(self.state.updates, {})
        self.assertEqual(self.state.missing(), {A, B})

    def test_wait_ends_early_when_a_participant_leaves(self):
        def answer():
            time.sleep(0.05)
            self.state.on_update(A, update([1] * 5, 10))
            time.sleep(0.05)
            self.state.on_status(B, "online-standby")       # leaves: not waited for any more

        threading.Thread(target=answer).start()
        started = time.monotonic()
        updates, missed, dropped = self.state.wait_for_updates(timeout=5)
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual((set(updates), missed, dropped), ({A}, set(), {B}))

    def test_wait_stops_at_the_timeout(self):
        self.state.on_update(A, update([1] * 5, 10))
        updates, missed, dropped = self.state.wait_for_updates(timeout=0.1)
        self.assertEqual((set(updates), missed, dropped), ({A}, {B}, set()))

    def test_min_clients_counts_only_active_clients(self):
        state = agg.RoundState(run=7)
        state.on_status(A, "online-active")
        state.on_status(B, "online-standby")
        done = threading.Event()

        def wait():
            with mock.patch("builtins.print"):
                state.wait_for_clients(2)
            done.set()

        threading.Thread(target=wait, daemon=True).start()
        self.assertFalse(done.wait(0.2))                    # 1 active, 1 standby: not enough
        state.on_status(B, "online-active")
        self.assertTrue(done.wait(2))


class SlowOutput(io.StringIO):
    """stdout that waits a little in every write, like a pipe: other threads run in between."""

    def write(self, text):
        time.sleep(0.0005)
        return super().write(text)


class Log(unittest.TestCase):

    def test_lines_from_several_threads_stay_whole(self):
        # The MQTT thread and the main loop log at the same time (2026-10-24:
        # "status: ... is now onlinewaiting for clients" in docker logs)
        out = SlowOutput()
        lines = [f"thread {t} line {i}" for t in range(4) for i in range(30)]

        def write(t):
            for i in range(30):
                agg.log(f"thread {t} line {i}")

        with contextlib.redirect_stdout(out):
            threads = [threading.Thread(target=write, args=(t,)) for t in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        self.assertEqual(sorted(out.getvalue().splitlines()), sorted(lines))


class Summary(unittest.TestCase):

    def test_summary_row_and_log_line(self):
        updates = {A: update([1] * 5, 100, loss=0.1, loss_before=0.5),
                   B: update([3] * 5, 300, loss=0.3, loss_before=0.9)}
        summary = agg.round_summary(7, 3, 5, {A, B, C, D}, updates, {C}, {D}, 1.23456)
        self.assertEqual(summary["participants"], [A, B, C, D])
        self.assertEqual((summary["answered"], summary["missed"], summary["dropped"]), ([A, B], [C], [D]))
        self.assertAlmostEqual(summary["global_loss"], (0.5 * 100 + 0.9 * 300) / 400)
        self.assertAlmostEqual(summary["avg_loss"], (0.1 * 100 + 0.3 * 300) / 400)
        self.assertEqual((summary["round_s"], summary["rounds"]), (1.235, 5))
        json.dumps(summary, allow_nan=False)                # fog/global/round must be plain JSON

        row = agg.rounds_row(summary, [0.1] * 5)
        self.assertEqual([row[k] for k in ("active", "clients", "missed", "dropped")], [4, 2, 1, 1])
        self.assertIs(summary["empty"], False)
        self.assertIs(row["empty"], False)
        self.assertEqual(list(row)[:4], ["run", "round", "time", "active"])
        line = agg.log_line(summary)
        self.assertIn("2 of 4 active clients", line)
        self.assertIn(f"left during the round: {D}", line)
        self.assertTrue(line.startswith("round 3:"))        # no EMPTY prefix

    def test_round_without_answers(self):
        summary = agg.round_summary(7, 1, 0, {A}, {}, {A}, set(), 10.0)
        self.assertIsNone(summary["global_loss"])
        json.dumps(summary, allow_nan=False)
        self.assertNotEqual(agg.rounds_row(summary, [0] * 5)["avg_loss"],
                            agg.rounds_row(summary, [0] * 5)["avg_loss"])   # nan in the CSV, as before
        self.assertIn("global loss nan", agg.log_line(summary))

    def test_empty_round_is_marked(self):
        # Nobody answered: one participant missed, one left during the round
        summary = agg.round_summary(7, 2, 6, {A, B}, {}, {A}, {B}, 10.0)
        self.assertIs(summary["empty"], True)
        self.assertIn('"empty": true', json.dumps(summary, allow_nan=False))   # fog/global/round
        self.assertIs(agg.rounds_row(summary, [0] * 5)["empty"], True)
        self.assertTrue(agg.log_line(summary).startswith("EMPTY round 2: 0 of 2 active clients"))

    def test_empty_column_in_rounds_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "rounds.csv")
            full = agg.round_summary(7, 1, 2, {A}, {A: update([1] * 5, 100, loss=0.1, loss_before=0.5)},
                                     set(), set(), 1.0)
            empty = agg.round_summary(7, 2, 2, {A}, {}, {A}, set(), 10.0)
            agg.append_csv(path, agg.rounds_row(full, [1] * 5))
            agg.append_csv(path, agg.rounds_row(empty, [1] * 5))
            with open(path, newline="") as f:
                rows = list(csv.DictReader(f))
        self.assertEqual([r["empty"] for r in rows], ["False", "True"])
        self.assertEqual(rows[1]["avg_loss"], "nan")


if __name__ == "__main__":
    unittest.main()
