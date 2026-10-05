"""
Local control page for the workers' load, for live demos.

Start it, then open http://127.0.0.1:8765 in a browser:

    .venv/bin/python scripts/control_page.py

For each worker the page shows the current load profile and lets you
  - pick a mode: sine, noisy_sine, bursts, steps or constant. A picked mode
    starts with the values of load/profiles/<mode>.json (the experiments' values);
  - move that mode's main settings with sliders. A change is applied when you
    let go of a slider, not while dragging, because a changed profile starts
    again from t = 0;
  - "Spike now": one extra spike on top of the current load, without
    restarting the profile (see "Spike now" in workload/workload.py).
"Both workers" starts a named profile on both workers at the same moment, as
the experiments do, so for example the two sine waves are 60 s apart again.

Every change goes through scripts/set_load.py (imported, not copied), so the
checks and the atomic file writes are the same as on the command line.
Only the workers read load/. The controllers never read it, nor this page:
they see nothing but Prometheus and the CPU limits.

While an experiment runs (scripts/run_experiments.py), the page shows a red
warning and refuses every change, because a manual change would spoil the run.

Only the Python standard library is used. The page listens on 127.0.0.1, so
other computers can't reach it.
"""
import glob
import json
import os
import re
import subprocess
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# scripts/set_load.py, next to this file
from set_load import (LOAD_DIR, PROFILES_DIR, ROOT, WORKERS, apply_named_profile, build_parser,
                      check, named_profiles, write_profile, write_spike)

HOST = "127.0.0.1"   # this computer only
PORT = 8765
GRAFANA_URL = "http://localhost:3000/d/cpu-demo?orgId=1&kiosk"
RUNS_DIR = os.path.join(ROOT, "data", "runs")


# ----------------------------------------------------------------------
# The sliders of every mode: setting -> (label, lowest, highest, step, unit)
# ----------------------------------------------------------------------
SINE = {
    "period": ("period: one wave", 20, 300, 10, "s"),
    "min": ("min: lowest level", 0, 1, 0.05, ""),
    "max": ("max: highest level", 0, 1, 0.05, ""),
    "phase": ("phase: shifts the wave", 0, 300, 5, "s"),
}
SLIDERS = {
    "sine": SINE,
    "noisy_sine": {**SINE,
                   "noise": ("noise: strength", 0, 0.5, 0.05, ""),
                   "hold": ("hold: new noise every", 1, 30, 1, "s")},
    "bursts": {
        "base": ("base: level between spikes", 0, 1, 0.05, ""),
        "height": ("height: spike level", 0, 1, 0.05, ""),
        "duration": ("duration: spike length", 5, 120, 5, "s"),
        "gap": ("gap: average pause", 10, 300, 10, "s"),
    },
    # A steps profile is shown as two levels: "first" from t = 0, "second" from "switch".
    "steps": {
        "first": ("first level", 0, 1, 0.05, ""),
        "second": ("second level", 0, 1, 0.05, ""),
        "switch": ("second level from", 10, 300, 10, "s"),
        "repeat": ("repeat every (0 = never)", 0, 600, 10, "s"),
    },
    "constant": {"level": ("level", 0, 1, 0.05, "")},
}
SPIKE_SLIDERS = {
    "height": ("height: added on top", 0.05, 1, 0.05, ""),
    "duration": ("duration", 5, 120, 5, "s"),
}


# ----------------------------------------------------------------------
# Profiles: reading them, and the values the sliders show
# ----------------------------------------------------------------------
def defaults(worker, mode):
    """set_load.py's defaults of a mode (or of "spike"), e.g. {"mode": "constant", "level": 0.5}."""
    values = vars(build_parser().parse_args([worker, mode]))
    values.pop("worker")
    return values


def start_profile(worker, mode):
    """
    The settings a picked mode starts with: set_load.py's defaults, overwritten
    by this worker's part of load/profiles/<mode>.json, the experiments' values.
    """
    profile = defaults(worker, mode)
    path = os.path.join(PROFILES_DIR, f"{mode}.json")
    if os.path.exists(path):
        with open(path) as f:
            profile.update(json.load(f).get(worker, {}))
    return profile


