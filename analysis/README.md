# analysis

This folder belongs to the earlier part of the thesis, the vertical CPU scaling of two containers. Its scripts turn the runs of `scripts/run_experiments.py` into tables and figures. They read the CPU from Prometheus and the training speed from the workers' logs.

- `compare_runs.py`: mean and standard deviation per controller, and figures per run. It writes `results/<profile>/comparison.md`.
- `summarize_profiles.py`: prints the tables of `results/profiles_summary.md`.
- `requirements.txt`: the Python packages these scripts need.
