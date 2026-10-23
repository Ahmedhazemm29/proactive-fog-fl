# ESP32 helper tools

All scripts use only the Python standard library. Run them from the repo
root. None contains a password: Wi-Fi details stay in the FL project's
git-ignored `secrets.h`, and the MQTT broker needs no login.
`fl_control.py` is the only laptop tool that publishes on the broker.

## fl_control.py

Join and leave for the ESP32 FL clients. Every board starts in standby
(connected, out of the rounds):

```
python3 hardware/tools/fl_control.py join ESP-1 ESP-2 ESP-3 ESP-4
python3 hardware/tools/fl_control.py leave ESP-5
python3 hardware/tools/fl_control.py status
```

- `join` / `leave` send the command to each board's `fog/<id>/control`, with
  QoS 1 and never retained. Then they wait up to `--timeout` seconds (default 5)
  for each board's fresh status (`online-active` or `online-standby`) and print
  for each board whether it confirmed. A join takes effect from the next round,
  a leave at once. Exit code 0 means every board confirmed.
- `status` only reads: the current run and round, every board's stored status,
  and a warning if a command is stored on a control topic (it must never be).
- Board names map to FL IDs through `hardware/esp_clients.md`.
- Every command is logged with its local time and epoch to
  `data/fl-runs/control.csv` of the main checkout. While a run is going on it
  also goes to that run's `data/fl-runs/<date>_<run>/control.csv`. Commands
  sent before a run starts get into the run's folder when `pi/pull_runs.py`
  copies the run. That way joins and leaves can be lined up with the CPU load later.

## mqtt_watch.py

A read-only MQTT subscriber that never publishes. It prints every message on
a topic and marks each one `retained` (a stored message sent right after
subscribing) or `fresh` (sent live). Use it to see the status of all FL
clients:

```
python3 hardware/tools/mqtt_watch.py fognode1.local 'fog/+/status' --seconds 5
```

Each line is `<epoch time> <retained|fresh> <topic> <payload>`, for example
`1792762648.031 retained fog/esp32-8a50/status online`.

## fl_flash_one.py

Flashes the FL firmware onto one board and checks that it comes back online:

1. Reads the MAC on the port with `esptool read_mac`. If it isn't the
   expected MAC, it stops without flashing.
2. Subscribes to `fog/<id>/status` with `mqtt_watch.py`.
3. Flashes the PlatformIO env (default `fl`). The flashing tool must report
   the same MAC.
4. Waits up to 90 s for a fresh online status that arrives after the flash:
   `online-standby` (the FL firmware always starts in standby), or plain
   `online` from the older firmware. A retained status doesn't count, because
   the broker keeps it from the board's previous session.

The FL ID is `esp32-<last 2 bytes of the MAC>`, as in the firmware. For
example, for ESP-1 with the FL firmware in `esp32/` (it needs its git-ignored
`esp32/include/secrets.h`):

```
python3 hardware/tools/fl_flash_one.py ESP-1 1c:c3:ab:ba:8a:50 /dev/ttyUSB0 --project esp32
```

`/dev/ttyUSB` numbers change on replug, so give the MAC from
`hardware/esp_clients.md` (PR #36). The port is only checked against it.
Exit code 0 means flashed and online; anything else means stop. Flash one
board at a time. Logs go to `data/esp_flash/` (git-ignored).

Options: `--env` (PlatformIO env, default `fl`) and `--broker` (default
`fognode1.local`). It needs `esptool.py` and `pio`, from PATH or their default
install places (`~/.local/bin`, `~/.platformio/penv/bin`).
