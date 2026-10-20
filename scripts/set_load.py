"""
Change a worker's load profile live. The worker picks it up within 1 second.

Examples:
    python scripts/set_load.py fl-worker-2 bursts --height 1.0 --gap 60
    python scripts/set_load.py fl-worker-1 sine --period 120 --min 0.1 --max 1.0
    python scripts/set_load.py fl-worker-1 noisy_sine --noise 0.15 --hold 5
    python scripts/set_load.py fl-worker-1 steps --steps 0:0.2,60:0.9 --repeat 120
    python scripts/set_load.py all constant --level 0.6
    python scripts/set_load.py all profile bursts      (named profile, see load/profiles/)
    python scripts/set_load.py fl-worker-1 spike --height 0.5 --duration 30
                                  (one extra spike on top; the profile keeps running)
    python scripts/set_load.py fl-worker-1 bursts --help   (all options of a mode)

It writes load/<worker>.json (a spike: load/<worker>.spike.json), which
docker-compose mounts into the worker at /load. Only the workers read these
files. The controllers never do: they see nothing but Prometheus and the
containers' CPU limits.
"""
import argparse
import json
import os
import sys
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LOAD_DIR = os.path.join(ROOT, "load")                 # mounted into the workers
PROFILES_DIR = os.path.join(LOAD_DIR, "profiles")     # named profiles for experiments
WORKERS = ["fl-worker-1", "fl-worker-2"]


