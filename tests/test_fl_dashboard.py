"""
Tests for the live FL dashboard (fl_dashboard/): the board and round rules of
fl_state.py, and that the MQTT listener of mqtt_listen.py only listens. No Pi,
no broker: the listener talks to a fake broker on 127.0.0.1.
"""
import json
import os
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(ROOT, "fl_dashboard"))

import fl_state                                   # noqa: E402
import mqtt_listen                                # noqa: E402

TABLE = """| Board | MAC |
|---|---|
| ESP-1 | 1c:c3:ab:ba:8a:50 |
| ESP-7 | 1c:c3:ab:f9:17:74 |
| ESP-8 | f8:b3:b7:7a:1c:74 |
"""
ESP1, ESP7, ESP8 = "esp32-8a50", "esp32-1774", "esp32-1c74"


def boards_from(table):
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(table)
    try:
        return fl_state.load_boards(f.name)
    finally:
        os.remove(f.name)


def new_state():
    """ESP-1 and ESP-8 shown, ESP-7 skipped, as with the dashboard's default --skip."""
    return fl_state.FLState(boards_from(TABLE), skip={"ESP-7"}, total_rounds=5)


def model(run, number):
    return json.dumps({"run": run, "round": number, "weights": [0.0] * 5}).encode()


def update(run, number, num_samples, loss, loss_before):
    return json.dumps({"run": run, "round": number, "weights": [0.1] * 5,
                       "num_samples": num_samples, "loss": loss, "loss_before": loss_before}).encode()


def board(state, fl_id):
    return next(b for b in state.snapshot(0)["boards"] if b["fl_id"] == fl_id)


class Boards(unittest.TestCase):

    def test_fl_ids_from_the_table(self):
        self.assertEqual(boards_from(TABLE), [("ESP-1", ESP1), ("ESP-7", ESP7), ("ESP-8", ESP8)])

    def test_real_table_without_esp7(self):
        boards = fl_state.load_boards(os.path.join(ROOT, "hardware", "esp_clients.md"))
        state = fl_state.FLState(boards, skip={"ESP-7"})
        shown = [(b["name"], b["fl_id"]) for b in state.snapshot(0)["boards"]]
        self.assertEqual([name for name, _ in shown],
                         ["ESP-1", "ESP-2", "ESP-3", "ESP-4", "ESP-5", "ESP-6", "ESP-8"])
        self.assertIn(("ESP-8", ESP8), shown)
        self.assertNotIn(ESP7, [fl_id for _, fl_id in shown])

    def test_stored_status_alone_is_unknown(self):
        state = new_state()
        state.on_message(f"fog/{ESP1}/status", b"online", True, 1.0)
        self.assertEqual(board(state, ESP1)["status"], "unknown")
        self.assertEqual(board(state, ESP1)["stored"], "online")

    def test_fresh_online_and_offline(self):
        state = new_state()
        state.on_message(f"fog/{ESP1}/status", b"online", False, 1.0)
        self.assertEqual(board(state, ESP1)["status"], "online")
        state.on_message(f"fog/{ESP1}/status", b"offline", False, 2.0)   # the Last Will
        self.assertEqual(board(state, ESP1)["status"], "offline")
        self.assertEqual(board(state, ESP1)["seen"], 2.0)

    def test_stored_status_that_disagrees_resets_to_unknown(self):
        state = new_state()
        state.on_message(f"fog/{ESP1}/status", b"online", False, 1.0)
        state.on_message(f"fog/{ESP1}/status", b"online", True, 5.0)     # reconnect, same: keep
        self.assertEqual(board(state, ESP1)["status"], "online")
        state.on_message(f"fog/{ESP1}/status", b"offline", True, 9.0)    # changed meanwhile
        self.assertEqual(board(state, ESP1)["status"], "unknown")

    def test_fresh_update_means_online(self):
        state = new_state()
        state.on_message(f"fog/{ESP8}/update", update(7, 1, 10, 0.1, 0.2), False, 3.0)
        self.assertEqual(board(state, ESP8)["status"], "online")

    def test_other_boards_only_when_fresh(self):
        state = new_state()
        state.on_message(f"fog/{ESP7}/status", b"online", True, 1.0)     # skipped, stored only
        self.assertNotIn(ESP7, [b["fl_id"] for b in state.snapshot(0)["boards"]])
        state.on_message(f"fog/{ESP7}/status", b"online", False, 2.0)    # live: shown, marked
        esp7 = board(state, ESP7)
        self.assertEqual((esp7["name"], esp7["status"], esp7["expected"]), ("ESP-7", "online", False))

    def test_sensor_topics_ignored(self):
        state = new_state()
        state.on_message("fog/client1/data", b"{}", False, 1.0)
        self.assertEqual(len(state.snapshot(0)["boards"]), 2)


