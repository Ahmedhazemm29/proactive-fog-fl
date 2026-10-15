"""
The scalers of Dogani & Khunjush (2024), simulated minute by minute.
No Docker or Kubernetes: a pod is just a number.

Time line: at the start of minute t a scaler may change the number of pods.
It knows the real traffic up to minute t-1. The proactive planner also gets a
forecast of minutes t .. t+4 (the predictors' t+1 .. t+5). New pods are ready
at once and serve minute t.

Cooldown (CDT): after a scale-up nothing may change for CDT_up minutes
(t .. t+2), after a scale-down for CDT_down minutes (t .. t+4). A decision
that keeps the pod count is not a scaling action and starts no cooldown.
"""
import math
from dataclasses import dataclass

import numpy as np


@dataclass
class Settings:
    """Planner parameters (paper Table 3, p. 10) and the no-autoscaling pod count (p. 17)."""
    workload_pod: float = 500     # requests per minute one pod can serve
    pods_min: int = 5
    cdt_up: int = 3               # minutes without rescaling after a scale-up
    cdt_down: int = 5             # minutes without rescaling after a scale-down
    sdr: float = 0.3              # scale-down rate: 30% of the extra pods stay
    fixed_pods: int = 15          # no autoscaling


def pods_for(load, workload_pod):
    """ceil(load / workload_pod). A forecast can be negative, so this can be 0 or less."""
    return math.ceil(load / workload_pod)


def requested_pods(real, workload_pod):
    """Pods the real traffic needs each minute: ceil(traffic / workload_pod), at least 1."""
    return np.maximum(np.ceil(np.asarray(real) / workload_pod), 1).astype(np.int64)


def run(decide, minutes, start_pods, s):
    """
    Step through `minutes` minutes. decide(t, current) gives the wanted pods
    at minute t. It is only asked when no cooldown is active.
    Returns (pods per minute, number of scale-ups, number of scale-downs).
    """
    pods = np.empty(minutes, dtype=np.int64)
    current, free_from, ups, downs = start_pods, 0, 0, 0
    for t in range(minutes):
        if t >= free_from:                       # CDT is not active (Algorithm 3, line 2)
            wanted = decide(t, current)
            if wanted > current:
                ups += 1
                free_from = t + s.cdt_up
            elif wanted < current:
                downs += 1
                free_from = t + s.cdt_down
            current = wanted
        pods[t] = current
    return pods, ups, downs


def no_autoscaling(minutes, s):
    """A fixed number of pods (p. 17)."""
    return np.full(minutes, s.fixed_pods, dtype=np.int64), 0, 0


def khpa(last_minute, s, start_pods):
    """
    KHPA (Algorithm 1, p. 5), reactive: the pods for the traffic of the minute
    just observed, at least Pods_min. last_minute[t] = real traffic of minute t-1.
    """
    def decide(t, current):
        return max(pods_for(last_minute[t], s.workload_pod), s.pods_min)
    return run(decide, len(last_minute), start_pods, s)


def planner_step(forecast, current, s):
    """
    One decision of the planner (Algorithm 3, p. 9).
    forecast = predicted traffic of minutes t .. t+4. Returns the new pod count.
    """
    wanted = pods_for(forecast[0], s.workload_pod)          # line 3: direction from the t+1 forecast
    if wanted > current:                                     # lines 4 to 8: scale up
        # Line 6 says W_max_ScaleDown; we read it as W_max_ScaleUp from line 5 (docs/decisions.md, entry 4A.4).
        return pods_for(float(np.max(forecast[:s.cdt_up])), s.workload_pod)
    if wanted < current:                                     # lines 9 to 15: scale down
        estimate = pods_for(float(np.max(forecast[:s.cdt_down])), s.workload_pod)
        # Remove only (1 - SDR) of the extra pods, rounded down.
        # The 1e-9 stops float error from turning e.g. 21.0 into 20.999...
        new = current - math.floor((current - estimate) * (1 - s.sdr) + 1e-9)
        new = max(new, s.pods_min)
        # A higher forecast later in the window can give new > current: keep the pods then.
        return min(new, current)
    return current


def planner(forecasts, s, start_pods):
    """The proactive planner with a forecast row (minutes t .. t+4) for every minute t."""
    return run(lambda t, current: planner_step(forecasts[t], current, s), len(forecasts), start_pods, s)
