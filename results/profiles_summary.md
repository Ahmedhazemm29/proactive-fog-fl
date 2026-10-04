# Reactive vs proactive across load profiles

Each load profile was run 3 times with each controller, 10 minutes per run,
alternating reactive and proactive. Before every run both workers were reset
to 0.5 CPU and the load profile was restarted, so all runs of a profile saw
the same load. The two workers share a budget of 1.0 CPU.

| Profile | Runs | Details |
|---|---|---|
| sine | 2026-10-02, 21:38 to 22:43 | [comparison.md](comparison.md), [figures](../figures/) |
| bursts | 2026-10-04, 18:42 to 19:47 | [bursts/comparison.md](bursts/comparison.md), [bursts/figures](bursts/figures/) |
| noisy_sine | 2026-10-04, 19:48 to 20:53 | [noisy_sine/comparison.md](noisy_sine/comparison.md), [noisy_sine/figures](noisy_sine/figures/) |

## The three loads

- **sine**: each worker follows a smooth 2-minute wave between 0.1 and 1.0
  CPU. On 2 October the two waves were about 20 seconds apart, so the
  workers were busy at roughly the same times.
- **bursts**: each worker idles at 0.1 CPU and jumps to 1.0 CPU for 20
  seconds at random moments, about once a minute. The two workers spike
  independently of each other.
- **noisy_sine**: the 2-minute wave plus random noise that changes every 5
  seconds, with the workers half a wave apart: one is busy while the other
  is quiet.

The load each worker wanted during the runs, from its own log:

| Profile | Worker 1 load | Worker 2 load | Correlation of the two loads | Total load | Time total is above 1.0 CPU |
|---|---:|---:|---:|---:|---:|
| sine | 0.55 | 0.55 | +0.44 | 1.10 (0.33 to 1.87) | 55% |
| bursts | 0.36 | 0.25 | -0.12 | 0.61 (0.20 to 2.00) | 42% |
| noisy_sine | 0.53 | 0.55 | -0.81 | 1.07 (0.53 to 1.51) | 63% |

A correlation near +1 means the workers are busy together, near -1 that
they take turns. The last column is how often the two together wanted more
than the 1.0 CPU budget.

## Results

Totals of both workers, mean ± standard deviation over 3 runs per controller.
Unmet demand is the CPU a worker wanted but could not get because its limit
was used up.

| Profile | Controller | Training speed (steps/s) | CPU used (CPU) | Unmet demand (CPU) |
|---|---|---:|---:|---:|
| sine | reactive | 315.3 ± 4.0 | 0.565 ± 0.018 | 0.622 ± 0.003 |
| sine | proactive | 354.0 ± 9.7 | 0.640 ± 0.001 | 0.561 ± 0.002 |
| bursts | reactive | 93.6 ± 34.9 | 0.172 ± 0.065 | 0.544 ± 0.071 |
| bursts | proactive | 220.4 ± 0.5 | 0.386 ± 0.012 | 0.303 ± 0.005 |
| noisy_sine | reactive | 300.3 ± 2.9 | 0.546 ± 0.006 | 0.615 ± 0.007 |
| noisy_sine | proactive | 391.8 ± 1.2 | 0.699 ± 0.012 | 0.462 ± 0.009 |

"Runs overlap?" compares the lowest and highest run of each controller.
"No" means every proactive run was on the same side of every reactive run.

| Profile | Metric | Reactive runs | Proactive runs | Proactive − reactive | Runs overlap? |
|---|---|---|---|---:|---|
| sine | Training speed (steps/s) | 312.8 to 319.9 | 343.0 to 360.9 | +38.7 (+12%) | no, proactive better |
| sine | CPU used (CPU) | 0.546 to 0.579 | 0.639 to 0.641 | +0.075 (+13%) | no, proactive better |
| sine | Unmet demand (CPU) | 0.618 to 0.624 | 0.560 to 0.563 | -0.061 (-10%) | no, proactive better |
| bursts | Training speed (steps/s) | 63.8 to 132.0 | 219.8 to 220.8 | +126.8 (+136%) | no, proactive better |
| bursts | CPU used (CPU) | 0.117 to 0.244 | 0.373 to 0.396 | +0.213 (+124%) | no, proactive better |
| bursts | Unmet demand (CPU) | 0.465 to 0.602 | 0.298 to 0.307 | -0.241 (-44%) | no, proactive better |
| noisy_sine | Training speed (steps/s) | 297.1 to 302.6 | 391.0 to 393.1 | +91.5 (+30%) | no, proactive better |
| noisy_sine | CPU used (CPU) | 0.542 to 0.553 | 0.686 to 0.706 | +0.153 (+28%) | no, proactive better |
| noisy_sine | Unmet demand (CPU) | 0.610 to 0.623 | 0.452 to 0.468 | -0.153 (-25%) | no, proactive better |

Training speed follows CPU used closely: every profile and controller gives
544 to 571 training steps per CPU-second. So the three metrics tell the same
story.

## Where the controllers put the CPU