def current_profile(worker):
    """
    (profile, problem): the worker's load file, with set_load.py's defaults for
    settings it leaves out. profile is None if there is no usable file.
    """
    path = os.path.join(LOAD_DIR, f"{worker}.json")
    try:
        with open(path) as f:
            profile = json.load(f)
    except FileNotFoundError:
        return None, "no load file, so the worker runs its default sine wave"
    except ValueError as error:
        return None, f"{os.path.relpath(path, ROOT)} is broken: {error}"
    if not isinstance(profile, dict) or profile.get("mode") not in SLIDERS:
        return None, f"{os.path.relpath(path, ROOT)} has no known mode"
    return {**defaults(worker, profile["mode"]), **profile}, None


def two_steps(profile):
    """A steps profile as two levels: (first level, switch time, second level)."""
    schedule = sorted(profile["steps"])
    first = schedule[0][1]
    switch, second = schedule[1] if len(schedule) > 1 else (60, first)
    return first, switch, second


def slider_value(profile, key):
    """The value a slider shows for a profile."""
    if profile["mode"] == "steps" and key in ("first", "switch", "second"):
        return dict(zip(("first", "switch", "second"), two_steps(profile)))[key]
    return profile[key]


def with_setting(profile, key, value):
    """A copy of the profile with one slider's setting changed."""
    new = {k: v for k, v in profile.items() if k != "set_at"}
    if new["mode"] == "steps" and key in ("first", "switch", "second"):
        levels = dict(zip(("first", "switch", "second"), two_steps(new)), **{key: value})
        new["steps"] = [[0, levels["first"]], [levels["switch"], levels["second"]]]
    else:
        new[key] = value
    return new


def text(value):
    """120.0 -> '120', 0.15 -> '0.15'"""
    return f"{value:g}" if isinstance(value, (int, float)) else str(value)


def describe(profile):
    """The settings as one line, e.g. 'level 0.8 · set at 05:39:09'."""
    units = {key: spec[4] for sliders in SLIDERS.values() for key, spec in sliders.items()}
    parts = []
    for key, value in profile.items():
        if key == "steps":
            parts.append("levels " + ", ".join(f"{text(level)} from {text(at)} s"
                                               for at, level in sorted(value)))
        elif key not in ("mode", "set_at"):
            parts.append(f"{key} {text(value)} {units.get(key, '')}".strip())
    if "set_at" in profile:
        parts.append(f"set at {profile['set_at'][11:19]}")
    # No line break inside a part ("duration 20 s"), only between parts or after a comma.
    return " · ".join(part.replace(" ", " ").replace(", ", ", ") for part in parts)


# ----------------------------------------------------------------------
# What the workers do right now, from their last log lines
# ----------------------------------------------------------------------
LOAD_LINE = re.compile(r"load t=(\d+) mode=(\S+) intensity=([\d.]+)")   # every second
SPIKE_LINE = re.compile(r"spike: \+([\d.]+) for (\d+) s")              # at a spike's start


def worker_now(worker):
    """
    {"t", "intensity", "spike", "spike_left"} from the worker's last log lines:
    the time in its profile, its intended load, and a running spike.
    None if docker gives no log.
    """
    try:
        lines = subprocess.run(["docker", "logs", "--tail", "200", worker], capture_output=True,
                               text=True, timeout=5).stdout.splitlines()
    except (OSError, subprocess.TimeoutExpired):
        return None
    now = None
    spike, spike_left = 0.0, 0
    for line in lines:   # oldest first, counting down the seconds of a spike as the worker does
        load, new_spike = LOAD_LINE.match(line), SPIKE_LINE.match(line)
        if new_spike:
            spike, spike_left = float(new_spike.group(1)), int(new_spike.group(2))
        elif line.startswith("load profile:"):
            spike_left = 0   # a new profile ends a spike
        elif load:
            now = {"t": int(load.group(1)), "intensity": float(load.group(3))}
            spike_left = max(0, spike_left - 1)
    if now:
        now.update(spike=spike, spike_left=spike_left)
    return now


