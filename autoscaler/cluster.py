"""
The live cluster of step 4B: worker containers behind HAProxy, run with the
docker command line.

- Network live-net (172.30.0.0/24) with fixed addresses, so HAProxy can list
  all 20 possible workers in its config from the start.
- 20 workers are created once (`docker create`), named live-worker-01 .. 20.
  A scale-up starts the next stopped ones, a scale-down stops the newest ones.
- HAProxy (live-haproxy) lists every worker in maintenance mode. The runner
  turns a worker on through HAProxy's runtime API once it answers /health,
  and turns it off before stopping it. Round-robin over the workers that are on.
- Every container has the label thesis.live=1. cleanup() removes exactly
  those containers and the network, nothing else.
- CPU per worker is read from its cgroup file (cpu.stat), which gives the exact
  CPU time of each step. KHPA reads Prometheus instead, like Kubernetes.
"""
import json
import os
import socket
import subprocess
import time
import urllib.parse
import urllib.request

NETWORK = "live-net"
SUBNET = "172.30.0.0/24"
LABEL = "thesis.live=1"
WORKER_IMAGE = "thesis/live-worker:latest"
HAPROXY_IMAGE = "haproxy:2.8.10-alpine"
HAPROXY_NAME = "live-haproxy"
HAPROXY_IP = "172.30.0.2"
MONITORING_NETWORK = "thesis-autoscaler_default"   # Prometheus' network, so it can scrape HAProxy
LB_PORT = 8090            # host port of the load balancer
ADMIN_PORT = 8091         # host port of HAProxy's runtime API
METRICS_PORT = 8404       # host port of HAProxy's Prometheus page
WORKER_PORT = 8000
MAX_WORKERS = 20          # safety cap
CPU_LIMIT = 0.5           # --cpus of every worker
MEMORY_LIMIT = "256m"


def worker_name(i):
    return f"live-worker-{i:02d}"


def worker_ip(i):
    return f"172.30.0.{10 + i}"


