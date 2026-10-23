"""
The dashboard's picture of the FL run, built only from MQTT messages.

No network code here (that is mqtt_listen.py), so the rules can be tested on
their own (tests/test_fl_dashboard.py). Every message comes with its arrival
time and its retained flag:
    retained  a stored message that the broker sends right after we subscribe.
              It can be old: a board that lost power keeps "online" stored
              until the broker notices.
    fresh     a message sent live while we are subscribed.

A board (from hardware/esp_clients.md) is
    online    after a fresh "online" status, or a fresh update from it
    offline   after a fresh "offline" status (the broker sends the board's Last Will)
    unknown   while there is only an old stored status
A stored status that disagrees with the last live one means the status changed
while we were not listening (e.g. the broker connection was down), so the board
goes back to unknown.

Rounds, with the messages of pi/aggregator/aggregator.py:
    fog/global/model  {"run", "round", "weights"}: a fresh one starts that round;
                      an empty one means the run is over
    fog/<id>/update   {"run", "round", "weights", "num_samples", "loss", "loss_before"}
For each round: the clients that answered, the round time (from the model to
the last update, as seen here), the boards that did not answer, and the two
losses, weighted by num_samples as the aggregator does:
    global loss   the global model on the clients' data (loss_before)
    avg loss      the clients' models after local training (loss)
"""
import json
import math
import re
import threading
from pathlib import Path

MODEL_TOPIC = "fog/global/model"
TOPICS = ["fog/+/status", "fog/+/update", MODEL_TOPIC]   # all we subscribe to
NUM_WEIGHTS = 5          # as in pi/aggregator/aggregator.py: bias + 4 weights

# A row of the table in hardware/esp_clients.md: | ESP-1 | 1c:c3:ab:ba:8a:50 |
CLIENT_ROW = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})\s*\|")


# ----------------------------------------------------------------------
# Boards and messages
# ----------------------------------------------------------------------
def fl_id_of(mac):
    """The FL ID as the firmware makes it: esp32-<last 2 bytes of the MAC>."""
    return "esp32-" + mac.lower().replace(":", "")[-4:]


def load_boards(path):
    """[(name, fl_id), ...] in the order of the table in esp_clients.md."""
    boards = []
    for line in Path(path).read_text().splitlines():
        match = CLIENT_ROW.match(line)
        if match:
            boards.append((match.group(1), fl_id_of(match.group(2))))
    return boards


def parse_model(text):
    """(run, round) of a global model message, or None."""
    try:
        model = json.loads(text)
        if isinstance(model["run"], int) and isinstance(model["round"], int):
            return model["run"], model["round"]
    except (ValueError, KeyError, TypeError):
        pass
    return None


def parse_update(text):
    """The update as a dict, or None if the aggregator would not use it either."""
    try:
        update = json.loads(text)
        numbers = [update["num_samples"], update["loss"], update["loss_before"], *update["weights"]]
        ok = (isinstance(update["run"], int) and isinstance(update["round"], int)
              and len(update["weights"]) == NUM_WEIGHTS and update["num_samples"] > 0
              and all(isinstance(x, (int, float)) and math.isfinite(x) for x in numbers))
        return update if ok else None
    except (ValueError, KeyError, TypeError):
        return None


def new_round(number, model_time):
    """A round of the run. model_time None: we only saw the stored model, so its start is unknown."""
    return {"round": number, "model_time": model_time, "updates": {}, "closed": False}