# ----------------------------------------------------------------------
# Is an experiment running?
# ----------------------------------------------------------------------
def runner_running():
    """
    Which experiment runner is running, or None.
    scripts/run_experiments.py keeps its pid in <out-dir>/runner.pid while it
    runs (by default data/runs/<profile>/runner.pid) and removes it at the end.
    """
    for pid_file in sorted(glob.glob(os.path.join(RUNS_DIR, "**", "runner.pid"), recursive=True)):
        try:
            with open(pid_file) as f:
                pid = int(f.read())
            os.kill(pid, 0)   # signal 0 only checks that the process exists
        except (OSError, ValueError):
            continue          # left over from a runner that is gone
        return f"pid {pid}, {os.path.relpath(pid_file, ROOT)}"
    # A runner started with another --out-dir keeps its pid file somewhere else.
    try:
        found = subprocess.run(["pgrep", "-f", r"python.*run_experiments\.py"],
                               capture_output=True, text=True).stdout.split()
    except OSError:
        found = []
    return f"pid {found[0]}, scripts/run_experiments.py" if found else None


# ----------------------------------------------------------------------
# What the page shows
# ----------------------------------------------------------------------
def sliders_for(table, values):
    """The page's description of a group of sliders, with their current values."""
    return [{"key": key, "label": label, "min": low, "max": high, "step": step, "unit": unit,
             "value": values[key]}
            for key, (label, low, high, step, unit) in table.items()]


def worker_state(worker):
    """One worker's card: its mode, settings and sliders, and what it does now."""
    card = {"name": worker, "mode": None, "settings": None, "sliders": [],
            "now": worker_now(worker)}
    profile, problem = current_profile(worker)
    if profile is None:
        return dict(card, settings=problem)   # only the mode buttons are shown
    sliders = SLIDERS[profile["mode"]]
    try:
        values = {key: slider_value(profile, key) for key in sliders}
        return dict(card, mode=profile["mode"], settings=describe(profile),
                    sliders=sliders_for(sliders, values))
    except (LookupError, TypeError, ValueError):   # e.g. a load file edited by hand
        return dict(card, settings=f"load/{worker}.json has settings the page can't show")


def page_state():
    """Everything the page shows, asked for every 2 seconds."""
    return {
        "runner": runner_running(),
        "modes": list(SLIDERS),
        "named": named_profiles(),
        "spike": sliders_for(SPIKE_SLIDERS, defaults(WORKERS[0], "spike")),
        "workers": [worker_state(worker) for worker in WORKERS],
    }


# ----------------------------------------------------------------------
# Changes. Each takes the page's request and returns a message, or raises
# an error (ValueError for a bad value): then nothing was changed.
# ----------------------------------------------------------------------
def pick(value, allowed, what):
    if value not in allowed:
        raise ValueError(f"unknown {what} {value!r}")
    return value


def number(value, table, key):
    """A slider's value from the page, checked against the slider's range."""
    _, low, high, _, _ = table[key]
    value = float(value)
    if not low <= value <= high:
        raise ValueError(f"{key} must be between {low:g} and {high:g}")
    return round(value, 3)


def save(worker, profile):
    """Check a profile with set_load.py's rules, then write it as set_load.py does."""
    problems = check(profile)
    if problems:
        raise ValueError("; ".join(problems))
    written = write_profile(worker, profile)
    return f"{worker}: {written['mode']} · {describe(written)}"


def pick_mode(request):
    """Switch a worker to another mode (it starts at t = 0)."""
    worker = pick(request.get("worker"), WORKERS, "worker")
    mode = pick(request.get("mode"), SLIDERS, "mode")
    return save(worker, start_profile(worker, mode))


def move_slider(request):
    """Change one setting of a worker's profile (the profile starts again at t = 0)."""
    worker = pick(request.get("worker"), WORKERS, "worker")
    profile, problem = current_profile(worker)
    if profile is None:
        raise ValueError(f"{problem}. Pick a mode first.")
    sliders = SLIDERS[profile["mode"]]
    key = pick(request.get("key"), sliders, f"{profile['mode']} setting")
    return save(worker, with_setting(profile, key, number(request.get("value"), sliders, key)))


def spike_now(request):
    """One extra spike on top of the worker's current load. The profile keeps running."""
    worker = pick(request.get("worker"), WORKERS, "worker")
    height = number(request.get("height"), SPIKE_SLIDERS, "height")
    duration = number(request.get("duration"), SPIKE_SLIDERS, "duration")
    problems = check({"height": height, "duration": duration})
    if problems:
        raise ValueError("; ".join(problems))
    write_spike(worker, height, duration)
    return f"{worker}: spike +{height:g} for {duration:g} s"


