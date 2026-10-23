# ESP32 edge clients

ESP-1 to ESP-7 are ESP32-D0WD-V3, revision v3.1. The MAC addresses of ESP-1
to ESP-8 were read with `esptool read_mac` on 2026-10-23.

ESP-8 (WROOM, USB-C) has a different chip: ESP32-D0WDQ6, revision v1.1.

The `/dev/ttyUSB` number of a board changes when it is unplugged and plugged
back in, so boards are identified by their MAC address only.

| Board | MAC |
|---|---|
| ESP-1 | 1c:c3:ab:ba:8a:50 |
| ESP-2 | 1c:c3:ab:f9:28:bc |
| ESP-3 | 1c:c3:ab:f8:fe:a8 |
| ESP-4 | 1c:c3:ab:f8:f2:94 |
| ESP-5 | f4:2d:c9:8a:44:70 |
| ESP-6 | 1c:c3:ab:fa:46:34 |
| ESP-7 | 1c:c3:ab:f9:17:74 |
| ESP-8 | f8:b3:b7:7a:1c:74 |
