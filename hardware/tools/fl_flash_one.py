"""Flash the FL firmware onto ONE ESP32, identified by its MAC, and wait
for a fresh (not retained) "online" on its fog/<id>/status topic.

    python3 hardware/tools/fl_flash_one.py ESP-1 1c:c3:ab:ba:8a:50 /dev/ttyUSB0 \
        --project ../Autoscaling-fl/esp32

Steps:
  1. esptool read_mac on the port: stop unless it is the expected MAC
  2. subscribe to fog/<id>/status (with mqtt_watch.py)
  3. flash the PlatformIO env (default fl) to that port; the flashing tool
     must also report the expected MAC
  4. wait for a fresh "online" that arrives after the flash finished

The FL ID is esp32-<last 2 bytes of the MAC>, as in the FL firmware.
Exit code 0 = flashed and online; anything else = stop, don't go on.
Logs go to data/esp_flash/ (git-ignored).
"""

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
LOG_DIR = TOOLS_DIR.parent.parent / "data" / "esp_flash"
ONLINE_TIMEOUT_S = 90  # how long to wait for "online" after the flash


def find_tool(name, default):
    """A command from PATH, else from its default install place."""
    return shutil.which(name) or str(default)


def stop(message, watcher=None):
    """Print why we stop and exit with an error."""
    if watcher:
        watcher.kill()
    print("STOP:", message)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Flash the FL firmware onto one ESP32.")
    parser.add_argument("name", help="board name for the output, e.g. ESP-1")
    parser.add_argument("mac", help="expected MAC, e.g. 1c:c3:ab:ba:8a:50")
    parser.add_argument("port", help="serial port, e.g. /dev/ttyUSB0")
    parser.add_argument("--project", required=True, type=Path,
                        help="PlatformIO project of the FL firmware (folder with platformio.ini)")
    parser.add_argument("--env", default="fl", help="PlatformIO env (default fl)")
    parser.add_argument("--broker", default="fognode1.local", help="MQTT broker host name")
    args = parser.parse_args()

    mac = args.mac.lower()
    fl_id = "esp32-" + mac.replace(":", "")[-4:]
    topic = f"fog/{fl_id}/status"
    esptool = find_tool("esptool.py", Path.home() / ".local/bin/esptool.py")
    pio = find_tool("pio", Path.home() / ".platformio/penv/bin/pio")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    print(f"{args.name}: MAC {mac}, FL ID {fl_id}, port {args.port}")

    # 1. Identify the board on this port by its MAC (esptool resets it afterwards)
    out = subprocess.run([esptool, "--port", args.port, "read_mac"],
                         capture_output=True, text=True).stdout
    macs = [line.split()[1].lower() for line in out.splitlines() if line.startswith("MAC:")]
    if macs[:1] != [mac]:
        stop(f"{args.port} reports MAC {macs[0] if macs else 'none'}, "
             f"not {args.name} ({mac}); nothing flashed")
    print(f"1. {args.port} reports MAC {macs[0]}: this is {args.name}")

    # 2. Subscribe to its status topic before flashing
    watch_log = LOG_DIR / f"watch_{fl_id}.log"
    watcher = subprocess.Popen([sys.executable, str(TOOLS_DIR / "mqtt_watch.py"),
                                args.broker, topic, "--seconds", "300"],
                               stdout=open(watch_log, "w"), stderr=subprocess.STDOUT)
    deadline = time.time() + 15
    while "subscribed" not in watch_log.read_text():
        if time.time() > deadline or watcher.poll() is not None:
            stop(f"could not subscribe to {topic}: {watch_log.read_text().strip()}", watcher)
        time.sleep(0.2)
    print(f"2. subscribed to {topic} on {args.broker}")

    # 3. Flash the env onto this port
    upload_log = LOG_DIR / f"upload_{fl_id}.log"
    t_start = time.time()
    with open(upload_log, "w") as log:
        rc = subprocess.run([pio, "run", "-d", str(args.project), "-e", args.env,
                             "-t", "upload", "--upload-port", args.port],
                            stdout=log, stderr=subprocess.STDOUT).returncode
    t_done = time.time()
    upload = upload_log.read_text()
    if rc != 0:
        print(upload[-3000:])
        stop(f"upload to {args.port} failed (pio exit {rc})", watcher)
    # The flashing tool reads the MAC again while connecting: must be the same board
    upload_macs = [l.split("MAC:")[1].strip().lower() for l in upload.splitlines() if "MAC:" in l]
    if upload_macs[:1] != [mac]:
        stop(f"upload connected to MAC {upload_macs[:1]}, expected {mac}", watcher)
    chip = next((l.split(":", 1)[1].strip() for l in upload.splitlines()
                 if "Chip type" in l or "Chip is" in l), "?")
    print(f"3. flashed env {args.env} in {t_done - t_start:.0f} s "
          f"({chip}, MAC {upload_macs[0]} during upload)")

    # 4. Wait for a fresh "online" that arrives after the flash finished.
    # Retained messages and anything from before the flash (the old firmware)
    # don't count.
    while time.time() < t_done + ONLINE_TIMEOUT_S:
        for line in watch_log.read_text().splitlines():
            parts = line.split(" ", 3)
            if (len(parts) == 4 and parts[1] == "fresh" and parts[2] == topic
                    and parts[3] == "online" and float(parts[0]) > t_done):
                watcher.kill()
                print(f"4. fresh 'online' on {topic} {float(parts[0]) - t_done:.1f} s after the flash")
                print("   all messages seen (seconds relative to the end of the flash):")
                for seen in watch_log.read_text().splitlines():
                    p = seen.split(" ", 3)
                    if len(p) == 4:
                        print(f"     {float(p[0]) - t_done:+7.1f}  {p[1]:8} {p[3]}")
                sys.exit(0)
        time.sleep(0.5)
    stop(f"no fresh 'online' on {topic} within {ONLINE_TIMEOUT_S} s after the flash", watcher)


if __name__ == "__main__":
    main()
