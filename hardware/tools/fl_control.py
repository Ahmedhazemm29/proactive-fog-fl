"""
Join and leave for the ESP32 FL clients. The only laptop tool that publishes.

    python3 hardware/tools/fl_control.py join ESP-1 ESP-2 ESP-3 ESP-4
    python3 hardware/tools/fl_control.py leave ESP-5
    python3 hardware/tools/fl_control.py status

join / leave send "join" or "leave" to fog/<id>/control of every named board,
with QoS 1 and never retained: a stored command would make a rebooted board
rejoin by itself. Then they wait up to --timeout seconds for each board's
fresh status: "online-active" after a join, "online-standby" after a leave.
Every board starts in standby; a join takes effect from the next round, a
leave at once (see pi/aggregator/aggregator.py).

status only reads: the current run, the stored status of every board, and a
warning if a command is stored on a control topic.

Board names (ESP-1, ...) map to FL IDs (esp32-<last 2 bytes of the MAC>)
through hardware/esp_clients.md.

Every command is logged with its time to data/fl-runs/control.csv and, while a
run is going on, also to the run's folder data/fl-runs/<date>_<run>/control.csv.
Commands sent before a run starts (e.g. the first joins) get into the run's
folder when pi/pull_runs.py copies the run. data/fl-runs is the one of the
main checkout, also when this runs from a git worktree.
"""
import argparse
import csv
import json
import os
import re
import select
import socket
import struct
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from mqtt_watch import mqtt_string, packet, read_packet   # same folder

TOOLS_DIR = Path(__file__).resolve().parent
COMMANDS = {"join": "online-active", "leave": "online-standby"}   # command -> the answer it wants
LOG_FIELDS = ["time", "epoch", "run", "command", "board", "fl_id", "result", "answer_s"]

# A row of the table in hardware/esp_clients.md: | ESP-1 | 1c:c3:ab:ba:8a:50 |
CLIENT_ROW = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})\s*\|")


# ----------------------------------------------------------------------
# Boards, runs and the log
# ----------------------------------------------------------------------
def load_boards(path):
    """{name: FL ID} from the table in esp_clients.md, in the table's order."""
    boards = {}
    for line in Path(path).read_text().splitlines():
        match = CLIENT_ROW.match(line)
        if match:
            boards[match.group(1)] = "esp32-" + match.group(2).lower().replace(":", "")[-4:]
    return boards


def default_runs_dir():
    """data/fl-runs of the main checkout, also from a git worktree, so all runs end up in one place."""
    try:
        common = subprocess.run(["git", "-C", str(TOOLS_DIR), "rev-parse", "--path-format=absolute",
                                 "--git-common-dir"], capture_output=True, text=True, check=True)
        return Path(common.stdout.strip()).parent / "data" / "fl-runs"
    except (OSError, subprocess.CalledProcessError):
        return TOOLS_DIR.parent.parent / "data" / "fl-runs"


def run_folder_name(run):
    """The run's folder in data/fl-runs: <date>_<run>, the date of its start (same in pi/pull_runs.py)."""
    return f"{datetime.fromtimestamp(int(run)):%Y-%m-%d}_{run}"


def append_log(path, rows):
    """Append rows to a CSV log, with a header if the file is new."""
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if new:
            writer.writeheader()
        writer.writerows(rows)


