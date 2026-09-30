"""
Lightweight training workload with a predictable, time-varying CPU demand.

Every 1-second slot, the worker wants to be busy for `intensity` seconds
(training an SGD classifier on the sklearn digits dataset) and idle for the rest.
Intensity follows a sine wave, so there is a pattern a forecaster can learn.

If the container's CPU cap is below the demand, throughput (steps/s) drops.
That drop is the "cost" of under-allocation you will measure later.
"""
import math
import os
import time

import numpy as np
from sklearn.datasets import load_digits
from sklearn.linear_model import SGDClassifier

PERIOD = float(os.getenv("PERIOD_S", "120"))
BATCH = int(os.getenv("BATCH", "256"))
LOG_EVERY = int(os.getenv("LOG_EVERY_S", "10"))

X, y = load_digits(return_X_y=True)
X = X / 16.0
classes = np.unique(y)
clf = SGDClassifier(loss="log_loss")
rng = np.random.default_rng(0)

t0 = time.time()
slot = 0
steps_window = 0

while True:
    slot_start = time.time()
    t = slot_start - t0
    intensity = 0.1 + 0.9 * (math.sin(2 * math.pi * t / PERIOD) + 1) / 2

    busy_until = slot_start + intensity
    while time.time() < busy_until:
        idx = rng.integers(0, len(X), BATCH)
        clf.partial_fit(X[idx], y[idx], classes=classes)
        steps_window += 1

    slot += 1
    if slot % LOG_EVERY == 0:
        acc = clf.score(X, y)
        print(f"t={t:6.0f}s intensity={intensity:.2f} "
              f"steps/s={steps_window / LOG_EVERY:7.1f} acc={acc:.3f}")
        steps_window = 0

    time.sleep(max(0.0, slot_start + 1.0 - time.time()))