# ----------------------------------------------------------------------
# The state
# ----------------------------------------------------------------------
class FLState:
    """What the page shows. The MQTT thread changes it, the web server reads it."""

    def __init__(self, boards, skip=(), total_rounds=None, broker=("fognode1.local", 1883)):
        self.lock = threading.Lock()
        self.names = {fl_id: name for name, fl_id in boards}           # every board of the table
        self.expected = [fl_id for name, fl_id in boards if name not in skip]
        self.boards = {fl_id: self._new_board(fl_id, expected=True) for fl_id in self.expected}
        self.total_rounds = total_rounds        # from --rounds; None = not given, 0 = no limit
        self.broker = {"host": broker[0], "port": broker[1], "connected": False,
                       "since": None, "error": None}
        self.run = None        # the run we follow: id, state, round, last_message, finished
        self.rounds = []       # its rounds, oldest first

    def _new_board(self, fl_id, expected):
        return {"name": self.names.get(fl_id, fl_id), "fl_id": fl_id, "expected": expected,
                "status": "unknown", "stored": None, "seen": None, "seen_what": None}

    def _board(self, fl_id, create):
        """The board's entry. A board we don't show gets one only if create is True."""
        if fl_id not in self.boards and create:
            self.boards[fl_id] = self._new_board(fl_id, expected=False)
        return self.boards.get(fl_id)

    # ---- Called by the MQTT listener ----

    def set_broker(self, connected, now, error=None):
        """The broker connection came or went."""
        with self.lock:
            if connected != self.broker["connected"] or self.broker["since"] is None:
                self.broker["since"] = now
            self.broker.update(connected=connected, error=error)

    def on_message(self, topic, payload, retained, now):
        """One MQTT message (payload: bytes) that arrived at time now."""
        text = payload.decode("utf-8", errors="replace")
        with self.lock:
            if topic == MODEL_TOPIC:
                self._on_model(text, retained, now)
                return
            parts = topic.split("/")
            if len(parts) != 3 or parts[0] != "fog" or not parts[1].startswith("esp32-"):
                return                      # e.g. the sensor firmware's fog/client1/... topics
            if parts[2] == "status":
                self._on_status(parts[1], text, retained, now)
            elif parts[2] == "update":
                self._on_update(parts[1], text, retained, now)

    # ---- Statuses ----

    def _on_status(self, fl_id, text, retained, now):
        board = self._board(fl_id, create=not retained)
        if board is None:
            return                          # an old stored status of a board we don't show
        board["stored"] = text or None      # the broker stores every status
        if retained:
            # Stored and live disagree: it changed while we were not listening
            if board["status"] != "unknown" and board["status"] != text:
                board["status"] = "unknown"
            return
        board["status"] = text if text in ("online", "offline") else "unknown"
        board["seen"], board["seen_what"] = now, f"status {text or '(cleared)'}"

    # ---- Updates ----

    def _on_update(self, fl_id, text, retained, now):
        if retained:
            return                          # updates are never stored; an old one tells nothing
        board = self._board(fl_id, create=True)
        board["status"] = "online"          # it just sent something, so it is online
        board["seen"] = now
        update = parse_update(text)
        if update is None:
            board["seen_what"] = "update (not usable)"
            return
        board["seen_what"] = f"update for round {update['round']}"

        current = self.rounds[-1] if self.rounds else None
        if (current is None or current["closed"] or update["run"] != self.run["id"]
                or update["round"] != current["round"]):
            return                          # another run or round: not counted
        current["updates"][fl_id] = {"time": now, "num_samples": update["num_samples"],
                                     "loss": update["loss"], "loss_before": update["loss_before"]}
        # A live update for the round: the run is going on, even if we only had the stored model
        self.run.update(state="running", last_message=now)

    # ---- The global model: rounds and runs ----

    def _on_model(self, text, retained, now):
        if not text:
            # The aggregator clears the model after its last round: the run is over.
            # (The broker never sends a cleared model as a stored one.)
            if self.run and self.run["state"] in ("running", "stale"):
                self._close_round()
                self.run.update(state="finished", finished=now, last_message=now)
            return
        model = parse_model(text)
        if model is None:
            return
        run_id, number = model

        if retained:
            # Stored before we subscribed: the run may still be going, or be long over
            if self.run is None or self.run["id"] != run_id:
                self._start_run(run_id, "stale")
                self.rounds.append(new_round(number, model_time=None))
                self.run["round"] = number
            return

        # A live model: this round starts now
        current = self.rounds[-1] if self.rounds else None
        if self.run is None or self.run["id"] != run_id:
            self._start_run(run_id, "running")
        elif current and current["round"] == number and not current["closed"]:
            self.run.update(state="running", last_message=now)   # the same round again
            return
        self._close_round()
        self.rounds.append(new_round(number, model_time=now))
        self.run.update(state="running", round=number, last_message=now)

    def _start_run(self, run_id, state):
        """A new run: forget the rounds of the previous one. The run ID is its start time."""
        self.run = {"id": run_id, "state": state, "round": None,
                    "last_message": None, "finished": None}
        self.rounds = []

    def _close_round(self):
        if self.rounds and not self.rounds[-1]["closed"]:
            self.rounds[-1]["closed"] = True

    # ---- Read by the web server ----

    def snapshot(self, now):
        """Everything the page needs, as plain JSON types."""
        with self.lock:
            order = {fl_id: i for i, fl_id in enumerate(self.expected)}
            boards = sorted(self.boards.values(),
                            key=lambda b: (order.get(b["fl_id"], len(order)), b["fl_id"]))
            return {
                "now": now,
                "broker": dict(self.broker),
                "boards": [dict(b) for b in boards],
                "expected": len(self.expected),
                "total_rounds": self.total_rounds,
                "run": dict(self.run) if self.run else None,
                "rounds": [self._summary(r) for r in self.rounds],
            }

    def _summary(self, r):
        """One row of the rounds table."""
        updates = list(r["updates"].values())
        samples = sum(u["num_samples"] for u in updates)

        def weighted(key):                  # as weighted_mean() in the aggregator
            return sum(u[key] * u["num_samples"] for u in updates) / samples if updates else None

        last = max((u["time"] for u in updates), default=None)
        known_start = last is not None and r["model_time"] is not None
        return {
            "round": r["round"],
            "in_progress": not r["closed"],
            "answered": len(updates),
            "answered_names": [self.boards[fl_id]["name"] for fl_id in r["updates"]],
            "missing": [self.boards[fl_id]["name"] for fl_id in self.expected
                        if fl_id not in r["updates"]],
            "round_s": last - r["model_time"] if known_start else None,
            "global_loss": weighted("loss_before"),
            "avg_loss": weighted("loss"),
        }
