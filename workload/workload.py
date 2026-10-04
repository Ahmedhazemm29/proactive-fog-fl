"""
Training workload with a controllable CPU demand (a "load profile").

Every 1-second slot the worker is busy for `intensity` seconds, training an
SGD classifier on the sklearn digits dataset, and sleeps for the rest.
Intensity 0.6 means it wants 0.6 CPU on average, but in bursts: while busy
it runs flat out on one core.

How busy it should be comes from a small JSON file (LOAD_FILE), re-read
every second, so a change applies live. Change it with scripts/set_load.py.
Modes and their parameters (times in seconds, levels from 0.0 to 1.0):

    sine        period, min, max, phase            (default 120, 0.1, 1.0, 0)
    noisy_sine  like sine, plus noise (strength = standard deviation),
                hold (seconds each noise value lasts) and seed
    bursts      base (baseline), height (spike level), duration (of a spike),
                gap (average pause between spikes) and seed
    steps       steps = [[at, level], ...], repeat (seconds, 0 = no repeat)
    constant    level

Time t of a profile counts from the moment the worker picks it up, so
setting the same profile again replays it from the start. Seeded modes give
exactly the same load every time they are replayed.

Without a load file the worker runs the default 120 s sine wave.

Logs:
    every second:   load t=12 mode=bursts intensity=1.000
                    the intended intensity: ground truth for the analysis
    every 10 s:     t=   120s intensity=0.55 steps/s=  139.5 acc=0.986
                    training speed; drops when the CPU limit is too low
"""
import json
import math
import os
import random
import time

import numpy as np
from sklearn.datasets import load_digits
from sklearn.linear_model import SGDClassifier

LOAD_FILE = os.getenv("LOAD_FILE", "/load/profile.json")
BATCH = int(os.getenv("BATCH", "256"))
LOG_EVERY = int(os.getenv("LOG_EVERY_S", "10"))

# Used until a valid load file appears: the original 120 s sine wave.
DEFAULT_PROFILE = {"mode": "sine", "period": 120, "min": 0.1, "max": 1.0, "phase": 0}


# ----------------------------------------------------------------------
# Load modes: each one returns the intensity at time t of the profile
# ----------------------------------------------------------------------
def sine(p, t):
    """Smooth wave between min and max, one full wave every `period` seconds."""
    wave = (math.sin(2 * math.pi * (t + p.get("phase", 0)) / p.get("period", 120)) + 1) / 2
    low, high = p.get("min", 0.1), p.get("max", 1.0)
    return low + (high - low) * wave


