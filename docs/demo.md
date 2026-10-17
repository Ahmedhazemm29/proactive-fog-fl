# How to demo

A 10 to 15 minute live demo: two worker containers share 1.0 CPU, and you
show what happens with no controller, with the proactive controller and with
the reactive one. Then you add a spike by hand. Run all commands from the
project folder.

## 1. Setup checks (before the meeting)

```bash
docker compose ps        # 5 containers "Up": fl-worker-1, fl-worker-2, cadvisor, prometheus, grafana
timedatectl              # needs "System clock synchronized: yes" (the RTC warning below it is expected)
pgrep -af "controller/|run_experiments"     # should print nothing: no controller, no experiment
.venv/bin/python controller/set_cpu.py fl-worker-1 0.5   # start both workers at 0.5 CPU
.venv/bin/python controller/set_cpu.py fl-worker-2 0.5
.venv/bin/python scripts/set_load.py all profile sine    # both sine waves, 60 s apart
```

If the clock is not synchronized yet, wait until it is: after a boot the clock
can start about 3 h off, and Prometheus then shows no new data.

Not run while this guide was written, because they change the live system:
the `set_cpu.py` and `set_load.py` lines, the controller starts in the acts
and the `mv` lines at the end. Their arguments were checked against the
scripts, and the experiment runner makes the same `set_cpu` and `set_load`
calls before every run.

## 2. What to open

1. Grafana: log in at http://localhost:3000. Then open the demo
   dashboard in kiosk mode: http://localhost:3000/d/cpu-demo?orgId=1&kiosk
   (Esc leaves kiosk mode). Per worker it shows demand (orange, dashed), used
   (blue) and the limit (thick green steps), plus "Both limits together".
   It shows the last 10 minutes and refreshes every 5 s.
2. Control page, in a second terminal:
   `.venv/bin/python scripts/control_page.py`, then http://127.0.0.1:8765.
   It also has a button that opens the Grafana dashboard.

## 3. The acts

Start each controller in its own terminal and stop it with Ctrl+C. Ctrl+C
leaves the limits where they are, so set both back to 0.5 with the two
`set_cpu.py` lines from the setup before the next act.

| Act | Do | The audience should see |
|---|---|---|
| 1. No controller, 2 min | Nothing. The sine profile runs. | The orange demand rises to about 1.0 while the green limit stays flat at 0.5: the busy worker is capped while the other holds CPU it does not need. |
| 2. Proactive, 3 min | `.venv/bin/python controller/proactive.py` | For about 25 s it prints "collecting history, keeping current limits". Then the two green limits swing in opposite directions and follow the orange waves, so the busy worker gets most of the budget. "Both limits together" stays at 1.00. |
| 3. Reactive, 3 min | Ctrl+C, reset limits, `.venv/bin/python controller/reactive.py` | The limits move only in 0.1 steps and stay between about 0.3 and 0.7. Help arrives about 30 s late, so the busy worker stays capped. |
| 4. Constant plus spike, 3 min | Ctrl+C, reset limits. On the control page, click "constant" under "Both workers" (worker 1 at 0.8, worker 2 at 0.3). Start `proactive.py` again and wait about 1 min. On worker 2, set the spike to height 0.5 and duration 60 s, then click "Spike now". | Worker 2's card shows the spike counting down. Its orange demand climbs toward 0.8, and its green limit follows a little later while worker 1's limit drops. After the spike, the split goes back. |

After the demo: Ctrl+C the controller, reset the limits, run
`.venv/bin/python scripts/set_load.py all profile sine`, and move the
controller logs away (see the last known limit).

## 4. What each load mode does

The values in brackets are those in `load/profiles/<mode>.json`, the ones
used in the experiments and the ones the control page starts a mode with.

| Mode | The load | Main settings on the page |
|---|---|---|
| sine | Smooth wave between a low and a high level (0.1 to 1.0 every 120 s, the two workers 60 s apart) | period, min, max, phase |
| noisy_sine | The same wave plus random noise (strength 0.15, new value every 5 s) | as sine, plus noise and hold |
| bursts | Low baseline with spikes at random times (0.1 base, spikes to 1.0 for 20 s, on average 60 s apart) | base, height, duration, gap |
| steps | Fixed levels at fixed times (worker 1: 0.2, then 0.9 from 120 s, repeating every 240 s; worker 2 the other way round) | first level, second level, switch time, repeat |
| constant | One fixed level (worker 1 at 0.8, worker 2 at 0.3) | level |
| Spike now | Adds height for duration seconds on top of any mode, at most 1.0 in total. The profile keeps running. | height, duration |

A level of 1.0 means one core flat out.

## 5. Known limits

- **Spikes under 30 s don't reach full height.** Demand is a rate over 30 s,
  both on the dashboard and for the controllers. A 10 s spike of +0.5 shows
  as about +0.17. Use 30 s or more in the demo.
- **The controller reacts only after a spike starts.** It sees nothing but
  Prometheus and the CPU limits, never the load files, so nothing warns it.
  The first seconds of every spike run at the old limit.
- **Releasing a slider restarts that worker's profile.** So does clicking a
  mode on one worker's card: its profile starts again from t = 0, and the two
  sine waves are no longer 60 s apart. Click "sine" under "Both workers" to
  line them up again. "Spike now" does not restart anything.
- **The control page refuses changes during an experiment.** While
  `scripts/run_experiments.py` runs, it shows a red warning and every control
  is disabled.
- **Move `data/*_log.csv` before experiments.** Each controller appends to
  `data/reactive_log.csv` or `data/proactive_log.csv`, and
  `run_experiments.py` refuses to start while either file exists. For example:

  ```bash
  mkdir -p data/old
  mv data/proactive_log.csv data/old/proactive_log_$(date +%F)_demo.csv
  mv data/reactive_log.csv data/old/reactive_log_$(date +%F)_demo.csv
  ```
