<!-- Written by scripts/milan_areas.py; do not edit by hand. -->

### Data

| Day | Empty internet cells | Missing rows | Squares with a gap |
|---|---|---|---|
| 2013-11-01 | 36 | 18 | 7 |
| 2013-11-02 | 84 | 14 | 4 |
| 2013-11-03 | 108 | 37 | 3 |
| 2013-11-04 | 103 | 24 | 1 |

Squares with a gap on any day: 8 (5239, 7623, 7722, 7727, 7823, 7824, 7825, 7925). Of these, 1 fall under the low-activity cut-off.
Empty = missing leaves 2013-11-01: 0, 2013-11-02: 1, 2013-11-03: 1, 2013-11-04: 1 squares with an hour that has no known slot at all.
Same areas with empty = 0 and empty = missing: A True, 5x5 True, 10x10 True.

### Low-activity cut-off

Dropped: the 1393 quietest squares, which together hold 1% of all internet activity of the 4 days (each has a 4-day total of at most 4284.0). Kept: 8607. Median 4-day total of all squares: 17979.3.

### A: shape clusters

| Area | Squares | Peak 11-04 | Peak other 3 days | Peak 4-day mean | Peak/mean 11-04 | Peak/mean 4-day | Hours >= 90% of peak, 11-04 | Share of city | Share of the 4 | Connected regions (largest) | Landmarks |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 493 | 08:00 | 18:00 | 18:00 | 1.89 | 1.39 | 1 | 2.4% | 2.5% | 38 (30%) | - |
| 2 | 2980 | 13:00 | 17:00 | 17:00 | 1.69 | 1.41 | 5 | 37.0% | 37.4% | 91 (30%) | Duomo, Bocconi |
| 3 | 3122 | 18:00 | 18:00 | 18:00 | 1.33 | 1.30 | 9 | 37.8% | 38.2% | 252 (13%) | Navigli |
| 4 | 2012 | 21:00 | 21:00 | 21:00 | 1.43 | 1.34 | 5 | 21.7% | 22.0% | 98 (18%) | - |

Hours in which 2 or more areas are within 90% of their own peak: 11-04: 7 (13, 14, 15, 18, 19, 20, 21); 4-day mean: 12 (11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22).

### B: 5x5 blocks

Blocks (block row, block col from the south-west): (15, 1), (3, 16), (14, 4), (6, 5). Smallest gap between the 11-04 peak hours: 4 h. Largest / smallest 4-day demand: 1.03.

| Area | Squares | Peak 11-04 | Peak other 3 days | Peak 4-day mean | Peak/mean 11-04 | Peak/mean 4-day | Hours >= 90% of peak, 11-04 | Share of city | Share of the 4 | Connected regions (largest) | Landmarks |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 25 | 08:00 | 19:00 | 14:00 | 1.41 | 1.25 | 2 | 0.2% | 25.4% | 1 (100%) | - |
| 2 | 25 | 12:00 | 17:00 | 17:00 | 1.64 | 2.29 | 5 | 0.2% | 24.7% | 1 (100%) | - |
| 3 | 25 | 16:00 | 18:00 | 18:00 | 1.52 | 1.36 | 2 | 0.2% | 25.1% | 1 (100%) | - |
| 4 | 25 | 20:00 | 17:00 | 17:00 | 1.45 | 1.33 | 2 | 0.2% | 24.8% | 1 (100%) | - |

Hours in which 2 or more areas are within 90% of their own peak: 11-04: 2 (16, 20); 4-day mean: 12 (11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22).

### B: 10x10 blocks

Blocks (block row, block col from the south-west): (9, 8), (9, 7), (8, 8), (3, 3). Smallest gap between the 11-04 peak hours: 4 h. Largest / smallest 4-day demand: 1.23.

| Area | Squares | Peak 11-04 | Peak other 3 days | Peak 4-day mean | Peak/mean 11-04 | Peak/mean 4-day | Hours >= 90% of peak, 11-04 | Share of city | Share of the 4 | Connected regions (largest) | Landmarks |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 100 | 08:00 | 17:00 | 18:00 | 1.51 | 1.47 | 3 | 1.0% | 22.9% | 1 (100%) | - |
| 2 | 100 | 13:00 | 17:00 | 17:00 | 1.47 | 1.68 | 7 | 1.1% | 24.6% | 1 (100%) | - |
| 3 | 100 | 17:00 | 18:00 | 18:00 | 1.34 | 1.33 | 7 | 1.1% | 24.2% | 1 (100%) | - |
| 4 | 100 | 21:00 | 20:00 | 21:00 | 1.47 | 1.33 | 5 | 1.3% | 28.2% | 1 (100%) | - |

Hours in which 2 or more areas are within 90% of their own peak: 11-04: 7 (13, 14, 15, 16, 17, 18, 19); 4-day mean: 7 (14, 15, 16, 17, 18, 19, 20).