def noisy_sine(p, t):
    """The sine wave plus random noise, with a new noise value every `hold` s."""
    block = int(t // p.get("hold", 1))
    # A random generator made from (seed, block): the same noise every time
    # the profile is replayed, without remembering anything between seconds.
    rng = random.Random(p.get("seed", 0) * 1_000_003 + block)
    return sine(p, t) + rng.gauss(0, p.get("noise", 0.1))


def bursts(p, t):
    """
    Low baseline with sudden spikes. The pause before each spike is random
    (on average `gap` s) and every spike lasts `duration` s. The spike times
    are drawn from `seed`, so the same seed always gives the same spikes.
    """
    gap, duration = p.get("gap", 60), p.get("duration", 20)
    rng = random.Random(p.get("seed", 0))
    spike_start = rng.expovariate(1 / gap)          # first spike
    while spike_start + duration <= t:              # that spike is over already:
        spike_start += duration + rng.expovariate(1 / gap)   # go to the next one
    if spike_start <= t:
        return p.get("height", 1.0)
    return p.get("base", 0.1)


def steps(p, t):
    """Fixed levels from fixed times, e.g. steps = [[0, 0.2], [60, 0.9]]."""
    schedule = sorted(p["steps"])
    if p.get("repeat", 0) > 0:
        t = t % p["repeat"]        # start the schedule again every `repeat` s
    level = schedule[0][1]
    for at, value in schedule:
        if t >= at:
            level = value
    return level


def constant(p, t):
    """One fixed level."""
    return p.get("level", 0.5)


MODES = {"sine": sine, "noisy_sine": noisy_sine, "bursts": bursts,
         "steps": steps, "constant": constant}


def intensity_at(profile, t):
    """Intended intensity, kept between 0.0 and 1.0 (one core flat out at most)."""
    value = MODES[profile["mode"]](profile, t)
    return min(1.0, max(0.0, value))


# ----------------------------------------------------------------------
# Reading the load file
# ----------------------------------------------------------------------
def check_profile(profile):
    """Raise an error if the profile can't be used, so a typo never stops the worker."""
    if profile.get("mode") not in MODES:
        raise ValueError(f"unknown mode {profile.get('mode')!r}, use one of {', '.join(MODES)}")
    for key in ("period", "hold", "gap", "duration"):
        if key in profile and not profile[key] >= 1:
            raise ValueError(f"{key} must be at least 1 second")
    intensity_at(profile, 0.0)  # try it once: missing or wrong values fail here


def read_profile():
    """
    Return (profile, problem). profile is None if the file is missing or
    can't be used; the worker then keeps its current profile.
    """
    try:
        with open(LOAD_FILE) as f:
            profile = json.load(f)
        check_profile(profile)
        return profile, None
    except FileNotFoundError:
        return None, None
    except Exception as error:  # broken JSON, unknown mode, bad values, ...
        return None, f"{LOAD_FILE}: {error}"


# ----------------------------------------------------------------------
# Main loop: one slot per second
# ----------------------------------------------------------------------
def main():
    X, y = load_digits(return_X_y=True)
    X = X / 16.0
    classes = np.unique(y)
    clf = SGDClassifier(loss="log_loss")
    rng = np.random.default_rng(0)

    profile = None       # set in the first second: the load file or the default
    last_problem = None

    # time.monotonic() only counts forward. The wall clock (time.time()) can
    # jump by hours, e.g. when it is corrected after a boot, and a worker
    # timed by it would then sleep or spin for hours.
    started = time.monotonic()
    profile_start = started
    slot = 0
    steps_window = 0

    while True:
        slot_start = time.monotonic()

        # 1. Follow the load file. A changed profile starts again at t = 0.
        new_profile, problem = read_profile()
        if problem and problem != last_problem:
            print(f"load file problem, keeping the current profile: {problem}")
        last_problem = problem
        if profile is None and new_profile is None:   # no usable file at start
            new_profile = DEFAULT_PROFILE
        if new_profile is not None and new_profile != profile:
            profile = new_profile
            profile_start = slot_start
            note = " (default, no load file)" if profile is DEFAULT_PROFILE else ""
            print(f"load profile: {json.dumps(profile)}{note}")

        # 2. How busy to be in this second, logged as ground truth.
        t = slot_start - profile_start
        intensity = intensity_at(profile, t)
        print(f"load t={t:.0f} mode={profile['mode']} intensity={intensity:.3f}")

        # 3. Train flat out for `intensity` seconds.
        busy_until = slot_start + intensity
        while time.monotonic() < busy_until:
            idx = rng.integers(0, len(X), BATCH)
            clf.partial_fit(X[idx], y[idx], classes=classes)
            steps_window += 1

        # 4. Every LOG_EVERY seconds: training speed (analysis/compare_runs.py reads it).
        slot += 1
        if slot % LOG_EVERY == 0:
            acc = clf.score(X, y)
            print(f"t={slot_start - started:6.0f}s intensity={intensity:.2f} "
                  f"steps/s={steps_window / LOG_EVERY:7.1f} acc={acc:.3f}")
            steps_window = 0

        # 5. Sleep for the rest of the second.
        time.sleep(max(0.0, slot_start + 1.0 - time.monotonic()))


if __name__ == "__main__":
    main()
