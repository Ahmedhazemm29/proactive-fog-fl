"""
FL aggregator on the fog node (Raspberry Pi): FedAvg over the ESP32 clients.

First version, without secure aggregation: the aggregator sees every client's
weights. The clients (esp32/src/fl/main.cpp) talk MQTT:
    fog/<id>/status   "online-standby" or "online-active" (retained); "offline" is
                      the clients' Last Will. The old firmware's plain "online"
                      counts as active.
    fog/<id>/control  "join" or "leave" from hardware/tools/fl_control.py, never
                      retained. Every board starts in standby.
    fog/<id>/update   {"run", "round", "weights", "num_samples", "loss", "loss_before"}
The aggregator publishes:
    fog/global/model  {"run", "round", "rounds", "weights"}, retained so that a
                      client that connects late gets it too
    fog/global/round  for the dashboard (fl_dashboard/), not retained:
                      {"phase": "start", "run", "round", "rounds", "participants"}
                      {"phase": "end", ...the round's results, see round_summary()}

Each round:
    1. wait until at least MIN_CLIENTS clients are active
    2. the clients active now are the round's participants; a client that
       joins later waits for the next round
    3. publish the global model with the round number
    4. wait for an update from every participant, at most ROUND_TIMEOUT_S
       seconds; a participant that leaves or goes offline is dropped from the
       round at once, together with its update if it already sent one
    5. FedAvg: the new global weights are the participants' weights averaged,
       weighted by their num_samples
    6. log the round, then go on with the next round
After ROUNDS rounds (0 = no limit) it clears the retained model and stops.

"run" is the aggregator's start time. Clients train again when the run
changes, so a restarted aggregator can start at round 1 again.

Losses (mean squared error on the clients' own data, weighted by num_samples):
    global loss   of the global model sent in this round (before local training)
    avg loss      of the clients' models after local training

Logs: one line per round on stdout, and one folder per run, DATA_DIR/<run>/:
    rounds.csv    one row per round
    updates.csv   one row per client update
One folder per run, so a new column never ends up under an older file's
header. Runs from before join/leave are in DATA_DIR/rounds.csv and updates.csv.
"""
import csv
import json
import os
import threading
import time
from datetime import datetime

import paho.mqtt.client as mqtt

MQTT_HOST = os.getenv("MQTT_HOST", "fognode1.local")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
ROUNDS = int(os.getenv("ROUNDS", "0"))                   # 0 = keep going
MIN_CLIENTS = int(os.getenv("MIN_CLIENTS", "1"))         # active clients needed for a round
ROUND_TIMEOUT_S = float(os.getenv("ROUND_TIMEOUT_S", "10"))
PAUSE_S = float(os.getenv("PAUSE_S", "1"))               # between two rounds
DATA_DIR = os.getenv("DATA_DIR", "/data")

MODEL_TOPIC = "fog/global/model"
ROUND_TOPIC = "fog/global/round"
NUM_WEIGHTS = 5                                          # bias + 4 weights

# Statuses that mean "takes part in the rounds". Plain "online" comes from the
# old firmware without join/leave, which always trained.
ACTIVE_STATUSES = ("online-active", "online")

# The MQTT thread and the main loop both print. print() writes the text and the
# newline separately, so two threads could glue their lines together: one lock.
LOG_LOCK = threading.Lock()


def log(line):
    """Print one whole line, never mixed with another thread's."""
    with LOG_LOCK:
        print(line, flush=True)


# ----------------------------------------------------------------------
# Messages and FedAvg (no MQTT here, so they can be tested on their own)
# ----------------------------------------------------------------------
def client_of(topic):
    """fog/esp32-a1b2/update -> "esp32-a1b2"."""
    return topic.split("/")[1]


def parse_update(payload):
    """The update as a dict, or None if it can't be used."""
    try:
        update = json.loads(payload)
        ok = (len(update["weights"]) == NUM_WEIGHTS and update["num_samples"] > 0
              and all(isinstance(w, (int, float)) for w in update["weights"]))
        return update if ok else None
    except (ValueError, KeyError, TypeError):
        return None


def fedavg(updates):
    """The clients' weights averaged, weighted by num_samples. updates: list of update dicts."""
    total = sum(u["num_samples"] for u in updates)
    return [sum(u["weights"][i] * u["num_samples"] for u in updates) / total
            for i in range(NUM_WEIGHTS)]