class Rounds(unittest.TestCase):

    def test_round_summary_like_the_aggregator(self):
        state = new_state()
        state.on_message("fog/global/model", model(100, 1), False, 10.0)
        state.on_message(f"fog/{ESP1}/update", update(100, 1, 10, 0.1, 0.5), False, 10.5)
        state.on_message(f"fog/{ESP8}/update", update(100, 1, 30, 0.3, 0.9), False, 11.2)
        state.on_message("fog/global/model", model(100, 2), False, 12.5)
        first, second = state.snapshot(13.0)["rounds"]
        self.assertFalse(first["in_progress"])
        self.assertEqual((first["answered"], first["missing"]), (2, []))
        self.assertAlmostEqual(first["round_s"], 1.2)
        self.assertAlmostEqual(first["global_loss"], (0.5 * 10 + 0.9 * 30) / 40)   # weighted
        self.assertAlmostEqual(first["avg_loss"], (0.1 * 10 + 0.3 * 30) / 40)
        self.assertTrue(second["in_progress"])
        self.assertEqual(second["missing"], ["ESP-1", "ESP-8"])
        self.assertEqual(state.snapshot(13.0)["run"]["round"], 2)

    def test_board_that_did_not_answer(self):
        state = new_state()
        state.on_message("fog/global/model", model(100, 1), False, 10.0)
        state.on_message(f"fog/{ESP8}/update", update(100, 1, 30, 0.3, 0.9), False, 10.4)
        state.on_message("fog/global/model", model(100, 2), False, 21.0)
        first = state.snapshot(22.0)["rounds"][0]
        self.assertEqual((first["answered"], first["missing"]), (1, ["ESP-1"]))

    def test_updates_of_other_rounds_or_runs_not_counted(self):
        state = new_state()
        state.on_message("fog/global/model", model(100, 2), False, 10.0)
        state.on_message(f"fog/{ESP1}/update", update(100, 1, 10, 0.1, 0.5), False, 10.1)  # late
        state.on_message(f"fog/{ESP8}/update", update(99, 2, 10, 0.1, 0.5), False, 10.2)   # old run
        state.on_message(f"fog/{ESP8}/update", b'{"run": 100}', False, 10.3)               # not usable
        self.assertEqual(state.snapshot(11.0)["rounds"][0]["answered"], 0)

    def test_stored_model_then_live_update(self):
        state = new_state()
        state.on_message("fog/global/model", model(5, 3), True, 1.0)
        snap = state.snapshot(1.0)
        self.assertEqual((snap["run"]["state"], snap["run"]["round"]), ("stale", 3))
        state.on_message(f"fog/{ESP1}/update", update(5, 3, 10, 0.1, 0.2), False, 2.0)
        snap = state.snapshot(2.0)
        self.assertEqual(snap["run"]["state"], "running")
        self.assertIsNone(snap["rounds"][0]["round_s"])          # its start was before we came

    def test_run_finished_and_new_run(self):
        state = new_state()
        state.on_message("fog/global/model", model(100, 1), False, 10.0)
        state.on_message("fog/global/model", b"", False, 12.0)    # cleared after the last round
        snap = state.snapshot(12.0)
        self.assertEqual(snap["run"]["state"], "finished")
        self.assertFalse(snap["rounds"][0]["in_progress"])
        state.on_message("fog/global/model", model(200, 1), False, 20.0)
        snap = state.snapshot(20.0)
        self.assertEqual((snap["run"]["id"], len(snap["rounds"])), (200, 1))

    def test_snapshot_is_plain_json(self):
        state = new_state()
        state.on_message("fog/global/model", model(100, 1), False, 10.0)
        json.loads(json.dumps(state.snapshot(10.0), allow_nan=False))


class FakeBroker(threading.Thread):
    """Accepts one client, answers CONNECT and SUBSCRIBE, sends two messages, records everything."""

    def __init__(self):
        super().__init__(daemon=True)
        self.server = socket.create_server(("127.0.0.1", 0))
        self.port = self.server.getsockname()[1]
        self.received = []                  # (first byte, body) of every packet from the client

    def publish(self, conn, topic, payload, retain):
        conn.sendall(mqtt_listen.packet(0x30 | int(retain), mqtt_listen.mqtt_string(topic) + payload))

    def run(self):
        conn, _ = self.server.accept()
        self.server.close()                 # one client is all we need
        conn.settimeout(5)
        with conn:
            self.received.append(mqtt_listen.read_packet(conn))         # CONNECT
            conn.sendall(bytes([0x20, 2, 0, 0]))                         # CONNACK: accepted
            self.received.append(mqtt_listen.read_packet(conn))         # SUBSCRIBE
            conn.sendall(bytes([0x90, 5, 0, 1, 0, 0, 0]))                # SUBACK: 3 x QoS 0
            self.publish(conn, f"fog/{ESP1}/status", b"online", retain=True)
            self.publish(conn, f"fog/{ESP8}/status", b"online", retain=False)
            try:
                while True:
                    self.received.append(mqtt_listen.read_packet(conn))
            except (ConnectionError, OSError):
                pass                                                     # the client left


class ListenerOnlyListens(unittest.TestCase):

    def test_packets_sent_and_messages_received(self):
        broker = FakeBroker()
        broker.start()
        messages, connections = [], []
        listener = mqtt_listen.Listener(
            "127.0.0.1", broker.port, fl_state.TOPICS,
            lambda topic, payload, retained, now: messages.append((topic, payload, retained)),
            lambda connected, now, error: connections.append(connected))
        listener.start()
        deadline = time.time() + 5
        while len(messages) < 2 and time.time() < deadline:
            time.sleep(0.05)
        listener.stop()
        listener.join(timeout=5)
        broker.join(timeout=5)

        self.assertEqual(messages, [(f"fog/{ESP1}/status", b"online", True),
                                    (f"fog/{ESP8}/status", b"online", False)])
        self.assertEqual(connections, [True])
        # Packet types sent: CONNECT (1), SUBSCRIBE (8), DISCONNECT (14). Never PUBLISH (3).
        kinds = [first >> 4 for first, _ in broker.received]
        self.assertEqual(kinds, [1, 8, 14])
        # The subscription: our three topics, each with QoS 0
        body, topics, at = broker.received[1][1], [], 2
        while at < len(body):
            length = struct.unpack("!H", body[at:at + 2])[0]
            topics.append((body[at + 2:at + 2 + length].decode(), body[at + 2 + length]))
            at += 3 + length
        self.assertEqual(topics, [(topic, 0) for topic in fl_state.TOPICS])


if __name__ == "__main__":
    unittest.main()
