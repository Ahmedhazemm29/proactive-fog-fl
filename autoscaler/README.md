# autoscaler

This folder holds the autoscalers of steps 4A and 4B. `scripts/simulate_autoscaler.py` uses them in the simulation, and `scripts/live_run.py` uses them with real containers. The decisions behind them are entries 4A.x and 4B.x of `docs/decisions.md`.

- `scalers.py`: no autoscaling, KHPA and the planner, which is Dogani's Algorithm 3. It also holds the cooldown loop and the settings of Table 3.
- `metrics.py`: θU, θO, TU, TO and the elastic speedup εn, Eqs. 14 to 18.
- `live.py`: one decision per step for the live demo, KHPA's CPU rules and the fresh Prometheus read.
- `cluster.py`: the live cluster: the worker containers, HAProxy, the cleanup and the Prometheus queries.
- `loadgen.py`: the open-loop load generator that replays the traffic.
- `__init__.py`: makes the folder a Python package.