def weighted_mean(updates, key):
    """Mean of updates[...][key], weighted by num_samples."""
    total = sum(u["num_samples"] for u in updates)
    return sum(u[key] * u["num_samples"] for u in updates) / total


# ----------------------------------------------------------------------
# One round's results: the log line, rounds.csv and fog/global/round
# ----------------------------------------------------------------------
def round_summary(run, number, rounds, participants, updates, missed, dropped, seconds):
    """
    The round's results as plain JSON types. participants: the clients active
    when the round started; updates: participant -> update of those that
    answered (and stayed); missed: still active but no update in time;
    dropped: left or went offline during the round. A round where nobody
    answered is "empty": its losses are None and the model stays the same.
    """
    used = list(updates.values())
    return {
        "run": run, "round": number, "rounds": rounds,
        "participants": sorted(participants), "answered": sorted(updates),
        "missed": sorted(missed), "dropped": sorted(dropped),
        "round_s": round(seconds, 3),
        "empty": not used,
        "global_loss": weighted_mean(used, "loss_before") if used else None,
        "avg_loss": weighted_mean(used, "loss") if used else None,
    }


def log_line(summary):
    """The round's line on stdout."""
    def loss(value):
        return "nan" if value is None else f"{value:.4f}"

    note = ""
    if summary["missed"]:
        note += f", no update from {', '.join(summary['missed'])}"
    if summary["dropped"]:
        note += f", left during the round: {', '.join(summary['dropped'])}"
    prefix = "EMPTY " if summary["empty"] else ""   # nobody answered: the model did not change
    return (f"{prefix}round {summary['round']}: {len(summary['answered'])} of "
            f"{len(summary['participants'])} active clients, {summary['round_s']:.2f} s, "
            f"global loss {loss(summary['global_loss'])}, avg loss {loss(summary['avg_loss'])}{note}")


def rounds_row(summary, weights):
    """The round's row of rounds.csv. active: participants when the round started;
    empty: True when nobody answered (losses NaN, weights unchanged)."""
    nan = float("nan")
    return {
        "run": summary["run"], "round": summary["round"],
        "time": datetime.now().isoformat(timespec="seconds"),
        "active": len(summary["participants"]), "clients": len(summary["answered"]),
        "missed": len(summary["missed"]), "dropped": len(summary["dropped"]),
        "empty": summary["empty"],
        "round_s": summary["round_s"],
        "global_loss": nan if summary["global_loss"] is None else summary["global_loss"],
        "avg_loss": nan if summary["avg_loss"] is None else summary["avg_loss"],
        "weights": json.dumps(weights),
    }


# ----------------------------------------------------------------------
# Who is active, and the current round
# ----------------------------------------------------------------------
class RoundState:
    """
    Shared by the MQTT thread (status messages and updates come in) and the
    main loop (rounds). The condition wakes the main loop on every change.
    """

    def __init__(self, run):
        self.run = run
        self.round = 0
        self.active = set()             # clients that take part in the rounds
        self.participants = set()       # the clients active when this round started
        self.dropped = set()            # participants that left during this round
        self.updates = {}               # participant -> update, this round only
        self.changed = threading.Condition()

    def on_status(self, client, text):
        """A status message. Returns True if the client became active or stopped being active."""
        with self.changed:
            was_active = client in self.active
            if text in ACTIVE_STATUSES:
                self.active.add(client)     # takes part from the next round on
            else:                           # "online-standby", "offline", or the status was cleared
                self.active.discard(client)
                if client in self.participants:
                    # Left during the round: no more waiting for it, and its update is dropped too
                    self.participants.discard(client)
                    self.updates.pop(client, None)
                    self.dropped.add(client)
            self.changed.notify_all()
            return was_active != (client in self.active)

    def on_update(self, client, update):
        """Keep a participant's update of the current round; returns False for any other."""
        with self.changed:
            if (update.get("run") != self.run or update.get("round") != self.round
                    or client not in self.participants):
                return False
            self.updates[client] = update
            self.changed.notify_all()
            return True

    def start_round(self, number):
        """A new round: the clients active now are its participants. Returns them."""
        with self.changed:
            self.round = number
            self.participants = set(self.active)
            self.dropped = set()
            self.updates = {}
            return set(self.participants)

    def missing(self):
        """Participants without an update in this round."""
        return self.participants - set(self.updates)

    def wait_for_clients(self, count):
        with self.changed:
            while len(self.active) < count:
                log(f"waiting for clients: {len(self.active)} of {count} active")
                self.changed.wait(timeout=10)

    def wait_for_updates(self, timeout):
        """
        Wait until every participant has answered or left, or the timeout.
        Returns (updates, missed, dropped).
        """
        deadline = time.monotonic() + timeout
        with self.changed:
            while self.missing():
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                self.changed.wait(timeout=left)
            return dict(self.updates), set(self.missing()), set(self.dropped)