# ----------------------------------------------------------------------
# A small MQTT 3.1.1 client (standard library only)
# ----------------------------------------------------------------------
class Mqtt:
    """Connect, subscribe, publish with QoS 1 (never retained), and keep every message received."""

    def __init__(self, host, port):
        self.sock = socket.create_connection((host, port), timeout=10)
        self.next_id = 1
        self.inbox = []         # (arrival time, topic, text, retained), oldest first
        client_id = f"fl-control-{os.getpid()}"     # can't clash with the aggregator or a board
        self.sock.sendall(packet(0x10, mqtt_string("MQTT") + bytes([4, 0x02])
                                 + struct.pack("!H", 60) + mqtt_string(client_id)))
        first, body = read_packet(self.sock)
        if first >> 4 != 2 or len(body) < 2 or body[1] != 0:
            raise ConnectionError("the broker refused the connection")

    def _packet_id(self):
        self.next_id += 1
        return self.next_id - 1

    def subscribe(self, topics):
        """Subscribe with QoS 0; the broker then sends the stored (retained) messages."""
        packet_id = self._packet_id()
        filters = b"".join(mqtt_string(topic) + bytes([0]) for topic in topics)
        self.sock.sendall(packet(0x82, struct.pack("!H", packet_id) + filters))
        self._wait_for(9, packet_id)                       # SUBACK

    def publish(self, topic, text):
        """Publish with QoS 1. First byte 0x32: PUBLISH, QoS 1, retain bit 0, so never stored."""
        packet_id = self._packet_id()
        self.sock.sendall(packet(0x32, mqtt_string(topic) + struct.pack("!H", packet_id) + text.encode()))
        self._wait_for(4, packet_id)                       # PUBACK: the broker has it

    def collect(self, seconds):
        """Read messages for the next `seconds` seconds."""
        end = time.time() + seconds
        while time.time() < end:
            self._read(end - time.time())

    def close(self):
        self.sock.sendall(bytes([0xE0, 0]))                # DISCONNECT
        self.sock.close()

    def _wait_for(self, kind, packet_id, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            got, body = self._read(deadline - time.time())
            if got == kind and struct.unpack("!H", body[:2])[0] == packet_id:
                return
        raise ConnectionError("no answer from the broker")

    def _read(self, timeout):
        """Read one packet, keeping a message in the inbox. Returns (kind, body), or (None, None)."""
        ready, _, _ = select.select([self.sock], [], [], max(0.0, timeout))
        if not ready:
            return None, None
        first, body = read_packet(self.sock)
        kind = first >> 4
        if kind == 3:                                      # PUBLISH from the broker
            qos = (first >> 1) & 0x03
            topic_len = struct.unpack("!H", body[:2])[0]
            topic = body[2:2 + topic_len].decode(errors="replace")
            start = 2 + topic_len + (2 if qos else 0)
            self.inbox.append((time.time(), topic, body[start:].decode(errors="replace"),
                               bool(first & 0x01)))
        return kind, body


def current_run(inbox):
    """(run, round, rounds) from the newest message on fog/global/model, or None if no run is going on."""
    models = [text for _, topic, text, _ in inbox if topic == "fog/global/model"]
    if not models or not models[-1]:
        return None                                        # no model, or cleared: no run
    try:
        model = json.loads(models[-1])
        return model["run"], model["round"], model.get("rounds")
    except (ValueError, KeyError, TypeError):
        return None


# ----------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------
def send(mqtt, targets, command, timeout):
    """
    Send the command to every (name, fl_id) in targets, then wait for each
    board's fresh status. Returns {fl_id: seconds until its answer, or None}.
    """
    wanted = COMMANDS[command]
    sent = {}
    for name, fl_id in targets:
        sent[fl_id] = time.time()          # before publishing: the answer may come quickly
        mqtt.publish(f"fog/{fl_id}/control", command)
    answers = {fl_id: None for fl_id in sent}
    deadline = time.time() + timeout
    while time.time() < deadline and None in answers.values():
        mqtt.collect(0.1)
        for arrived, topic, text, retained in mqtt.inbox:
            fl_id = topic.split("/")[1] if topic.endswith("/status") else None
            if (fl_id in sent and answers[fl_id] is None and not retained
                    and text == wanted and arrived >= sent[fl_id]):
                answers[fl_id] = arrived - sent[fl_id]
    return answers


def show_status(mqtt, boards, run):
    """Print the run and every board's stored status; warn about stored commands."""
    if run:
        run_id, number, rounds = run
        total = f" of {rounds}" if rounds else ""
        print(f"Run {run_id} (started {datetime.fromtimestamp(run_id):%Y-%m-%d %H:%M:%S}), round {number}{total}")
    else:
        print("No run going on (no global model stored on the broker)")
    stored, commands = {}, {}
    for _, topic, text, _ in mqtt.inbox:
        parts = topic.split("/")
        if len(parts) == 3 and parts[2] == "status":
            stored[parts[1]] = text
        elif len(parts) == 3 and parts[2] == "control" and text:
            commands[parts[1]] = text
    print("Stored statuses (the last one each board sent; 'offline' = it dropped):")
    names = {fl_id: name for name, fl_id in boards.items()}
    for fl_id in list(boards.values()) + sorted(set(stored) - set(boards.values())):
        print(f"  {names.get(fl_id, '?'):6} {fl_id}  {stored.get(fl_id, '(none)')}")
    for fl_id, text in sorted(commands.items()):
        print(f"WARNING: a command is stored on fog/{fl_id}/control: {text!r}. Commands must "
              "never be retained; the board deletes it the next time it connects.")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Join/leave for the ESP32 FL clients.")
    parser.add_argument("command", choices=["join", "leave", "status"])
    parser.add_argument("boards", nargs="*", help="board names, e.g. ESP-1 ESP-2")
    parser.add_argument("--broker", default="fognode1.local", help="MQTT broker (default fognode1.local)")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--timeout", type=float, default=5, help="seconds to wait for the answers (default 5)")
    parser.add_argument("--clients", type=Path, default=TOOLS_DIR.parent / "esp_clients.md",
                        help="board table (default hardware/esp_clients.md)")
    parser.add_argument("--data", type=Path, default=None,
                        help="log folder (default data/fl-runs of the main checkout)")
    args = parser.parse_args(argv)

    boards = load_boards(args.clients)
    names = list(dict.fromkeys(args.boards))                # without repeats, in order
    unknown = [name for name in names if name not in boards]
    if unknown:
        sys.exit(f"unknown board(s): {', '.join(unknown)}; known: {', '.join(boards)}")
    if args.command != "status" and not names:
        sys.exit(f"{args.command}: name at least one board, e.g. ESP-1")
    runs_dir = args.data or default_runs_dir()

    mqtt = Mqtt(args.broker, args.port)
    topics = ["fog/+/status", "fog/global/model"]
    if args.command == "status":
        topics.append("fog/+/control")
    mqtt.subscribe(topics)
    mqtt.collect(1.0)               # the stored (retained) messages come right after subscribing
    run = current_run(mqtt.inbox)

    now = time.time()
    stamp = {"time": datetime.fromtimestamp(now).astimezone().isoformat(timespec="seconds"),
             "epoch": f"{now:.3f}", "run": run[0] if run else "", "command": args.command}
    if args.command == "status":
        show_status(mqtt, boards, run)
        rows = [{**stamp, "board": "", "fl_id": "", "result": "read only", "answer_s": ""}]
        exit_code = 0
    else:
        targets = [(name, boards[name]) for name in names]
        answers = send(mqtt, targets, args.command, args.timeout)
        rows = []
        for name, fl_id in targets:
            seconds = answers[fl_id]
            result = "confirmed" if seconds is not None else "no answer"
            rows.append({**stamp, "board": name, "fl_id": fl_id, "result": result,
                         "answer_s": "" if seconds is None else f"{seconds:.2f}"})
            detail = (f"now {COMMANDS[args.command]} ({seconds:.2f} s)" if seconds is not None else
                      f"no answer within {args.timeout:g} s (offline, or older firmware without join/leave?)")
            print(f"{args.command} {name} ({fl_id}): {detail}")
        exit_code = 0 if all(row["result"] == "confirmed" for row in rows) else 1
    mqtt.close()

    append_log(runs_dir / "control.csv", rows)
    if run:
        append_log(runs_dir / run_folder_name(run[0]) / "control.csv", rows)
    where = f" and {run_folder_name(run[0])}/control.csv" if run else ""
    print(f"logged to {runs_dir / 'control.csv'}{where}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
