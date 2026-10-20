"""
MQTT worker: trains on live sensor data from an ESP32 fog client.

workload.py follows a programmed load profile. This worker instead subscribes
to fog/client<CLIENT_ID>/data, keeps the last BUFFER_SIZE sensor values and
runs STEPS_PER_MSG training steps for every message that arrives. So its CPU
demand grows with the ESP32's publish rate, which can be changed live:

    mosquitto_pub -h fognode1.local -t fog/client1/control -m 30

The training step is the one of workload.py: SGDClassifier.partial_fit on a
batch of BATCH samples. Here a sample is a window of WINDOW consecutive
sensor values, and the label says whether the next value is higher.

Steps that can't be done right away wait in a backlog of at most MAX_BACKLOG
steps; steps beyond that are dropped (and counted). A worker whose CPU limit
is too low is therefore busy all the time, which shows up as throttling in
cAdvisor, like the profile workers.

Settings (environment variables, defaults in brackets):
    CLIENT_ID [1], MQTT_HOST [fognode1.local], MQTT_PORT [1883],
    STEPS_PER_MSG [10], BATCH [256], WINDOW [8], BUFFER_SIZE [2000],
    MAX_BACKLOG [2000], METRICS_PORT [8000], LOG_EVERY_S [10]

Logs every LOG_EVERY_S seconds (steps/s= as in workload.py, so
analysis/compare_runs.py can read it):
    t=   120s msgs/s=  30.0 steps/s=  300.0 backlog=0 dropped=0 acc=0.712

Prometheus page on :METRICS_PORT/metrics, next to cAdvisor's container metrics:
    fog_messages_received_total   messages received so far
    fog_messages_per_second       messages per second over the last log window
    fog_training_steps_total      training steps done so far
    fog_backlog_steps             steps waiting to be done
"""
import json
import os
import threading
import time
from collections import deque

import numpy as np
import paho.mqtt.client as mqtt
from prometheus_client import Counter, Gauge, start_http_server
from sklearn.linear_model import SGDClassifier

CLIENT_ID = int(os.getenv("CLIENT_ID", "1"))
MQTT_HOST = os.getenv("MQTT_HOST", "fognode1.local")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
STEPS_PER_MSG = int(os.getenv("STEPS_PER_MSG", "10"))
BATCH = int(os.getenv("BATCH", "256"))
WINDOW = int(os.getenv("WINDOW", "8"))
BUFFER_SIZE = int(os.getenv("BUFFER_SIZE", "2000"))
MAX_BACKLOG = int(os.getenv("MAX_BACKLOG", "2000"))
METRICS_PORT = int(os.getenv("METRICS_PORT", "8000"))
LOG_EVERY = int(os.getenv("LOG_EVERY_S", "10"))

TOPIC = f"fog/client{CLIENT_ID}/data"
CLASSES = np.array([0, 1])   # 0 = next value not higher, 1 = higher

# Prometheus metrics
MESSAGES = Counter("fog_messages_received", "Messages received from the ESP32")
MESSAGES_PER_S = Gauge("fog_messages_per_second", "Messages per second over the last log window")
STEPS = Counter("fog_training_steps", "Training steps done")
BACKLOG = Gauge("fog_backlog_steps", "Training steps waiting to be done")

# State shared by the MQTT thread (adds work) and the main loop (does it).
# The lock makes sure the two never change it at the same moment.
lock = threading.Lock()
samples = deque(maxlen=BUFFER_SIZE)   # latest sensor values, oldest drop out
received = 0                          # messages received so far
backlog = 0                           # training steps still to do
dropped = 0                           # steps skipped because the backlog was full


# ----------------------------------------------------------------------
# Messages
# ----------------------------------------------------------------------
def parse_sensor(payload):
    """Sensor value from a message like {"sensor": 23.71, ...}, or None if unusable."""
    try:
        return float(json.loads(payload)["sensor"])
    except (ValueError, KeyError, TypeError):
        return None