def both_named(request):
    """Start a named profile on both workers at the same moment, as the experiments do."""
    name = pick(request.get("name"), named_profiles(), "profile")
    apply_named_profile(name)
    return f"both workers: profile {name} (load/profiles/{name}.json)"


ACTIONS = {"/api/mode": pick_mode, "/api/setting": move_slider,
           "/api/spike": spike_now, "/api/named": both_named}
WRITE_LOCK = threading.Lock()   # one change at a time: the server answers in threads


# ----------------------------------------------------------------------
# The web server
# ----------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path == "/":
            self.reply(200, PAGE.encode(), "text/html; charset=utf-8")
        elif self.path == "/api/state":
            self.reply_json(200, page_state())
        else:
            self.reply_json(404, {"error": "not found"})

    def do_POST(self):
        # Changes come only from this page. Another web site open in the same
        # browser would have another Host, or could not send JSON without asking.
        if (self.headers.get("Host") not in (f"{HOST}:{PORT}", f"localhost:{PORT}")
                or self.headers.get("Content-Type") != "application/json"):
            return self.reply_json(403, {"error": "Refused: not from the control page."})
        action = ACTIONS.get(self.path)
        if action is None:
            return self.reply_json(404, {"error": "not found"})

        runner = runner_running()
        if runner:
            return self.refuse(409, f"an experiment is running ({runner})")
        try:
            request = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            with WRITE_LOCK:
                message = action(request)
        except (ValueError, TypeError, LookupError, AttributeError) as error:
            return self.refuse(400, error)
        print(f"{datetime.now():%H:%M:%S} {message}", flush=True)
        self.reply_json(200, {"message": message})

    def refuse(self, status, reason):
        message = f"Not changed: {reason}"
        print(f"{datetime.now():%H:%M:%S} {message}", flush=True)
        self.reply_json(status, {"error": message})

    def reply(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def reply_json(self, status, data):
        self.reply(status, json.dumps(data).encode(), "application/json")

    def log_message(self, format, *args):
        """Keep the terminal quiet: the page asks for the state every 2 seconds."""


# ----------------------------------------------------------------------
# The page: HTML, CSS and JavaScript in one piece
# ----------------------------------------------------------------------
PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Worker load control</title>
<link rel="icon" href="data:,">  <!-- no icon, so the browser does not ask for /favicon.ico -->
<style>
  /* Blue and orange are the dashboard's "used" and "demand" colours. --spike-ink is a
     darker (light mode) or lighter (dark mode) orange, so spike text stays readable. */
  :root {
    --bg: #f4f5f7; --card: #ffffff; --ink: #1c2230; --muted: #5b6475; --line: #d8dde6;
    --accent: #3987e5; --spike: #d95926; --spike-ink: #b4441a; --spike-button: #b4441a;
    --track: #eceff3; --danger: #b42318; --danger-bg: #fdecea;
    color-scheme: light;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #111217; --card: #181b1f; --ink: #e4e7ec; --muted: #9ba3b4; --line: #2e333d;
      --spike-ink: #f08a5d; --track: #2e333d; --danger: #ff9b8f; --danger-bg: #3b1513;
      color-scheme: dark;
    }
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--ink);
         font: 18px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
  main { max-width: 1200px; margin: 0 auto; padding: 24px 16px 40px; }
  header { display: flex; flex-wrap: wrap; gap: 12px 24px; align-items: center;
           justify-content: space-between; }
  h1 { font-size: 30px; margin: 0; }
  .sub { color: var(--muted); margin: 2px 0 0; }
  button, a.button {
    font: inherit; font-size: 16px; padding: 8px 14px; border-radius: 8px; cursor: pointer;
    border: 1px solid var(--line); background: var(--card); color: var(--ink); text-decoration: none;
  }
  button:hover:not(:disabled), a.button:hover { border-color: var(--muted); }
  button:disabled { cursor: not-allowed; }
  :focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }
  #runner { margin: 20px 0 0; padding: 14px 18px; border-radius: 10px; font-weight: 600;
            background: var(--danger-bg); color: var(--danger); border: 2px solid var(--danger); }
  fieldset { border: 0; margin: 0; padding: 0; min-width: 0; }
  fieldset:disabled { opacity: 0.45; }
  .both { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 20px 0; }
  .both > span:first-child { color: var(--muted); margin-right: 4px; }
  #named { display: contents; }
  .cards { display: grid; gap: 20px; grid-template-columns: repeat(auto-fit, minmax(min(100%, 440px), 1fr)); }
  .card { background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 20px; }
  .card h2 { margin: 0; font-size: 24px; }
  .now { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 12px; margin-top: 6px; }
  .now .value { font-size: 44px; font-weight: 700; font-variant-numeric: tabular-nums; }
  .now .detail { color: var(--muted); }
  .spiking .now .detail { color: var(--spike-ink); font-weight: 600; }
  .bar { height: 10px; border-radius: 5px; background: var(--track); overflow: hidden; }
  .bar span { display: block; height: 100%; width: 0; background: var(--accent); transition: width .5s; }
  .spiking .bar span { background: var(--spike); }
  /* room for two lines, so both cards keep their buttons at the same height */
  .settings { color: var(--muted); font-size: 16px; margin: 12px 0 0; min-height: 2.9em; }
  .modes { display: flex; flex-wrap: wrap; gap: 6px; margin: 14px 0 6px; }
  .modes button[aria-pressed="true"] { background: var(--ink); color: var(--card); border-color: var(--ink); }
  .slider { display: grid; grid-template-columns: 1fr auto; gap: 0 12px; margin: 12px 0 0; }
  .slider input { grid-column: 1 / -1; width: 100%; margin: 6px 0 0; accent-color: var(--accent); }
  .slider output { font-weight: 600; font-variant-numeric: tabular-nums; }
  .spike { border-top: 1px solid var(--line); margin-top: 18px; padding-top: 14px; }
  .spike h3 { margin: 0; font-size: 18px; }
  .spike p { margin: 2px 0 0; color: var(--muted); font-size: 16px; }
  .spike button { margin-top: 14px; background: var(--spike-button); border-color: var(--spike-button);
                  color: #fff; font-weight: 700; }
  #status { min-height: 1.5em; margin: 16px 0 0; color: var(--muted); }
  #status.error { color: var(--danger); font-weight: 600; }
</style>
</head>
<body>
<main>
  <header>
    <div>
      <h1>Worker load</h1>
      <p class="sub">What the two training workers are asked to do. The controllers never see this.</p>
    </div>
    <a class="button" href="GRAFANA_URL" target="_blank" rel="noopener">Grafana demo dashboard ↗</a>
  </header>
  <p id="runner" role="alert" hidden></p>
  <fieldset id="controls">
    <div class="both"><span>Both workers, as in the experiments:</span><span id="named"></span></div>
    <div class="cards" id="cards"></div>
  </fieldset>
  <p id="status" role="status"></p>
</main>
<script>
// The page asks the server for the state every 2 seconds and draws it.
// Sliders send their value only when they are let go ("change" event), not
// while dragging ("input" event), because every change of a profile starts
// it again from t = 0.

const cards = {};   // worker name -> the parts of its card
let asked = 0;      // number of the latest state request
let drawn = 0;      // number of the state on screen

function make(tag, properties = {}, ...children) {
  const node = Object.assign(document.createElement(tag), properties);
  node.append(...children);
  return node;
}

function show(value, unit) {
  return unit === "s" ? `${Math.round(Number(value))} s` : Number(value).toFixed(2);
}

function setStatus(message, isError) {
  const status = document.getElementById("status");
  status.textContent = message;
  status.className = isError ? "error" : "";
}

async function post(path, body) {
  try {
    const response = await fetch(path, {method: "POST", headers: {"Content-Type": "application/json"},
                                        body: JSON.stringify(body)});
    const answer = await response.json();
    setStatus(answer.message || answer.error, !response.ok);
  } catch (error) {
    setStatus("No answer from the control page. Is scripts/control_page.py still running?", true);
  }
  refresh();
}

// A slider with its label and value. onRelease(value) runs when it is let go.
function slider(spec, onRelease) {
  const output = make("output", {textContent: show(spec.value, spec.unit)});
  // min, max and step before value, or the browser rounds the value to the default range
  const input = make("input", {type: "range", min: spec.min, max: spec.max, step: spec.step,
                               value: spec.value});
  input.addEventListener("input", () => { output.textContent = show(input.value, spec.unit); });
  input.addEventListener("change", () => onRelease(Number(input.value)));
  return make("label", {className: "slider"}, make("span", {textContent: spec.label}), output, input);
}

// A worker's card, made once. Its mode buttons and sliders are filled in by draw().
function card(worker, spikeSpecs) {
  const parts = {
    value: make("span", {className: "value"}),
    detail: make("span", {className: "detail"}),
    bar: make("span"),
    settings: make("p", {className: "settings"}),
    modes: make("div", {className: "modes"}),
    sliders: make("div"),
    shown: null,
  };
  parts.modes.setAttribute("role", "group");
  parts.modes.setAttribute("aria-label", `${worker} mode`);
  // The spike sliders only choose the next spike; nothing is sent until the button.
  const spikeSliders = spikeSpecs.map(spec => slider(spec, () => {}));
  const button = make("button", {textContent: "Spike now"});
  button.addEventListener("click", () => {
    const [height, duration] = spikeSliders.map(label => Number(label.querySelector("input").value));
    post("/api/spike", {worker, height, duration});
  });
  parts.root = make("section", {className: "card"},
    make("h2", {textContent: worker}),
    make("div", {className: "now"}, parts.value, parts.detail),
    make("div", {className: "bar"}, parts.bar),
    parts.settings, parts.modes, parts.sliders,
    make("div", {className: "spike"},
      make("h3", {textContent: "Spike now"}),
      make("p", {textContent: "One extra spike on top of the current load. The profile keeps running."}),
      ...spikeSliders, button));
  document.getElementById("cards").append(parts.root);
  return parts;
}

function draw(info, state) {
  const worker = info.name;
  const parts = cards[worker] || (cards[worker] = card(worker, state.spike));

  // What the worker does this second, from its log.
  const now = info.now;
  parts.value.textContent = now ? now.intensity.toFixed(2) : "–";
  parts.detail.textContent = !now ? "no log from the worker"
    : now.spike_left > 0 ? `load now · spike +${now.spike.toFixed(2)}, ${now.spike_left} s left`
    : `load now · t = ${now.t} s of the profile`;
  parts.bar.style.width = now ? `${now.intensity * 100}%` : "0";
  parts.root.classList.toggle("spiking", Boolean(now && now.spike_left > 0));

  // Mode, settings and sliders are drawn again only when the profile changed,
  // so a slider is never reset while it is being dragged.
  const key = JSON.stringify([info.mode, info.settings]);
  if (parts.shown === key) return;
  parts.shown = key;
  parts.settings.textContent = info.mode ? `${info.mode} · ${info.settings}` : info.settings;
  parts.modes.replaceChildren(...state.modes.map(mode => {
    const button = make("button", {textContent: mode.replace("_", " ")});
    button.setAttribute("aria-pressed", String(mode === info.mode));
    button.addEventListener("click", () => {
      if (mode !== info.mode) post("/api/mode", {worker, mode});
    });
    return button;
  }));
  parts.sliders.replaceChildren(...info.sliders.map(spec =>
    slider(spec, value => post("/api/setting", {worker, key: spec.key, value}))));
}

async function refresh() {
  const number = ++asked;
  let state;
  try {
    state = await (await fetch("/api/state")).json();
  } catch (error) {
    setStatus("No answer from the control page. Is scripts/control_page.py still running?", true);
    return;
  }
  if (number < drawn) return;   // an older answer that arrived late
  drawn = number;
  if (document.getElementById("status").textContent.startsWith("No answer")) setStatus("");

  // An experiment is running: red warning, and every control is switched off.
  const runner = document.getElementById("runner");
  runner.hidden = !state.runner;
  runner.textContent = state.runner ? `An experiment is running (${state.runner}). ` +
    "All controls are off, because a manual change would spoil the run." : "";
  document.getElementById("controls").disabled = Boolean(state.runner);

  const named = document.getElementById("named");
  if (!named.childElementCount) {
    named.append(...state.named.map(name => {
      const button = make("button", {textContent: name.replace("_", " ")});
      button.addEventListener("click", () => post("/api/named", {name}));
      return button;
    }));
  }
  for (const info of state.workers) draw(info, state);
}

refresh();
setInterval(refresh, 2000);
</script>
</body>
</html>
""".replace("GRAFANA_URL", GRAFANA_URL)


def main():
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as error:
        raise SystemExit(f"cannot listen on {HOST}:{PORT} ({error}). Is the page running already?")
    print(f"Control page: http://{HOST}:{PORT}   (stop it with Ctrl+C)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
