"""
Scaler logic of the live demo (step 4B): one decision per step.

A step is one trace minute, replayed in 10 s. The rules are those of step 4A
(scalers.py), asked one step at a time instead of over a whole array:
- Stepper is scalers.run() for one step: same cooldowns, plus a cap (20 workers).
- KHPA decides from the real CPU of the last step, like Kubernetes' HPA with
  CPU request = limit: pods = ceil(total CPU / (0.5 x 0.7)), at least Pods_min.
  fresh_cpu() makes sure that CPU value is complete (docs/decisions.md, 4B.14).
- The planner is scalers.planner_step() unchanged, on the scaled forecasts.
"""
import math
import time

import numpy as np


class Stepper:
    """The cooldown loop of scalers.run(), asked once per step."""

    def __init__(self, start_pods, cdt_up, cdt_down, pods_max):
        self.pods = start_pods
        self.cdt_up, self.cdt_down, self.pods_max = cdt_up, cdt_down, pods_max
        self.free_from = 0           # first step without cooldown
        self.ups = self.downs = 0

    def step(self, t, decide):
        """Pods for step t. decide(current) gives the wanted pods; it is only asked without cooldown."""
        if t >= self.free_from:
            wanted = min(decide(self.pods), self.pods_max)
            if wanted > self.pods:
                self.ups += 1
                self.free_from = t + self.cdt_up
            elif wanted < self.pods:
                self.downs += 1
                self.free_from = t + self.cdt_down
            self.pods = wanted
        return self.pods


def fresh_cpu(last_scrape, cpu_at, step_start, timeout=8.0, poll=0.1, clock=time.time, sleep=time.sleep):
    """
    KHPA's CPU at the start of a step, from a complete rate window.

    Prometheus scrapes cAdvisor every 5 s. Asked right at the step start, the
    newest scrape is often not stored yet, and rate() over 15 s then sees 2
    samples instead of 3 and reads too low. So:
    1. wait until Prometheus has stored a scrape from after step_start
       (last_scrape() gives the newest scrape time), at most `timeout` seconds;
    2. evaluate the query at that scrape's own time (cpu_at(time)), so the
       window holds that scrape and the two before it.
    Returns (cpu, scrape time, seconds waited, fresh). fresh is False when the
    timeout passed first; the value then comes from the newest stored scrape.
    """
    began = clock()
    while True:
        scrape = last_scrape()
        if scrape >= step_start or clock() - began >= timeout:
            break
        sleep(poll)
    return cpu_at(scrape), scrape, clock() - began, scrape >= step_start


def cpu_share(prom, real):
    """
    Share of the real CPU that the Prometheus readings saw over a run (1.0 = all).
    prom[k] is read at the start of step k and real[k] is the cgroup CPU of
    step k, so prom[k] is compared with real[k - 1]. Steps where Prometheus
    did not answer (nan) are left out.
    """
    prom, real = np.asarray(prom, dtype=float)[1:], np.asarray(real, dtype=float)[:-1]
    ok = np.isfinite(prom)
    return float(prom[ok].sum() / real[ok].sum())


def pods_for_cpu(cpu_cores, cpu_limit, threshold):
    """ceil(CPU / (limit x threshold)). The rounding stops float error from turning 2.0 into 2.0000001."""
    return math.ceil(round(cpu_cores / (cpu_limit * threshold), 9))


def khpa_pods(cpu_cores, cpu_limit, threshold, pods_min):
    """KHPA: the pods that would run the CPU just measured at the target use, at least Pods_min."""
    return max(pods_for_cpu(cpu_cores, cpu_limit, threshold), pods_min)


def requested_from_cpu(cpu_cores, cpu_limit, threshold):
    """Requested workers of each step from the real CPU: ceil(CPU / (limit x threshold)), at least 1."""
    return np.array([max(pods_for_cpu(c, cpu_limit, threshold), 1) for c in cpu_cores], dtype=np.int64)


def cpu_per_step(before, after, seconds):
    """
    CPU cores each worker used between two cgroup readings ({worker: (CPU s, throttled s)}).
    A worker that was started in between has no earlier reading and counts from 0.
    """
    used = {}
    for i, (cpu, throttled) in after.items():
        old_cpu, old_throttled = before.get(i, (0.0, 0.0))
        if cpu < old_cpu:                     # restarted: its counters began again at 0
            old_cpu, old_throttled = 0.0, 0.0
        used[i] = ((cpu - old_cpu) / seconds, (throttled - old_throttled) / seconds)
    return used
