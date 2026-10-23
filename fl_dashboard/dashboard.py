"""
Live FL dashboard: the ESP32 FL clients and the aggregator's rounds, in the browser.

Start it from the repo root, then open http://127.0.0.1:8766 in a browser:

    python3 fl_dashboard/dashboard.py --rounds 5

--rounds is the run's total number of rounds (the FL_ROUNDS given to
pi/deploy.sh). The aggregator doesn't send it over MQTT, so without --rounds the
page shows "of ?" until the run has finished.

Read-only: it only listens to the Pi's MQTT broker and never publishes, so it
changes nothing on the broker, the Pi or the boards, and it doesn't start a run.
A browser can't speak plain MQTT (port 1883), so this small server listens to the
broker (mqtt_listen.py), keeps the picture of the run (fl_state.py) and serves
the page (static/) plus /api/state, which the page asks for every second.

Only the Python standard library is used. The server listens on 127.0.0.1, so
other computers can't reach it.
"""
import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from fl_state import TOPICS, FLState, load_boards
from mqtt_listen import Listener

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
STATIC_DIR = HERE / "static"
HOST = "127.0.0.1"

# Every file the page may load; nothing else is served
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/static/style.css": ("style.css", "text/css; charset=utf-8"),
    "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/static/vendor/chart-4.5.1.umd.min.js": ("vendor/chart-4.5.1.umd.min.js",
                                              "text/javascript; charset=utf-8"),
}

STATE = None     # the FLState, set in main()
PORT = None      # the page's port, set in main()


# ----------------------------------------------------------------------
# The web server
# ----------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    """Serves the page's files and /api/state, nothing else."""

    def do_GET(self):
        # Answer only requests for this page's own address, so another web site
        # can't read the data through a made-up host name (DNS rebinding)
        if self.headers.get("Host") not in (f"{HOST}:{PORT}", f"localhost:{PORT}"):
            return self.reply(403, b"Forbidden", "text/plain; charset=utf-8")
        path = self.path.split("?")[0]
        if path == "/api/state":
            body = json.dumps(STATE.snapshot(time.time())).encode()
            return self.reply(200, body, "application/json")
        if path in STATIC:
            name, content_type = STATIC[path]
            return self.reply(200, (STATIC_DIR / name).read_bytes(), content_type)
        self.reply(404, b"Not found", "text/plain; charset=utf-8")

    def reply(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        """Keep the terminal quiet: the page asks for the state every second."""


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    global STATE, PORT
    parser = argparse.ArgumentParser(description="Live FL dashboard (read-only).")
    parser.add_argument("--rounds", type=int,
                        help="total rounds of the run, the FL_ROUNDS of pi/deploy.sh (0 = no limit)")
    parser.add_argument("--broker", default="fognode1.local", help="MQTT broker (default fognode1.local)")
    parser.add_argument("--broker-port", type=int, default=1883, help="MQTT port (default 1883)")
    parser.add_argument("--port", type=int, default=8766, help="port of the page (default 8766)")
    parser.add_argument("--clients", type=Path, default=ROOT / "hardware" / "esp_clients.md",
                        help="board table (default hardware/esp_clients.md)")
    parser.add_argument("--skip", default="ESP-7",
                        help='boards of the table not to show, comma-separated (default ESP-7, '
                             'the faulty one; --skip "" shows all)')
    args = parser.parse_args()

    boards = load_boards(args.clients)
    skip = {name.strip() for name in args.skip.split(",") if name.strip()}
    for name in sorted(skip - {name for name, _ in boards}):
        print(f"note: --skip {name}: no such board in {args.clients}")
    STATE = FLState(boards, skip, args.rounds, (args.broker, args.broker_port))
    PORT = args.port

    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as error:
        raise SystemExit(f"cannot listen on {HOST}:{PORT} ({error}). Is the dashboard running already?")
    listener = Listener(args.broker, args.broker_port, TOPICS, STATE.on_message, STATE.set_broker)
    listener.start()
    shown = len(STATE.expected)
    print(f"FL dashboard: http://{HOST}:{PORT}   ({shown} boards; read-only, listening to "
          f"{args.broker}:{args.broker_port}; stop it with Ctrl+C)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        listener.stop()
        listener.join(timeout=2)            # lets it send DISCONNECT
        server.server_close()


if __name__ == "__main__":
    main()
