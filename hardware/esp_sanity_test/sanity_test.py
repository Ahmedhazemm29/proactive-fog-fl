"""ESP32 hardware sanity test: flash one board, read its output, PASS or FAIL.

Run it with PlatformIO's Python, which already has pyserial:

    ~/.platformio/penv/bin/python hardware/esp_sanity_test/sanity_test.py /dev/ttyUSB0

Steps:
  1. Build the sketch in this folder (src/main.cpp) and flash it with PlatformIO.
  2. Reset the board and read its serial output (115200 baud), at most 25 s.
  3. Print one PASS or FAIL line for the board's MAC address.

PASS means all of these:
  - the MAC address is one of the boards in hardware/esp_clients.md
  - the flash size is reported
  - Wi-Fi connects within 20 seconds
  - the IP address and RSSI are printed
Anything else is FAIL, with the reason. A board that restarts during the
test (for example a brownout from weak USB power) also fails.

Options:
  --no-flash      skip step 1 (the sketch is already on the board)
  --clients PATH  board table to use (default: hardware/esp_clients.md)

Exit code: 0 for PASS, 1 for FAIL.
"""

import argparse
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import serial  # pyserial

# ---- Settings ----

PROJECT_DIR = Path(__file__).resolve().parent  # the PlatformIO project
DEFAULT_CLIENTS = PROJECT_DIR.parent / "esp_clients.md"
SECRETS = PROJECT_DIR / "include" / "secrets.h"

BAUD = 115200        # must match Serial.begin in src/main.cpp
WIFI_LIMIT_S = 20.0  # Wi-Fi must connect within this many seconds
READ_TIME_S = 25.0   # read the output at most this long (limit + boot time)

# ---- Lines the sketch prints (see src/main.cpp) ----

BANNER = "=== ESP32 sanity test ==="  # printed once per boot

# (key, pattern, conversion): a matching line stores its value under key
PATTERNS = [
    ("mac", re.compile(r"^MAC: ([0-9a-f]{2}(?::[0-9a-f]{2}){5})$"), str),
    ("chip", re.compile(r"^Chip: (.+)$"), str),
    ("flash_mb", re.compile(r"^Flash: (\d+) MB$"), int),
    ("wifi_s", re.compile(r"^WiFi: connected after ([\d.]+) s$"), float),
    ("wifi_status", re.compile(r"^WiFi: not connected after [\d.]+ s \(status (.+)\)$"), str),
    ("ip", re.compile(r"^IP: (\d+\.\d+\.\d+\.\d+)$"), str),
    ("rssi", re.compile(r"^RSSI: (-?\d+) dBm$"), int),
]

# Everything a passing board reports; reading stops once all are seen
NEEDED = ["mac", "flash_mb", "wifi_s", "ip", "rssi"]

# A row of the table in esp_clients.md: | ESP-1 | 1c:c3:ab:ba:8a:50 |
CLIENT_ROW = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})\s*\|")


# ---- Board table ----

def load_clients(path):
    """Read the board table: {mac: board name}."""
    if not path.exists():
        sys.exit(f"{path} not found, use --clients PATH")
    clients = {}
    for line in path.read_text().splitlines():
        match = CLIENT_ROW.match(line)
        if match:
            clients[match.group(2).lower()] = match.group(1)
    if not clients:
        sys.exit(f"no MAC addresses found in {path}")
    return clients


# ---- Step 1: flash ----

def find_pio():
    """PlatformIO's pio command: from PATH, else from its default place."""
    on_path = shutil.which("pio")
    if on_path:
        return on_path
    default = Path.home() / ".platformio" / "penv" / "bin" / "pio"
    if default.exists():
        return str(default)
    sys.exit("PlatformIO (pio) not found")


def flash(port):
    """Build the sketch and upload it to the board. True if it worked."""
    cmd = [find_pio(), "run", "--project-dir", str(PROJECT_DIR),
           "--target", "upload", "--upload-port", port]
    print("$", " ".join(cmd), flush=True)
    return subprocess.run(cmd).returncode == 0


# ---- Step 2: read ----

def serial_lines(ser, seconds):
    """Yield each complete line the board prints during the next `seconds`."""
    pending = b""  # received bytes that do not end in a newline yet
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        pending += ser.read(ser.in_waiting or 1)  # waits at most ser.timeout
        while b"\n" in pending:
            raw, pending = pending.split(b"\n", 1)
            yield raw.decode("utf-8", errors="replace").strip()


