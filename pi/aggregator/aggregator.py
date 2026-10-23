"""
FL aggregator on the fog node (Raspberry Pi): FedAvg over the ESP32 clients.

First version, without secure aggregation: the aggregator sees every client's
weights. The clients (esp32/src/fl/main.cpp) talk MQTT:
    fog/<id>/status   "online" or "offline" (retained; "offline" is the clients' Last Will)
    fog/<id>/update   {"run", "round", "weights", "num_samples", "loss", "loss_before"}
The aggregator publishes, retained so that a client that joins late gets it too:
    fog/global/model  {"run", "round", "weights"}

Each round:
    1. wait until at least MIN_CLIENTS clients are online
    2. publish the global model with the round number
    3. wait for an update from every online client, at most ROUND_TIMEOUT_S
       seconds; a client that goes offline is no longer waited for
    4. FedAvg: the new global weights are the clients' weights averaged,
       weighted by their num_samples
    5. log the round, the clients, the round time and the losses, then go on
       with the next round
After ROUNDS rounds (0 = no limit) it clears the retained model and stops.

"run" is the aggregator's start time. Clients train again when the run
changes, so a restarted aggregator can start at round 1 again.

Losses (mean squared error on the clients' own data, weighted by num_samples):
    global loss   of the global model sent in this round (before local training)
    avg loss      of the clients' models after local training

Logs: one line per round on stdout, and CSV files in DATA_DIR:
    rounds.csv    one row per round
    updates.csv   one row per client update
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
MIN_CLIENTS = int(os.getenv("MIN_CLIENTS", "1"))
ROUND_TIMEOUT_S = float(os.getenv("ROUND_TIMEOUT_S", "10"))
PAUSE_S = float(os.getenv("PAUSE_S", "1"))               # between two rounds
DATA_DIR = os.getenv("DATA_DIR", "/data")

MODEL_TOPIC = "fog/global/model"
NUM_WEIGHTS = 5                                          # bias + 4 weights


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
# Who is online, and the updates of the current round
# ----------------------------------------------------------------------
class RoundState:
    """
    Shared by the MQTT thread (status messages and updates come in) and the
    main loop (rounds). The condition wakes the main loop on every change.
    """

    def __init__(self, run):
        self.run = run
        self.round = 0
        self.online = set()
        self.updates = {}               # client -> update, current round only
        self.changed = threading.Condition()

    def on_status(self, client, text):
        with self.changed:
            if text == "online":
                self.online.add(client)
            else:                       # "offline", or the retained status was cleared
                self.online.discard(client)
            self.changed.notify_all()

    def on_update(self, client, update):
        """Keep an update of the current round; returns False for an old or foreign one."""
        with self.changed:
            if update.get("run") != self.run or update.get("round") != self.round:
                return False
            self.updates[client] = update
            self.online.add(client)     # it sent an update, so it is online
            self.changed.notify_all()
            return True

    def start_round(self, number):
        with self.changed:
            self.round = number
            self.updates = {}

    def missing(self):
        """Online clients without an update in this round."""
        return self.online - set(self.updates)

    def wait_for_clients(self, count):
        with self.changed:
            while len(self.online) < count:
                print(f"waiting for clients: {len(self.online)} of {count} online", flush=True)
                self.changed.wait(timeout=10)

    def wait_for_updates(self, timeout):
        """Wait until every online client has sent its update, or the timeout. Returns the updates."""
        deadline = time.monotonic() + timeout
        with self.changed:
            while self.missing():
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                self.changed.wait(timeout=left)
            return dict(self.updates), set(self.missing())


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
    os.makedirs(DATA_DIR, exist_ok=True)

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            print(f"mqtt: connect failed: {reason_code}", flush=True)
            return
        # Subscribe again after every connect: the broker forgets it on a drop
        client.subscribe([("fog/+/status", 1), ("fog/+/update", 1)])
        print(f"mqtt: connected to {MQTT_HOST}:{MQTT_PORT}", flush=True)

    def on_message(client, userdata, message):
        if not message.topic.startswith("fog/esp32-"):
            return                      # e.g. the sensor firmware's fog/client1/... topics
        sender = client_of(message.topic)
        if message.topic.endswith("/status"):
            state.on_status(sender, message.payload.decode(errors="replace"))
        elif message.topic.endswith("/update"):
            update = parse_update(message.payload)
            if update is None:
                print(f"bad update from {sender}: {message.payload[:80]!r}", flush=True)
            elif not state.on_update(sender, update):
                print(f"old update from {sender} (round {update.get('round')}) ignored", flush=True)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="fl-aggregator")
    client.on_connect = on_connect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=5)
    client.connect_async(MQTT_HOST, MQTT_PORT)
    client.loop_start()
    print(f"aggregator: run {run}, rounds {ROUNDS or 'no limit'}, at least {MIN_CLIENTS} "
          f"client(s), round timeout {ROUND_TIMEOUT_S:g} s", flush=True)

    number = 0
    while ROUNDS == 0 or number < ROUNDS:
        number += 1
        state.wait_for_clients(MIN_CLIENTS)
        state.start_round(number)
        started = time.monotonic()
        client.publish(MODEL_TOPIC, json.dumps({"run": run, "round": number, "weights": weights}),
                       qos=1, retain=True)

        updates, missed = state.wait_for_updates(ROUND_TIMEOUT_S)
        seconds = time.monotonic() - started
        if updates:
            weights = fedavg(list(updates.values()))
            avg_loss = weighted_mean(list(updates.values()), "loss")
            global_loss = weighted_mean(list(updates.values()), "loss_before")
        else:
            avg_loss = global_loss = float("nan")   # nobody answered: keep the model

        note = f", no update from {', '.join(sorted(missed))}" if missed else ""
        print(f"round {number}: {len(updates)} clients, {seconds:.2f} s, global loss "
              f"{global_loss:.4f}, avg loss {avg_loss:.4f}{note}", flush=True)
        append_csv(os.path.join(DATA_DIR, "rounds.csv"), {
            "run": run, "round": number, "time": datetime.now().isoformat(timespec="seconds"),
            "clients": len(updates), "missed": len(missed), "round_s": round(seconds, 3),
            "global_loss": global_loss, "avg_loss": avg_loss, "weights": json.dumps(weights)})
        for sender, u in sorted(updates.items()):
            append_csv(os.path.join(DATA_DIR, "updates.csv"), {
                "run": run, "round": number, "client": sender, "num_samples": u["num_samples"],
                "loss": u["loss"], "loss_before": u["loss_before"]})
        time.sleep(PAUSE_S)

    # Done: clear the retained model, so no client trains an old round again
    client.publish(MODEL_TOPIC, payload=None, qos=1, retain=True).wait_for_publish(timeout=5)
    client.loop_stop()
    client.disconnect()
    print(f"aggregator: {number} rounds done, final weights {[round(w, 4) for w in weights]}",
          flush=True)


if __name__ == "__main__":
    main()
