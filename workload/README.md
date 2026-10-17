# workload

This folder belongs to the earlier part of the thesis. It holds the program of the two worker containers `fl-worker-1` and `fl-worker-2` in `docker-compose.yml`. Each worker trains a small classifier on the sklearn digits data. In every second it works for "intensity" seconds and sleeps for the rest, following its profile in `load/`.

- `workload.py`: the training loop. It logs the intended intensity every second.
- `Dockerfile`: the worker image, python:3.11-slim with numpy and scikit-learn.
