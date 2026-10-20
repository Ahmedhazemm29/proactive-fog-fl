"""
Tests for workload/mqtt_worker.py. Run all tests with:

    .venv/bin/python -m unittest discover -s tests -v

No broker and no Docker needed: the MQTT, Prometheus and scikit-learn
libraries are replaced by stand-ins, and the message handler and the batch
maker are called directly.
"""
import os
import sys
import types
import unittest
from unittest import mock

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_worker():
    """Import mqtt_worker.py with stand-ins for the libraries it needs."""
    stand_ins = {name: mock.MagicMock() for name in
                 ("paho", "paho.mqtt", "paho.mqtt.client", "prometheus_client")}
    stand_ins["sklearn"] = types.ModuleType("sklearn")
    stand_ins["sklearn.linear_model"] = types.ModuleType("sklearn.linear_model")
    stand_ins["sklearn.linear_model"].SGDClassifier = None
    module = types.ModuleType("mqtt_worker")
    with open(os.path.join(ROOT, "workload", "mqtt_worker.py")) as f:
        source = f.read()
    with mock.patch.dict(sys.modules, stand_ins):
        exec(compile(source, "mqtt_worker.py", "exec"), module.__dict__)
    return module


def message(payload):
    """A stand-in for a paho message: only .payload is used."""
    return types.SimpleNamespace(payload=payload)


class ParseSensorTest(unittest.TestCase):
    def setUp(self):
        self.worker = load_worker()

    def test_reads_the_sensor_value(self):
        self.assertEqual(self.worker.parse_sensor(b'{"client_id":1,"sensor":23.71}'), 23.71)

    def test_unusable_messages_give_none(self):
        for payload in (b"not json", b'{"counter":1}', b'{"sensor":"abc"}', b'[1, 2]'):
            self.assertIsNone(self.worker.parse_sensor(payload), payload)


class OnMessageTest(unittest.TestCase):
    def setUp(self):
        self.worker = load_worker()
        self.worker.STEPS_PER_MSG = 10
        self.worker.MAX_BACKLOG = 25

    def test_each_message_adds_steps_up_to_the_backlog_limit(self):
        for value in (1.0, 2.0, 3.0):
            self.worker.on_message(None, None, message(b'{"sensor": %f}' % value))
        self.assertEqual(list(self.worker.samples), [1.0, 2.0, 3.0])
        self.assertEqual(self.worker.received, 3)
        self.assertEqual(self.worker.backlog, 25)   # 30 steps, capped at 25
        self.assertEqual(self.worker.dropped, 5)

    def test_bad_message_adds_nothing(self):
        with mock.patch("builtins.print"):
            self.worker.on_message(None, None, message(b"garbage"))
        self.assertEqual(len(self.worker.samples), 0)
        self.assertEqual(self.worker.backlog, 0)


class MakeBatchTest(unittest.TestCase):
    def setUp(self):
        self.worker = load_worker()
        self.worker.BATCH = 50
        self.worker.WINDOW = 4
        self.rng = np.random.default_rng(0)

    def test_shapes_and_centred_windows(self):
        X, y = self.worker.make_batch(np.arange(20.0), self.rng)
        self.assertEqual(X.shape, (50, 4))
        self.assertEqual(y.shape, (50,))
        np.testing.assert_allclose(X.mean(axis=1), 0, atol=1e-12)

    def test_labels_say_whether_the_next_value_is_higher(self):
        _, y_up = self.worker.make_batch(np.arange(20.0), self.rng)
        _, y_down = self.worker.make_batch(np.arange(20.0)[::-1], self.rng)
        self.assertTrue((y_up == 1).all())
        self.assertTrue((y_down == 0).all())

    def test_works_with_just_one_window_more_than_needed(self):
        X, y = self.worker.make_batch(np.arange(5.0), self.rng)   # WINDOW + 1 values
        np.testing.assert_allclose(X[0], [-1.5, -0.5, 0.5, 1.5])
        self.assertTrue((y == 1).all())


if __name__ == "__main__":
    unittest.main()
