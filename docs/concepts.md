# Concept Notes

Plain-language explanations of key ideas in this project. Useful for explaining the work to others.

---

## Worker and controller

**Worker:** a container that does work and needs CPU. Each worker trains a small model, and its hunger for CPU rises and falls in a 120-second wave. Later, the workers become the federated learning clients.

**Controller:** a Python script that decides how much CPU each worker gets. Every 5 seconds it looks at how hungry each worker is, decides how to split the 1.0 CPU budget, and applies the new split through Docker.

Analogy: two hungry people at a table (workers) and a waiter sharing one pizza between them (controller).

- **Reactive controller** (`reactive.py`): waits until someone is clearly starving, then gives them more. Always a bit late.
- **Proactive controller** (`proactive.py`): watches who is *getting* hungrier, and gives them more *before* they starve.

---

## Hidden demand

A container can never use more CPU than its limit. So a worker capped at 0.2 shows a usage of 0.2, even if it wants 1.0. Looking only at usage, the controller would think 0.2 is all it needs and keep it there forever.

Analogy: if you give a friend one slice, they eat one slice. Looking at their plate, you would think one slice is all they want. Maybe they wanted four.

Fix: real demand = CPU used + CPU it was held back from (see below).

---

## How do we know how much a worker was held back?

We don't guess it, Linux measures it.

Docker enforces limits in small time slices of 0.1 seconds. With a 0.5 limit, a worker may run for 0.05 s in each slice. If it wants more, Linux pauses it until the next slice, and keeps a stopwatch of how long it was paused.

cAdvisor reads that stopwatch, and Prometheus records it. That is the "throttled" number.

Analogy: a bouncer at a club door lets people in at a fixed rate, and writes down how long each person waited outside. Long waits mean that person wanted in much more than they were allowed.

---

## Why does worker-1 never get as much as worker-2?

It's the timing, not favoritism. Worker-2 always gets busy about 20 seconds before worker-1. From the proactive run log:

```
20:57:52  worker-1: demand 0.22    worker-2: demand 0.56 -> limit 0.85
20:58:38  worker-1: demand 1.00    worker-2: demand 0.87 -> limit 0.60 / 0.40
```

- When worker-2 climbs, worker-1 is still resting. Worker-2 has the CPU almost to itself (0.85).
- When worker-1 climbs, worker-2 is still busy. They have to share, so worker-1 only gets about 0.60.

A prediction above 1.0 does not help: the budget is 1.0 in total. If one worker predicts 1.24 and the other 0.89, the split is still only about 58% / 42%. When both are hungry at the same time, someone has to lose.

Analogy: two people walking into a restaurant 20 seconds apart. The first one always finds an empty table, the second one has to share.

---

## Why compare reactive and proactive under the same conditions?

Believing proactive is better is not enough. The thesis has to prove it with numbers. An older reactive run used different worker timing and conditions, so comparing it to a new proactive run would be like comparing two race cars on different tracks in different weather.

Robotics analogy: when tuning a new controller for a robot arm, you run the old and the new controller on the same trajectory, then compare the errors side by side.

---

## What happens when both workers need more than the budget?

The budget is 1.0 CPU in total. If worker 1 has 0.8 and worker 2 needs more than the remaining 0.2, worker 2 is throttled and slows down. There is no hidden extra CPU.

When both workers are hungry at the same time, the controller has to decide who loses, and by how much. Our proactive controller splits the budget in proportion to predicted demand. Example: worker 1 predicts 1.0 and worker 2 predicts 0.5. Together they want 1.5, but only 1.0 exists:

```
worker 1: 1.0 / 1.5 = 0.67
worker 2: 0.5 / 1.5 = 0.33
```

Both get less than they want, each in proportion to their hunger.

Proportional is only one possible rule:

| Rule | Idea |
|---|---|
| Proportional (current) | Share the shortage fairly |
| Equal | 0.5 / 0.5, ignore demand |
| Help the straggler | Give more to whoever would finish last |

In federated learning, a round only ends when the slowest client finishes, so "help the straggler" may beat "fair". This is a design choice worth testing with real FL.

The other way out is to grow the budget itself, for example by adding another machine when everyone is hungry. That is horizontal scaling, as Kubernetes does in the related papers.

Why the two limit lines mirror each other in the plots: the controller always splits exactly 1.0, so every step up for one worker is the same step down for the other. The mirroring comes from the fixed budget, the 120 s rhythm comes from the workload.

---

## Limitation: our test workload is the easiest possible case

The workers' demand follows a smooth sine wave that repeats every 120 s. Real demand can jump suddenly, without warning. So the measured improvement of proactive over reactive (+12% training speed) is probably optimistic.

The controller is not cheating, though. It never reads the sine formula or the intensity value. It only sees CPU usage measured from outside by Prometheus, like on a real system. It found the rhythm by observation.

Real workloads are not fully random either. Websites are busy by day and quiet at night, and federated learning repeats a train, wait, train, wait cycle. Proactive scaling helps where patterns exist. Truly sudden spikes cannot be predicted by anyone, which is why real systems often combine both: predict when possible, react fast when a surprise hits (hybrid scaling).

Next experiments to make the result stronger:
1. Sudden bursts at random moments
2. A noisy wave (pattern plus randomness)
3. Real FL rounds, where the rhythm comes from training itself
4. A real recorded trace, such as the Bitbrains dataset used by Kumar et al.
