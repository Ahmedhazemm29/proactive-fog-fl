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
