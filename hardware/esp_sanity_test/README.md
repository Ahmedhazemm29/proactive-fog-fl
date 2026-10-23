# ESP32 hardware sanity test

Checks one ESP32 edge client at a time: flashes a small test sketch, reads
the board's serial output and prints PASS or FAIL for its MAC address.

PASS means all of these:

- the MAC address is in [`../esp_clients.md`](../esp_clients.md)
- the flash size is reported
- Wi-Fi connects within 20 seconds
- the IP address and RSSI are printed

Anything else is FAIL, with the reason. A board that restarts during the test
(for example a brownout from weak USB power) also fails.

## Setup (once)

Copy `include/secrets.example.h` to `include/secrets.h` and fill in the Wi-Fi
name and password. `secrets.h` is git-ignored, so the password stays local.

## Test one board

From the repo root, with PlatformIO's Python (it already has pyserial):

```
~/.platformio/penv/bin/python hardware/esp_sanity_test/sanity_test.py /dev/ttyUSB0
```

The first run compiles the sketch (about a minute); later runs only flash.
`/dev/ttyUSB` numbers change when a board is replugged, so the result names
the board by its MAC address, for example:

```
PASS ESP-1 (1c:c3:ab:ba:8a:50) on /dev/ttyUSB0: ESP32-D0WD-V3, revision v3.1, flash 4 MB, Wi-Fi after 2.3 s, IP 192.168.1.57, RSSI -48 dBm
```

Options: `--no-flash` only resets the board and checks its output (the sketch
is already on it); `--clients PATH` uses another board table.

## Files

- `src/main.cpp`: the test sketch; prints the report every 5 s
- `sanity_test.py`: flashes, reads the serial output, prints PASS/FAIL
- `platformio.ini`: build settings (espressif32 8.0.0, Arduino core 3.3)
- `include/secrets.example.h`: template for the git-ignored `secrets.h`
