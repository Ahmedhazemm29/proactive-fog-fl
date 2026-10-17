# load

This folder belongs to the earlier part of the thesis. It holds the load profiles of the two training workers. `scripts/set_load.py` writes each worker's current profile to `load/<worker>.json`. Git ignores those files, and tracks only the named profiles.

- `profiles/sine.json`: a sine wave between 0.1 and 1.0 CPU with a 120 s period. The two workers are 60 s apart.
- `profiles/noisy_sine.json`: the same sine with random noise added.
- `profiles/bursts.json`: bursts of full load, 20 s long and 60 s apart, on a base of 0.1.
- `profiles/steps.json`: 0.2 and 0.9 CPU, swapped between the two workers every 120 s.
- `profiles/constant.json`: a constant 0.8 and 0.3 CPU.
