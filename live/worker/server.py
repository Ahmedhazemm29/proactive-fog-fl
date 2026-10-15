"""
One "pod" of the live demo (step 4B): a small HTTP service.

GET /work runs one of Dogani's three tasks, picked at random with equal chance:
  1. sort an array of 3000 random numbers
  2. eigenvalues of a 100 x 100 random matrix
  3. compress a small file (64 KB of text, made once at start)
GET /health answers at once, so the runner knows the worker is ready.

Standard library plus numpy only. One thread per connection (the load
balancer keeps its connections open), HTTP/1.1 keep-alive.
"""
import json
import os
import random
import signal
import sys
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

PORT = int(os.environ.get("PORT", "8000"))

# The "small file": 64 KB of random words, so it compresses like real text.
WORDS = [f"word{i}" for i in range(500)]
SMALL_FILE = " ".join(random.Random(0).choices(WORDS, k=9000)).encode()[:65536]


def sort_task(rng):
    return float(np.sort(rng.random(3000))[0])


def eigen_task(rng):
    return float(np.abs(np.linalg.eigvals(rng.random((100, 100)))).max())


def compress_task(rng):
    return len(zlib.compress(SMALL_FILE, 6))


TASKS = [sort_task, eigen_task, compress_task]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"          # keep the connection open between requests
    # Send small answers at once. With Nagle's algorithm on, the body waits
    # for the ACK of the headers, which adds about 40 ms to most requests.
    disable_nagle_algorithm = True

    def do_GET(self):
        if self.path == "/health":
            self.reply({"ok": True})
        elif self.path == "/work":
            rng = np.random.default_rng()
            index = random.randrange(len(TASKS))
            self.reply({"task": TASKS[index].__name__, "result": TASKS[index](rng)})
        else:
            self.send_error(404)

    def reply(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass                                  # no line per request


def main():
    # As PID 1 in a container, Python ignores SIGTERM unless we handle it,
    # and `docker stop` would then wait for its timeout.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.daemon_threads = True
    print(f"worker ready on port {PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
