# live

This folder holds the worker container of the live demo, step 4B. One container plays one pod, with 0.5 CPU and 256 MB. `autoscaler/cluster.py` starts and stops these containers behind HAProxy.

- `worker/server.py`: a small HTTP server. Each request to `/work` runs one of Dogani's three tasks, chosen at random: sort 3000 numbers, find the eigenvalues of a 100 x 100 matrix, or compress 64 KB of text.
- `worker/Dockerfile`: the image `thesis/live-worker:latest`, which is python:3.11-slim with numpy. Build it with `docker build -t thesis/live-worker:latest live/worker`.