def on_connect(client, userdata, flags, reason_code, properties):
    """Called after every (re)connect: subscribe again, the broker forgot it."""
    if reason_code.is_failure:
        print(f"mqtt: connect failed: {reason_code}")
        return
    client.subscribe(TOPIC)
    print(f"mqtt: connected to {MQTT_HOST}:{MQTT_PORT}, subscribed to {TOPIC}")


def on_disconnect(client, userdata, flags, reason_code, properties):
    print(f"mqtt: disconnected ({reason_code}), reconnecting ...")


def on_message(client, userdata, message):
    """Runs in the MQTT thread: store the value and add STEPS_PER_MSG steps of work."""
    global received, backlog, dropped
    value = parse_sensor(message.payload)
    if value is None:
        print(f"mqtt: ignored message {message.payload[:80]!r}")
        return
    with lock:
        samples.append(value)
        received += 1
        backlog += STEPS_PER_MSG
        if backlog > MAX_BACKLOG:          # too much work waiting: drop the rest
            dropped += backlog - MAX_BACKLOG
            backlog = MAX_BACKLOG
    MESSAGES.inc()


# ----------------------------------------------------------------------
# Training
# ----------------------------------------------------------------------
def make_batch(values, rng):
    """
    BATCH random windows from the sensor values (needs more than WINDOW values).
    X: WINDOW consecutive values minus their mean, so only the shape counts.
    y: 1 if the value right after the window is higher than its last value.
    """
    starts = rng.integers(0, len(values) - WINDOW, BATCH)
    windows = values[starts[:, None] + np.arange(WINDOW)]
    X = windows - windows.mean(axis=1, keepdims=True)
    y = (values[starts + WINDOW] > windows[:, -1]).astype(int)
    return X, y


def main():
    global backlog
    print(f"mqtt worker: client {CLIENT_ID}, {STEPS_PER_MSG} steps per message, "
          f"batch {BATCH}, window {WINDOW}")
    start_http_server(METRICS_PORT)

    # The MQTT client runs in its own thread and reconnects by itself.
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                         client_id=f"fl-worker-{CLIENT_ID}")
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=5)
    client.connect_async(MQTT_HOST, MQTT_PORT)
    client.loop_start()

    clf = SGDClassifier(loss="log_loss")
    rng = np.random.default_rng(0)

    # Timed with time.monotonic(), like workload.py: the wall clock can jump.
    started = time.monotonic()
    next_log = started + LOG_EVERY
    steps_window = 0
    messages_at_last_log = 0
    values = None        # the data of the latest training step
    acc = float("nan")

    while True:
        # 1. Take one step of work, if there is any and enough data.
        with lock:
            have_work = backlog > 0 and len(samples) > WINDOW
            if have_work:
                backlog -= 1
                values = np.array(samples)   # a copy: the MQTT thread keeps appending

        # 2. Do the training step, or wait a moment for new messages.
        if have_work:
            X, y = make_batch(values, rng)
            clf.partial_fit(X, y, classes=CLASSES)
            steps_window += 1
            STEPS.inc()
        else:
            time.sleep(0.005)

        # 3. Every LOG_EVERY seconds: rates, backlog and accuracy.
        now = time.monotonic()
        if now >= next_log:
            with lock:
                total, waiting, lost = received, backlog, dropped
            msgs_per_s = (total - messages_at_last_log) / LOG_EVERY
            messages_at_last_log = total
            if values is not None:   # score on a fresh batch, once the model has trained
                acc = clf.score(*make_batch(values, rng))
            MESSAGES_PER_S.set(msgs_per_s)
            BACKLOG.set(waiting)
            print(f"t={now - started:6.0f}s msgs/s={msgs_per_s:6.1f} "
                  f"steps/s={steps_window / LOG_EVERY:7.1f} backlog={waiting} "
                  f"dropped={lost} acc={acc:.3f}")
            steps_window = 0
            next_log += LOG_EVERY


if __name__ == "__main__":
    main()