# ----------------------------------------------------------------------
# CSV logs
# ----------------------------------------------------------------------
def append_csv(path, row):
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(row))
        if new:
            writer.writeheader()
        writer.writerow(row)


# ----------------------------------------------------------------------
# Main loop
# ----------------------------------------------------------------------
def main():
    run = int(time.time())
    state = RoundState(run)
    weights = [0.0] * NUM_WEIGHTS       # round 1 starts from zeros
    run_dir = os.path.join(DATA_DIR, str(run))
    os.makedirs(run_dir, exist_ok=True)

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log(f"mqtt: connect failed: {reason_code}")
            return
        # Subscribe again after every connect: the broker forgets it on a drop
        client.subscribe([("fog/+/status", 1), ("fog/+/update", 1)])
        log(f"mqtt: connected to {MQTT_HOST}:{MQTT_PORT}")

    def on_message(client, userdata, message):
        if not message.topic.startswith("fog/esp32-"):
            return                      # e.g. the sensor firmware's fog/client1/... topics
        sender = client_of(message.topic)
        if message.topic.endswith("/status"):
            text = message.payload.decode(errors="replace")
            if state.on_status(sender, text):
                log(f"status: {sender} is now {text or '(cleared)'}")
        elif message.topic.endswith("/update"):
            update = parse_update(message.payload)
            if update is None:
                log(f"bad update from {sender}: {message.payload[:80]!r}")
            elif not state.on_update(sender, update):
                log(f"update from {sender} (round {update.get('round')}) ignored: "
                    "another round, or not a participant")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="fl-aggregator")
    client.on_connect = on_connect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=5)
    client.connect_async(MQTT_HOST, MQTT_PORT)
    client.loop_start()
    log(f"aggregator: run {run}, rounds {ROUNDS or 'no limit'}, at least {MIN_CLIENTS} active "
        f"client(s), round timeout {ROUND_TIMEOUT_S:g} s, data in {run_dir}")

    number = 0
    while ROUNDS == 0 or number < ROUNDS:
        number += 1
        state.wait_for_clients(MIN_CLIENTS)
        participants = state.start_round(number)
        started = time.monotonic()
        client.publish(MODEL_TOPIC, json.dumps({"run": run, "round": number, "rounds": ROUNDS,
                                                "weights": weights}), qos=1, retain=True)
        client.publish(ROUND_TOPIC, json.dumps({"phase": "start", "run": run, "round": number,
                                                "rounds": ROUNDS,
                                                "participants": sorted(participants)}), qos=1)

        updates, missed, dropped = state.wait_for_updates(ROUND_TIMEOUT_S)
        summary = round_summary(run, number, ROUNDS, participants, updates, missed, dropped,
                                time.monotonic() - started)
        if updates:
            weights = fedavg(list(updates.values()))   # nobody answered: keep the model
        log(log_line(summary))
        append_csv(os.path.join(run_dir, "rounds.csv"), rounds_row(summary, weights))
        for sender, u in sorted(updates.items()):
            append_csv(os.path.join(run_dir, "updates.csv"), {
                "run": run, "round": number, "client": sender, "num_samples": u["num_samples"],
                "loss": u["loss"], "loss_before": u["loss_before"]})
        client.publish(ROUND_TOPIC, json.dumps({"phase": "end", **summary}), qos=1)
        time.sleep(PAUSE_S)

    # Done: clear the retained model, so no client trains an old round again
    client.publish(MODEL_TOPIC, payload=None, qos=1, retain=True).wait_for_publish(timeout=5)
    client.loop_stop()
    client.disconnect()
    log(f"aggregator: {number} rounds done, final weights {[round(w, 4) for w in weights]}")


if __name__ == "__main__":
    main()