# ----------------------------------------------------------------------
# Writing a worker's load file
# ----------------------------------------------------------------------
def write_json(path, data):
    """Save `data` as JSON at `path` (a profile or a spike file)."""
    # Write a temporary file first and then rename it: a rename is instant, so
    # the worker never reads a half-written file.
    temporary = path + ".tmp"
    with open(temporary, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(temporary, path)


def write_profile(worker, profile):
    """
    Save one worker's profile. "set_at" records when, and also makes the file
    differ from the last one, so setting the same profile again replays it.
    """
    profile = dict(profile, set_at=datetime.now().astimezone().isoformat(timespec="seconds"))
    write_json(os.path.join(LOAD_DIR, f"{worker}.json"), profile)
    return profile


def write_spike(worker, height, duration):
    """
    One extra spike on top of the worker's current load: `height` more for
    `duration` seconds. It has its own file, load/<worker>.spike.json, because
    a changed profile file would start the profile again from zero.
    "set_at" makes the file differ from the last one, so every spike counts.
    """
    spike = {"height": height, "duration": duration,
             "set_at": datetime.now().astimezone().isoformat(timespec="seconds")}
    write_json(os.path.join(LOAD_DIR, f"{worker}.spike.json"), spike)
    return spike


def apply_named_profile(name, workers=WORKERS, offset=0):
    """
    Give each worker its part of load/profiles/<name>.json. With an offset
    (seconds) the profile starts at t = offset instead of 0, for both workers.
    """
    path = os.path.join(PROFILES_DIR, f"{name}.json")
    with open(path) as f:
        profiles = json.load(f)
    if offset:
        profiles = {worker: dict(profile, offset=offset) for worker, profile in profiles.items()}
    return {worker: write_profile(worker, profiles[worker]) for worker in workers}


def named_profiles():
    return sorted(f[:-5] for f in os.listdir(PROFILES_DIR) if f.endswith(".json"))


# ----------------------------------------------------------------------
# Checking the values, so mistakes are caught here and not in the worker
# ----------------------------------------------------------------------
def parse_steps(text):
    """'0:0.2,60:0.9' -> [[0.0, 0.2], [60.0, 0.9]]"""
    try:
        return [[float(at), float(level)] for at, level in
                (pair.split(":") for pair in text.split(","))]
    except ValueError:
        raise argparse.ArgumentTypeError("use time:level pairs, e.g. 0:0.2,60:0.9")


def check(profile):
    """Return a list of problems with a profile (empty if it is fine)."""
    problems = []
    levels = [profile[k] for k in ("min", "max", "base", "height", "level") if k in profile]
    levels += [level for _, level in profile.get("steps", [])]
    if any(not 0 <= level <= 1 for level in levels):
        problems.append("levels must be between 0 and 1 (1 = one core flat out)")
    for key in ("period", "hold", "gap", "duration"):
        if key in profile and profile[key] < 1:
            problems.append(f"--{key} must be at least 1 second")
    if profile.get("min", 0) > profile.get("max", 1):
        problems.append("--min must not be above --max")
    if profile.get("noise", 0) < 0:
        problems.append("--noise must not be negative")
    if profile.get("offset", 0) < 0:
        problems.append("offset must not be negative")
    return problems


# ----------------------------------------------------------------------
# Command line
# ----------------------------------------------------------------------
def build_parser():
    parser = argparse.ArgumentParser(description="Change a worker's load profile live.")
    parser.add_argument("worker", choices=WORKERS + ["all"])
    modes = parser.add_subparsers(dest="mode", required=True, metavar="mode")

    def sine_options(p):
        p.add_argument("--period", type=float, default=120, help="seconds per wave (120)")
        p.add_argument("--min", type=float, default=0.1, help="lowest level (0.1)")
        p.add_argument("--max", type=float, default=1.0, help="highest level (1.0)")
        p.add_argument("--phase", type=float, default=0, help="shift the wave by seconds (0)")

    sine_options(modes.add_parser("sine", help="smooth wave"))

    noisy = modes.add_parser("noisy_sine", help="wave plus random noise")
    sine_options(noisy)
    noisy.add_argument("--noise", type=float, default=0.1, help="noise strength, std dev (0.1)")
    noisy.add_argument("--hold", type=float, default=1, help="seconds per noise value (1)")
    noisy.add_argument("--seed", type=int, default=0, help="random seed (0)")

    burst = modes.add_parser("bursts", help="low baseline with random spikes")
    burst.add_argument("--base", type=float, default=0.1, help="baseline level (0.1)")
    burst.add_argument("--height", type=float, default=1.0, help="spike level (1.0)")
    burst.add_argument("--duration", type=float, default=20, help="seconds per spike (20)")
    burst.add_argument("--gap", type=float, default=60, help="average seconds between spikes (60)")
    burst.add_argument("--seed", type=int, default=0, help="random seed (0)")

    step = modes.add_parser("steps", help="fixed levels at fixed times")
    step.add_argument("--steps", type=parse_steps, default=[[0, 0.2], [60, 0.9]],
                      help="time:level pairs (0:0.2,60:0.9)")
    step.add_argument("--repeat", type=float, default=0,
                      help="restart the schedule every N seconds (0 = hold the last level)")

    const = modes.add_parser("constant", help="one fixed level")
    const.add_argument("--level", type=float, default=0.5, help="level (0.5)")

    named = modes.add_parser("profile", help="named profile from load/profiles/")
    named.add_argument("name", help="e.g. sine, bursts, steps")

    spike = modes.add_parser("spike", help="one extra spike on top of the current load "
                                           "(the profile keeps running)")
    spike.add_argument("--height", type=float, default=0.5,
                       help="added on top of the current level, at most 1.0 in total (0.5)")
    spike.add_argument("--duration", type=float, default=30, help="seconds (30)")
    return parser


def main():
    args = build_parser().parse_args()
    workers = WORKERS if args.worker == "all" else [args.worker]

    if args.mode == "profile":
        if args.name not in named_profiles():
            sys.exit(f"unknown profile {args.name!r}, choose from: {', '.join(named_profiles())}")
        written = apply_named_profile(args.name, workers)
    elif args.mode == "spike":
        problems = check({"height": args.height, "duration": args.duration})
        if problems:
            sys.exit("not changed: " + "; ".join(problems))
        written = {worker: write_spike(worker, args.height, args.duration) for worker in workers}
    else:
        # All options of the chosen mode (except the worker) form the profile.
        profile = {key: value for key, value in vars(args).items() if key != "worker"}
        problems = check(profile)
        if problems:
            sys.exit("not changed: " + "; ".join(problems))
        written = {worker: write_profile(worker, profile) for worker in workers}

    for worker, profile in written.items():
        print(f"{worker}: {json.dumps(profile)}")


if __name__ == "__main__":
    main()
