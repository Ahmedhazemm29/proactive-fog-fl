# Random windows: proactive vs reactive

Written by `analysis/random_windows.py` from the runs of `scripts/run_random_windows.py`. Each window starts its load profile at a random offset; reactive and proactive run on the same window (paired), gain = (proactive - reactive) / reactive per window. "Gain of means" is computed like the earlier reports (proactive mean / reactive mean), so it compares directly with the fixed window: all earlier runs started the profile at t = 0 (`results/<profile>/comparison.md`).

| Profile | Windows | Reactive (steps/s) | Proactive (steps/s) | Mean gain | Min gain | Max gain | Proactive faster | Gain of means | Fixed window |
|---|---|---|---|---|---|---|---|---|---|
| sine | 10 | 330.3 ± 4.6 | 416.7 ± 5.3 | +26.2% | +23.1% | +29.4% | 10 of 10 | +26.2% | +26% |
| noisy_sine | 10 | 316.0 ± 14.7 | 407.1 ± 4.9 | +29.1% | +19.6% | +39.5% | 10 of 10 | +28.9% | +30% |
| bursts | 10 | 113.0 ± 32.5 | 205.3 ± 27.4 | +92.1% | +43.1% | +193.1% | 10 of 10 | +81.8% | +136% |

## sine

10 windows, offsets drawn with seed 1 (`sine_windows.csv`). Training speed = both workers' steps/s added up.

| Controller | Training speed (steps/s), mean ± sd |
|---|---|
| Reactive | 330.3 ± 4.6 |
| Proactive | 416.7 ± 5.3 |

| Mean gain ± sd | Min gain | Max gain | Proactive faster |
|---|---|---|---|
| +26.2% ± 1.8 | +23.1% | +29.4% | 10 of 10 |

| Window | Offset (s) | Reactive (steps/s) | Proactive (steps/s) | Gain |
|---|---|---|---|---|
| 1 | 196 | 331.3 | 407.9 | +23.1% |
| 2 | 1246 | 320.4 | 406.9 | +27.0% |
| 3 | 3182 | 326.1 | 422.1 | +29.4% |
| 4 | 1986 | 335.4 | 419.3 | +25.0% |
| 5 | 593 | 329.1 | 422.2 | +28.3% |
| 6 | 373 | 335.0 | 419.1 | +25.1% |
| 7 | 495 | 332.6 | 416.6 | +25.3% |
| 8 | 1942 | 328.0 | 417.1 | +27.2% |
| 9 | 676 | 332.4 | 417.3 | +25.6% |
| 10 | 2648 | 332.9 | 419.0 | +25.8% |

## noisy_sine

10 windows, offsets drawn with seed 1 (`noisy_sine_windows.csv`). Training speed = both workers' steps/s added up.

| Controller | Training speed (steps/s), mean ± sd |
|---|---|
| Reactive | 316.0 ± 14.7 |
| Proactive | 407.1 ± 4.9 |

| Mean gain ± sd | Min gain | Max gain | Proactive faster |
|---|---|---|---|
| +29.1% ± 6.3 | +19.6% | +39.5% | 10 of 10 |

| Window | Offset (s) | Reactive (steps/s) | Proactive (steps/s) | Gain |
|---|---|---|---|---|
| 1 | 3240 | 294.4 | 410.8 | +39.5% |
| 2 | 774 | 323.9 | 415.6 | +28.3% |
| 3 | 527 | 314.0 | 409.0 | +30.2% |
| 4 | 1995 | 322.2 | 400.6 | +24.3% |
| 5 | 698 | 292.9 | 404.3 | +38.1% |
| 6 | 1513 | 318.4 | 404.7 | +27.1% |
| 7 | 1062 | 342.5 | 409.7 | +19.6% |
| 8 | 2581 | 308.9 | 409.9 | +32.7% |
| 9 | 1978 | 317.9 | 406.6 | +27.9% |
| 10 | 1948 | 324.3 | 399.8 | +23.3% |

## bursts

10 windows, offsets drawn with seed 1 (`bursts_windows.csv`). Training speed = both workers' steps/s added up.

| Controller | Training speed (steps/s), mean ± sd |
|---|---|
| Reactive | 113.0 ± 32.5 |
| Proactive | 205.3 ± 27.4 |

| Mean gain ± sd | Min gain | Max gain | Proactive faster |
|---|---|---|---|
| +92.1% ± 45.3 | +43.1% | +193.1% | 10 of 10 |

| Window | Offset (s) | Reactive (steps/s) | Proactive (steps/s) | Gain |
|---|---|---|---|---|
| 1 | 2909 | 92.1 | 201.6 | +118.9% |
| 2 | 2596 | 71.4 | 156.0 | +118.7% |
| 3 | 3182 | 126.6 | 189.2 | +49.5% |
| 4 | 2044 | 164.2 | 252.0 | +53.4% |
| 5 | 976 | 122.1 | 210.6 | +72.5% |
| 6 | 2768 | 98.7 | 188.7 | +91.1% |
| 7 | 573 | 110.4 | 232.1 | +110.2% |
| 8 | 881 | 151.1 | 216.2 | +43.1% |
| 9 | 603 | 130.1 | 222.5 | +71.0% |
| 10 | 1146 | 62.9 | 184.4 | +193.1% |