def parse_line(line, found):
    """Store what one line of the board's output tells us in `found`."""
    if BANNER in line:
        found["boots"] += 1
    if "brownout" in line.lower():
        found["brownout"] = True
    for key, pattern, convert in PATTERNS:
        match = pattern.match(line)
        if match:
            found[key] = convert(match.group(1))


def read_board(port):
    """Reset the board and collect what the sketch reports (a dict)."""
    found = {"boots": 0, "brownout": False}

    # Open the port with DTR and RTS released: on ESP32 dev boards these
    # lines drive the BOOT (IO0) and EN (reset) pins
    ser = serial.Serial()
    ser.port = port
    ser.baudrate = BAUD
    ser.timeout = 0.2  # read() waits at most 0.2 s for data
    ser.dtr = False
    ser.rts = False
    ser.open()

    # Reset the board (RTS pulls EN low), so we see it start from the beginning
    ser.rts = True
    time.sleep(0.1)
    ser.reset_input_buffer()  # drop anything printed before the reset
    ser.rts = False

    for line in serial_lines(ser, READ_TIME_S):
        if not line:
            continue
        print("  |", line, flush=True)
        parse_line(line, found)
        if all(key in found for key in NEEDED):
            break  # everything is there, no need to wait longer
    ser.close()
    return found


# ---- Step 3: judge ----

def judge(found, clients, clients_path):
    """Check the PASS rules. Returns the reasons for FAIL (empty = PASS)."""
    reasons = []

    mac = found.get("mac")
    if mac is None:
        reasons.append("no MAC address in the serial output")
    elif mac not in clients:
        reasons.append(f"MAC {mac} is not in {clients_path}")

    if found.get("flash_mb", 0) <= 0:
        reasons.append("flash size not reported")

    wifi_s = found.get("wifi_s")
    if wifi_s is None:
        last = found.get("wifi_status", "none reported")
        reasons.append(f"Wi-Fi did not connect within {WIFI_LIMIT_S:.0f} s"
                       f" (last status {last})")
    elif wifi_s > WIFI_LIMIT_S:
        reasons.append(f"Wi-Fi took {wifi_s:.1f} s to connect"
                       f" (limit {WIFI_LIMIT_S:.0f} s)")
    elif found.get("ip", "0.0.0.0") == "0.0.0.0" or found.get("rssi", 0) >= 0:
        # Connected, but no usable IP address or signal strength printed
        # (Wi-Fi RSSI is always negative; 0 means "no value")
        reasons.append("IP address or RSSI not printed")

    if found["boots"] > 1:
        why = ", brownout detector triggered" if found["brownout"] else ""
        reasons.append(f"board restarted during the test"
                       f" ({found['boots']} boots{why})")
    return reasons


# ---- Main ----

def main():
    parser = argparse.ArgumentParser(
        description="Flash the sanity test onto one ESP32 and print PASS or FAIL.")
    parser.add_argument("port", help="serial port of the board, e.g. /dev/ttyUSB0")
    parser.add_argument("--no-flash", action="store_true",
                        help="don't flash, only reset the board and check its output")
    parser.add_argument("--clients", type=Path, default=DEFAULT_CLIENTS,
                        help="board table (default: hardware/esp_clients.md)")
    args = parser.parse_args()

    clients = load_clients(args.clients)
    if not Path(args.port).exists():
        sys.exit(f"{args.port} does not exist (is the board plugged in?)")

    # Step 1: flash
    if not args.no_flash:
        if not SECRETS.exists():
            sys.exit(f"{SECRETS} is missing: copy secrets.example.h to"
                     " secrets.h and fill in your Wi-Fi details")
        if not flash(args.port):
            print(f"FAIL unknown board on {args.port}: flashing failed"
                  " (see the PlatformIO output above)")
            return 1

    # Step 2: read
    print(f"Reading {args.port} for up to {READ_TIME_S:.0f} s ...", flush=True)
    try:
        found = read_board(args.port)
    except serial.SerialException as error:
        print(f"FAIL unknown board on {args.port}: could not read the port ({error})")
        return 1

    # Step 3: judge and print one line for this board
    reasons = judge(found, clients, args.clients)
    mac = found.get("mac", "no MAC")
    board = clients.get(mac, "unknown board")
    if reasons:
        print(f"FAIL {board} ({mac}) on {args.port}: " + "; ".join(reasons))
        return 1
    print(f"PASS {board} ({mac}) on {args.port}: {found.get('chip', 'chip unknown')},"
          f" flash {found['flash_mb']} MB, Wi-Fi after {found['wifi_s']:.1f} s,"
          f" IP {found['ip']}, RSSI {found['rssi']} dBm")
    return 0


if __name__ == "__main__":
    sys.exit(main())
