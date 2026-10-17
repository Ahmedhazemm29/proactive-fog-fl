# controller

This folder belongs to the earlier part of the thesis. Two worker containers share a budget of 1.0 CPU, and these controllers change their CPU limits while they run. The controllers only see Prometheus and the CPU limits, never the load profiles.

- `reactive.py`: the reactive baseline. Every 5 s it adds 0.1 CPU to a worker above 80% use and takes 0.1 from one below 20%.
- `proactive.py`: the proactive controller. It fits a line to the last 6 readings, predicts 10 s ahead and splits the budget by the predicted demand.
- `set_cpu.py`: sets a running container's CPU limit.
- `requirements.txt`: the Python packages the controllers need.