Average CPU limit in cores. "While busy" covers the seconds in which a worker
wanted at least 0.7 CPU, "while idle" the seconds in which it wanted at most
0.3 CPU.

| Profile | Controller | Both limits together | Limit while busy | Limit while idle |
|---|---|---:|---:|---:|
| sine | reactive | 0.95 | 0.47 | 0.49 |
| sine | proactive | 1.00 | 0.57 | 0.42 |
| bursts | reactive | 0.49 | 0.22 | 0.25 |
| bursts | proactive | 1.00 | 0.64 | 0.46 |
| noisy_sine | reactive | 0.96 | 0.45 | 0.52 |
| noisy_sine | proactive | 1.00 | 0.72 | 0.23 |

On average, reactive gave a busy worker no more CPU than an idle one: it
reacts so late that its extra CPU arrives after the busy phase. Proactive
gave the busy worker more in every profile.

## Where proactive helps and where it doesn't

**Proactive was better in all three loads.** No proactive run was worse than
any reactive run, on any metric.

**It helps most when the workers take turns.** In noisy_sine one worker is
busy while the other is quiet. Proactive moves the CPU to the busy worker in
time (0.72 CPU while busy, 0.23 while idle, see
[limits_proactive_1.pdf](noisy_sine/figures/limits_proactive_1.pdf)).
Reactive moves it too late, so a worker even had more CPU while idle than
while busy. Training was 30% faster with proactive. The noise did not stop
proactive from following the wave: both controllers look at 30-second
averages, which smooth out noise that changes every 5 seconds.

**It helps less when both workers are busy at the same time.** On 2 October
the two waves were only about 20 seconds apart. When both workers want more
than 0.5 CPU, any split of the 1.0 budget leaves one of them short, so there
is less to gain from moving CPU around: 12% faster training.

**Its biggest gain, under bursts, mostly does not come from predicting.** A
20-second spike shows up small and late in a 30-second average. So
proactive gives a spiking worker only a little more CPU than an idle one
(0.64 against 0.46). The large difference, 136% faster training, comes from
reactive breaking down:

- An idle bursts worker uses about 20% of a 0.5 limit, which is exactly
  reactive's "shrink" threshold. So reactive keeps shrinking idle workers,
  down to 0.1.
- A short spike only briefly lifts the 30-second average over reactive's
  80% "grow" threshold. Reactive usually grows the worker by one step of
  0.1 and shrinks it again afterwards (see
  [demand_usage_reactive_3.pdf](bursts/figures/demand_usage_reactive_3.pdf)).
- So reactive left about half of the 1.0 CPU budget unused (0.49 handed
  out on average), while proactive always hands out the whole budget.

**Where proactive does not help:**

- **Short spikes.** It cannot see them in time. Even with proactive, unmet
  demand under bursts stayed at 0.30 CPU, although the workers' average
  demand (0.69 CPU) is well below the budget.
- **Both workers busy at once.** When the two together want more than 1.0
  CPU, no split satisfies both. This happened 42% to 63% of the time, and
  unmet demand stayed high for both controllers in the sine loads (0.46 to
  0.62 CPU).

## Caveats

- **The sine runs are from another day and an older setup.** They used the
  old built-in sine (both waves about 20 seconds apart) and a runner that did
  not restart the load before each run. Today's `sine` profile puts the
  workers half a wave apart, like noisy_sine. For a like-for-like
  comparison, run `--profile sine` (about 67 minutes).
- **Prediction or budget?** These runs cannot tell how much of proactive's
  gain comes from predicting 10 seconds ahead, and how much from always
  sharing out the full budget in proportion to demand. A proactive run with
  a 0-second horizon would separate the two.
- **Reactive's bursts runs vary a lot** (0.117 to 0.244 CPU used), although
  their load was identical. The runs part ways at the first decision: at
  the 0.5 starting limit, an idle worker's usage is so close to the 20%
  threshold (0.108 against 0.088 CPU in two runs) that tiny measurement
  differences decide whether reactive shrinks it.
- **Measured demand reads high.** In every profile, demand (CPU used plus
  throttled time) is about 0.1 CPU above the load the workers wanted, for
  example 1.16 against 1.07 under noisy_sine. This probably comes from how
  throttled time is counted, to the end of each 100 ms period. It affects
  both controllers in the same way.
- **Only 3 runs per controller.** "Runs overlap: no" shows the difference is
  consistent, but the means are not precise, especially for reactive under
  bursts.

## How these numbers were made

```
python scripts/run_experiments.py --profile bursts
python scripts/run_experiments.py --profile noisy_sine
python analysis/compare_runs.py --runs-dir data/runs/bursts --results results/bursts/comparison.md --figures-dir results/bursts/figures
python analysis/compare_runs.py --runs-dir data/runs/noisy_sine --results results/noisy_sine/comparison.md --figures-dir results/noisy_sine/figures
python analysis/summarize_profiles.py
```

The last command prints all tables in this file. The raw data (controller
CSVs, worker logs, runs.csv) is in `data/runs/<profile>/`, which is not in git.
