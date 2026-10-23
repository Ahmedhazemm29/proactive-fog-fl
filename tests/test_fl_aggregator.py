"""
Tests for pi/aggregator/aggregator.py (the FL aggregator on the Pi). Run all tests with:

    .venv/bin/python -m unittest discover -s tests -v

No broker needed: paho-mqtt is replaced by a stand-in, and the message
parsing, FedAvg and the round state are called directly.
"""
import json
import os
import sys
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


class Rounds(unittest.TestCase):

    def setUp(self):
        self.state = agg.RoundState(run=7)
        self.state.start_round(1)

    def test_online_and_offline(self):
        self.state.on_status("esp32-0001", "online")
        self.state.on_status("esp32-0002", "online")
        self.state.on_status("esp32-0001", "offline")
        self.assertEqual(self.state.online, {"esp32-0002"})

    def test_only_updates_of_this_run_and_round_count(self):
        self.state.on_status("esp32-0001", "online")
        self.assertFalse(self.state.on_update("esp32-0001", update([0] * 5, 10, round_number=0)))
        self.assertFalse(self.state.on_update("esp32-0001", update([0] * 5, 10, run=6)))
        self.assertEqual(self.state.missing(), {"esp32-0001"})
        self.assertTrue(self.state.on_update("esp32-0001", update([0] * 5, 10)))
        self.assertEqual(self.state.missing(), set())

    def test_a_new_round_forgets_the_old_updates(self):
        self.state.on_update("esp32-0001", update([0] * 5, 10))
        self.state.start_round(2)
        self.assertEqual(self.state.updates, {})
        self.assertEqual(self.state.missing(), {"esp32-0001"})   # still online

    def test_wait_ends_when_every_online_client_answered(self):
        for client in ("esp32-0001", "esp32-0002"):
            self.state.on_status(client, "online")

        def answer():
            time.sleep(0.05)
            self.state.on_update("esp32-0001", update([1] * 5, 10))
            time.sleep(0.05)
            self.state.on_status("esp32-0002", "offline")   # leaves: no longer waited for

        threading.Thread(target=answer).start()
        started = time.monotonic()
        updates, missed = self.state.wait_for_updates(timeout=5)
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(set(updates), {"esp32-0001"})
        self.assertEqual(missed, set())

    def test_wait_stops_at_the_timeout(self):
        self.state.on_status("esp32-0001", "online")
        updates, missed = self.state.wait_for_updates(timeout=0.1)
        self.assertEqual(updates, {})
        self.assertEqual(missed, {"esp32-0001"})


if __name__ == "__main__":
    unittest.main()
