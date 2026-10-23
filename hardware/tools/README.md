# ESP32 helper tools

Both scripts use only the Python standard library. Run them from the repo
root. Neither contains a password: Wi-Fi details stay in the FL project's
git-ignored `secrets.h`, and the MQTT broker needs no login.

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
4. Waits up to 90 s for a fresh `online` that arrives after the flash. A
   retained `online` doesn't count, because the broker keeps it from
   the board's previous session.

The FL ID is `esp32-<last 2 bytes of the MAC>`, as in the firmware. For
example, for ESP-1 with the FL project from PR #35 checked out in
`../Autoscaling-fl`:

```
python3 hardware/tools/fl_flash_one.py ESP-1 1c:c3:ab:ba:8a:50 /dev/ttyUSB0 --project ../Autoscaling-fl/esp32
```

`/dev/ttyUSB` numbers change on replug, so give the MAC from
`hardware/esp_clients.md` (PR #36). The port is only checked against it.
Exit code 0 means flashed and online; anything else means stop. Flash one
board at a time. Logs go to `data/esp_flash/` (git-ignored).

Options: `--env` (PlatformIO env, default `fl`) and `--broker` (default
`fognode1.local`). It needs `esptool.py` and `pio`, from PATH or their default
install places (`~/.local/bin`, `~/.platformio/penv/bin`).
