# Reactive vs proactive across load profiles

Each load profile was run 3 times with each controller, 10 minutes per run,
alternating reactive and proactive. Before every run both workers were reset
to 0.5 CPU and the load profile was restarted, so all runs of a profile saw
the same load. The two workers share a budget of 1.0 CPU.

| Profile | Runs | Details |
|---|---|---|
| sine, 20 s apart | 2026-10-02, 21:38 to 22:43 | [comparison.md](comparison.md), [figures](../figures/) |
| bursts | 2026-10-04, 18:42 to 19:47 | [bursts/comparison.md](bursts/comparison.md), [bursts/figures](bursts/figures/) |
| noisy_sine | 2026-10-04, 19:48 to 20:53 | [noisy_sine/comparison.md](noisy_sine/comparison.md), [noisy_sine/figures](noisy_sine/figures/) |
| sine, 60 s apart | 2026-10-05, 00:06 to 01:12 | [sine/comparison.md](sine/comparison.md), [sine/figures](sine/figures/) |

Up to "Where proactive helps and where it doesn't", "sine" means the
2 October runs, with the two workers' waves about 20 seconds apart. The run
with the waves 60 seconds apart is compared in its own section after that.

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
| noisy_sine | 0.53 | 0.55 | -0.82 | 1.07 (0.53 to 1.50) | 63% |

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
| bursts | proactive | 1.00 | 0.63 | 0.46 |
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
(0.63 against 0.46). The large difference, 136% faster training, comes from
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

## Sine with the waves 20 s apart vs 60 s apart

On 2 October the two workers' waves were about 20 seconds apart, so they
were busy at roughly the same times. To see whether that is why proactive
gained only 12% there but 30% under noisy_sine, the sine profile was run on
2026-10-05 with the waves 60 seconds apart: half a period, so one worker is
busy exactly when the other is quiet. Everything else was done as for the
other profiles.

The offset was measured from the load each worker logged every second.
Before the runs the waves were 60.08 seconds apart, and in the six runs 59.9
to 60.0 seconds. The small differences come from the second worker picking
up a new profile a fraction of a second after the first. On 2 October the
waves were 18.3 to 18.6 seconds apart. noisy_sine is also set to 60 seconds,
but its noise shifts the measured value to about 56 seconds: the same
calculation on its load without the noise gives exactly 60.00 seconds.

| Load | Waves apart (s) | Correlation of the two loads | Total load | Time total is above 1.0 CPU |
|---|---:|---:|---:|---:|
| sine, 20 s apart (2 Oct) | 18.3 to 18.6 | +0.44 | 1.10 (0.33 to 1.87) | 55% |
| sine, 60 s apart | 59.9 to 60.0 | -1.00 | 1.10 (1.09 to 1.11) | 100% |
| noisy_sine | 54.8 to 56.1 | -0.82 | 1.07 (0.53 to 1.50) | 63% |
| bursts | - | -0.12 | 0.61 (0.20 to 2.00) | 42% |

| Load | Training speed, reactive | Training speed, proactive | Speed difference | CPU used difference | Unmet demand difference | Runs overlap? |
|---|---:|---:|---:|---:|---:|---|
| sine, 20 s apart (2 Oct) | 315.3 ± 4.0 | 354.0 ± 9.7 | +38.7 (+12%) | +0.075 (+13%) | -0.061 (-10%) | no |
| sine, 60 s apart | 322.9 ± 3.8 | 407.0 ± 5.0 | +84.1 (+26%) | +0.147 (+25%) | -0.139 (-23%) | no |
| noisy_sine | 300.3 ± 2.9 | 391.8 ± 1.2 | +91.5 (+30%) | +0.153 (+28%) | -0.153 (-25%) | no |
| bursts | 93.6 ± 34.9 | 220.4 ± 0.5 | +126.8 (+136%) | +0.213 (+124%) | -0.241 (-44%) | no |

CPU limit in cores, as in the section "Where the controllers put the CPU":

| Profile | Controller | Both limits together | Limit while busy | Limit while idle |
|---|---|---:|---:|---:|
| sine, 20 s apart (2 Oct) | reactive | 0.95 | 0.47 | 0.49 |
| sine, 20 s apart (2 Oct) | proactive | 1.00 | 0.57 | 0.42 |
| sine, 60 s apart | reactive | 1.00 | 0.48 | 0.53 |
| sine, 60 s apart | proactive | 1.00 | 0.76 | 0.21 |
| noisy_sine | reactive | 0.96 | 0.45 | 0.52 |
| noisy_sine | proactive | 1.00 | 0.72 | 0.23 |
| bursts | reactive | 0.49 | 0.22 | 0.25 |
| bursts | proactive | 1.00 | 0.63 | 0.46 |

### Does the offset explain +12% against +30%?

**Mostly, yes.** With the waves 60 seconds apart instead of 20, proactive's
advantage in training speed grew from 12% to 26%. That is 14 of the 18
points between the 2 October sine and noisy_sine. The other 4 points come
with the noise, which slowed both controllers, reactive a little more: by 23
steps/s against 15 steps/s for proactive. Cutting the noise off at 0 and 1
also lowers noisy_sine's average load a little, 1.07 against 1.10 CPU.

The reason is simple. With the waves 60 seconds apart, one worker is always
busy while the other is quiet, so there is always CPU worth moving, and
proactive moves it: a busy worker had 0.76 CPU on average and a quiet one
0.21. With the waves 20 seconds apart, the two workers rise and fall almost
together, so proactive kept the split closer to even, 0.57 against 0.42.

**What the offset does not explain:**

- **Reactive.** It trained at 315 steps/s with the waves 20 seconds apart
  and at 323 with them 60 seconds apart. Under a sine load it hardly moves
  the limits: they stayed between 0.3 and 0.7 CPU in every sine run, mostly
  between 0.4 and 0.6, while demand swung between about 0.2 and 1.0 (see
  [demand_usage_reactive_1.pdf](sine/figures/demand_usage_reactive_1.pdf)).
  So reactive cannot profit from the workers taking turns, and the whole
  change in the gap comes from proactive: 354 against 407 steps/s.
- **The shortage.** With the waves 60 seconds apart the two workers together
  want 1.10 CPU at every moment, just above the 1.0 budget, and each wants a
  full core while it is busy. So even proactive left 0.46 CPU of demand
  unmet, the same as under noisy_sine.
- **Bursts.** Its +136% comes from reactive shrinking both workers and
  leaving half the budget unused, not from how the two loads line up.
- **The other differences between the two sine runs.** The 2 October runs
  also had another day, the older runner, which did not restart the load
  before each run, and the old workload code with the same wave formula.
  Reactive's nearly equal speed on both days, 2% apart, suggests these
  matter little, but this comparison cannot rule them out.

## Caveats

- **The first sine runs are from another day and an older setup.** They
  used the old built-in sine (both waves about 20 seconds apart) and a
  runner that did not restart the load before each run. The section above
  compares them with a sine run with the waves 60 seconds apart.
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
python scripts/run_experiments.py --profile sine
python analysis/compare_runs.py --runs-dir data/runs/bursts --results results/bursts/comparison.md --figures-dir results/bursts/figures
python analysis/compare_runs.py --runs-dir data/runs/noisy_sine --results results/noisy_sine/comparison.md --figures-dir results/noisy_sine/figures
python analysis/compare_runs.py --runs-dir data/runs/sine --results results/sine/comparison.md --figures-dir results/sine/figures
python analysis/summarize_profiles.py
```

The last command prints all tables in this file. The raw data (controller
CSVs, worker logs, runs.csv) is in `data/runs/<profile>/`, which is not in git.