def docker(*args, check=True):
    """Run one docker command and return its output."""
    done = subprocess.run(["docker", *args], capture_output=True, text=True)
    if check and done.returncode != 0:
        raise RuntimeError(f"docker {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout.strip()


def haproxy_config(workers=MAX_WORKERS):
    """HAProxy config with every worker listed, all in maintenance ("disabled") at start."""
    servers = "\n".join(f"    server w{i:02d} {worker_ip(i)}:{WORKER_PORT} maxconn 16 disabled"
                        for i in range(1, workers + 1))
    return f"""global
    maxconn 20000
    stats socket ipv4@0.0.0.0:9999 level admin

defaults
    mode http
    # Enough client connections for an open-loop overload: 2,700 requests per
    # second that each wait up to 2 s.
    maxconn 10000
    timeout connect 1s
    # Keep the load generator's idle connections open for a whole run
    timeout client 10m
    timeout http-keep-alive 10m
    timeout server 2s
    # A request waits at most 1 s for a free worker, then gets a 503. It is
    # shorter than the client's 2 s, so an overloaded queue answers 503 instead
    # of keeping requests that nobody waits for any more.
    timeout queue 1s
    # Drop a queued request when its client gives up, so no worker spends CPU on it.
    option abortonclose
    option http-keep-alive

frontend web
    bind :80
    default_backend workers

frontend metrics
    bind :8404
    http-request use-service prometheus-exporter if {{ path /metrics }}

backend workers
    balance roundrobin
    http-reuse always
{servers}
"""


class Cluster:
    """The network, HAProxy and the 20 workers of one run."""

    def __init__(self, config_dir, log=print):
        self.config_dir = config_dir
        self.log = log
        self.ids = {}             # worker number -> container id (for its cgroup file)
        self.running = []         # worker numbers that are on, in start order

    # ---------- setup and cleanup ----------
    def setup(self):
        cleanup(self.log)         # leftovers of a run that was killed
        os.makedirs(self.config_dir, exist_ok=True)
        path = os.path.join(self.config_dir, "haproxy.cfg")
        with open(path, "w") as f:
            f.write(haproxy_config())
        docker("network", "create", "--subnet", SUBNET, "--label", LABEL, NETWORK)
        docker("run", "-d", "--name", HAPROXY_NAME, "--label", LABEL, "--network", NETWORK, "--ip", HAPROXY_IP,
               "-p", f"127.0.0.1:{LB_PORT}:80", "-p", f"127.0.0.1:{ADMIN_PORT}:9999",
               "-p", f"127.0.0.1:{METRICS_PORT}:8404",
               "-v", f"{os.path.abspath(path)}:/usr/local/etc/haproxy/haproxy.cfg:ro", HAPROXY_IMAGE)
        if docker("network", "ls", "-q", "--filter", f"name=^{MONITORING_NETWORK}$"):
            docker("network", "connect", "--alias", HAPROXY_NAME, MONITORING_NETWORK, HAPROXY_NAME)
        for i in range(1, MAX_WORKERS + 1):
            self.ids[i] = docker("create", "--name", worker_name(i), "--label", LABEL,
                                 "--network", NETWORK, "--ip", worker_ip(i),
                                 "--cpus", str(CPU_LIMIT), "--memory", MEMORY_LIMIT, WORKER_IMAGE)
        self.wait_for(lambda: self.admin("show info").startswith("Name: HAProxy"), "HAProxy")
        self.log(f"Cluster ready: HAProxy on 127.0.0.1:{LB_PORT}, {MAX_WORKERS} workers created")

    def wait_for(self, check, what, seconds=20):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                if check():
                    return
            except OSError:
                pass
            time.sleep(0.05)
        raise RuntimeError(f"{what} not ready after {seconds} s")

    # ---------- HAProxy runtime API ----------
    def admin(self, command):
        with socket.create_connection(("127.0.0.1", ADMIN_PORT), timeout=2) as s:
            s.sendall(command.encode() + b"\n")
            chunks = []
            while chunk := s.recv(65536):
                chunks.append(chunk)
        return b"".join(chunks).decode()

    def enabled_in_haproxy(self):
        """Worker numbers HAProxy sends requests to (srv_op_state 2 = running; in maintenance it is 0)."""
        lines = self.admin("show servers state workers").splitlines()
        on = []
        for line in lines[2:]:
            parts = line.split()
            if len(parts) > 6 and parts[5] == "2":
                on.append(int(parts[3][1:]))
        return sorted(on)

    # ---------- scaling ----------
    def scale_to(self, pods):
        """Start or stop workers until `pods` are on. Returns the seconds it took."""
        started = time.monotonic()
        pods = max(0, min(pods, MAX_WORKERS))
        if pods > len(self.running):
            new = [i for i in range(1, MAX_WORKERS + 1) if i not in self.running][:pods - len(self.running)]
            docker("start", *[worker_name(i) for i in new])
            for i in new:
                self.wait_for(lambda i=i: health(i), worker_name(i))
                self.admin(f"set server workers/w{i:02d} state ready")
            self.running += new
        elif pods < len(self.running):
            old = self.running[pods:]
            for i in old:
                self.admin(f"set server workers/w{i:02d} state maint")
            time.sleep(0.2)                     # let the requests in progress finish
            docker("stop", "-t", "2", *[worker_name(i) for i in old])
            self.running = self.running[:pods]
        return time.monotonic() - started

    # ---------- CPU ----------
    def cpu_stat(self):
        """{worker number: (CPU seconds used, seconds throttled)} of the running workers, from cgroup v2."""
        result = {}
        for i in list(self.running):             # a copy: scale_to() may change it meanwhile
            path = f"/sys/fs/cgroup/system.slice/docker-{self.ids[i]}.scope/cpu.stat"
            try:
                with open(path) as f:
                    stat = dict(line.split() for line in f)
                result[i] = (int(stat["usage_usec"]) / 1e6, int(stat["throttled_usec"]) / 1e6)
            except (OSError, KeyError):
                pass                             # just stopped
        return result


def health(i):
    with urllib.request.urlopen(f"http://{worker_ip(i)}:{WORKER_PORT}/health", timeout=0.5) as r:
        return r.status == 200


def cleanup(log=print):
    """Remove every container with the label thesis.live=1 and the network live-net."""
    ids = docker("ps", "-aq", "--filter", f"label={LABEL}", check=False).split()
    if ids:
        docker("rm", "-f", *ids, check=False)
        log(f"Removed {len(ids)} live containers")
    if docker("network", "ls", "-q", "--filter", f"name=^{NETWORK}$", check=False):
        docker("network", "rm", NETWORK, check=False)


def prometheus_cpu(url, window="15s"):
    """KHPA's input: total CPU (cores) of the live workers, as Prometheus sees it from cAdvisor."""
    query = f'sum(rate(container_cpu_usage_seconds_total{{name=~"live-worker-.*"}}[{window}]))'
    with urllib.request.urlopen(f"{url}/api/v1/query?" + urllib.parse.urlencode({"query": query}), timeout=2) as r:
        data = json.load(r)["data"]["result"]
    return float(data[0]["value"][1]) if data else 0.0
