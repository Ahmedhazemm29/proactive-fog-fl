"""
Tests for hardware/tools/fl_control.py (join/leave for the ESP32 FL clients).
No Pi and no real broker: the script talks to a fake broker on 127.0.0.1 that
records every packet and answers a command the way a board does.
"""
import contextlib
import csv
import io
import json
import os
import socket
import struct
import sys
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hardware" / "tools"))

import fl_control                                 # noqa: E402
import mqtt_watch                                 # noqa: E402

RUN = 1792772831
MODEL = json.dumps({"run": RUN, "round": 2, "rounds": 5, "weights": [0] * 5})


class FakeBroker(threading.Thread):
    """
    One client: answers CONNECT, SUBSCRIBE (then sends the stored messages)
    and PUBLISH QoS 1 (PUBACK, then the board's fresh status if answer=True).
    """

    def __init__(self, stored=(), answer=True):
        super().__init__(daemon=True)
        self.server = socket.create_server(("127.0.0.1", 0))
        self.port = self.server.getsockname()[1]
        self.stored, self.answer = list(stored), answer
        self.received = []                      # (first byte, body) of every packet from the client

    def publish(self, conn, topic, text, retain):
        conn.sendall(mqtt_watch.packet(0x30 | int(retain), mqtt_watch.mqtt_string(topic) + text.encode()))

    def run(self):
        conn, _ = self.server.accept()
        self.server.close()
        conn.settimeout(5)
        with conn:
            try:
                while True:
                    first, body = mqtt_watch.read_packet(conn)
                    self.received.append((first, body))
                    kind = first >> 4
                    if kind == 1:                                   # CONNECT
                        conn.sendall(bytes([0x20, 2, 0, 0]))
                    elif kind == 8:                                 # SUBSCRIBE
                        count, at = 0, 2
                        while at < len(body):
                            at += 3 + struct.unpack("!H", body[at:at + 2])[0]
                            count += 1
                        conn.sendall(mqtt_watch.packet(0x90, body[:2] + bytes(count)))
                        for topic, text in self.stored:
                            self.publish(conn, topic, text, retain=True)
                    elif kind == 3:                                 # PUBLISH (QoS 1)
                        length = struct.unpack("!H", body[:2])[0]
                        topic = body[2:2 + length].decode()
                        packet_id, text = body[2 + length:4 + length], body[4 + length:].decode()
                        conn.sendall(bytes([0x40, 2]) + packet_id)  # PUBACK
                        if self.answer and topic.endswith("/control"):
                            status = {"join": "online-active", "leave": "online-standby"}[text]
                            self.publish(conn, f"fog/{topic.split('/')[1]}/status", status, retain=False)
                    elif kind == 14:                                # DISCONNECT
                        return
            except (ConnectionError, OSError):
                pass

    def publishes(self):
        """(first byte, topic, text) of every PUBLISH the client sent."""
        found = []
        for first, body in self.received:
            if first >> 4 == 3:
                length = struct.unpack("!H", body[:2])[0]
                found.append((first, body[2:2 + length].decode(), body[4 + length:].decode()))
        return found


def run_tool(broker, *args):
    """Run fl_control.main with the fake broker; returns (exit code, output)."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = fl_control.main([*args, "--broker", "127.0.0.1", "--port", str(broker.port)])
    broker.join(timeout=5)
    return code, out.getvalue()


def read_log(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


class Boards(unittest.TestCase):

    def test_names_map_to_fl_ids(self):
        boards = fl_control.load_boards(ROOT / "hardware" / "esp_clients.md")
        self.assertEqual(boards["ESP-1"], "esp32-8a50")
        self.assertEqual(boards["ESP-8"], "esp32-1c74")
        self.assertEqual(boards["ESP-7"], "esp32-1774")

    def test_run_folder_name(self):
        self.assertEqual(fl_control.run_folder_name(RUN),
                         f"{datetime.fromtimestamp(RUN):%Y-%m-%d}_{RUN}")

    def test_unknown_board_or_no_board_stops_before_connecting(self):
        with self.assertRaises(SystemExit):
            fl_control.main(["join", "ESP-99", "--broker", "127.0.0.1", "--port", "1"])
        with self.assertRaises(SystemExit):
            fl_control.main(["leave", "--broker", "127.0.0.1", "--port", "1"])


class Commands(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_join_sends_qos1_never_retained_and_logs(self):
        broker = FakeBroker(stored=[("fog/global/model", MODEL)])
        broker.start()
        code, out = run_tool(broker, "join", "ESP-1", "ESP-8", "--data", str(self.data), "--timeout", "3")
        self.assertEqual(code, 0, out)
        # 0x32 = PUBLISH, QoS 1, retain bit 0
        self.assertEqual(broker.publishes(), [(0x32, "fog/esp32-8a50/control", "join"),
                                              (0x32, "fog/esp32-1c74/control", "join")])
        rows = read_log(self.data / "control.csv")
        self.assertEqual([(r["board"], r["fl_id"], r["result"], r["run"]) for r in rows],
                         [("ESP-1", "esp32-8a50", "confirmed", str(RUN)),
                          ("ESP-8", "esp32-1c74", "confirmed", str(RUN))])
        in_run = read_log(self.data / fl_control.run_folder_name(RUN) / "control.csv")
        self.assertEqual(len(in_run), 2)                  # also in the run's folder

    def test_no_answer_is_reported_and_logged(self):
        broker = FakeBroker(answer=False)
        broker.start()
        code, out = run_tool(broker, "leave", "ESP-5", "--data", str(self.data), "--timeout", "0.3")
        self.assertEqual(code, 1)
        self.assertIn("no answer", out)
        self.assertEqual(read_log(self.data / "control.csv")[0]["result"], "no answer")
        self.assertEqual([p.name for p in self.data.iterdir()], ["control.csv"])   # no run: no run folder

    def test_status_only_reads_and_warns_about_a_stored_command(self):
        broker = FakeBroker(stored=[("fog/esp32-8a50/status", "online-active"),
                                    ("fog/esp32-28bc/status", "online-standby"),
                                    ("fog/esp32-28bc/control", "join"),
                                    ("fog/global/model", MODEL)])
        broker.start()
        code, out = run_tool(broker, "status", "--data", str(self.data))
        self.assertEqual(code, 0)
        self.assertEqual(broker.publishes(), [])          # status never publishes
        self.assertIn("esp32-8a50  online-active", out)
        self.assertIn("round 2 of 5", out)
        self.assertIn("WARNING: a command is stored on fog/esp32-28bc/control", out)
        self.assertEqual(read_log(self.data / "control.csv")[0]["command"], "status")


if __name__ == "__main__":
    unittest.main()
