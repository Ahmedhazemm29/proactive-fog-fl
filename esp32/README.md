# esp32

The edge clients: ESP32-WROOM-32 boards (PlatformIO, board `esp32dev`, Arduino framework). They find the broker on the Pi as `fognode1.local` (mDNS) and reconnect by themselves. Three firmwares share this folder:

- `src/fl/main.cpp` (env `fl`, the default): federated learning client.
  - **ID:** taken from the chip's MAC, `esp32-<last 4 hex>`. It is the MQTT client ID, the mDNS name and part of the topics, so every board gets the same firmware.
  - **Local data:** a sine wave with noise. Its amplitude, period, phase, offset, noise and length (150 to 300 points) come from the MAC, so the clients differ. The data never leaves the board.
  - **Model:** linear regression that predicts the next value from the last 4 (4 weights and a bias), trained with SGD on the board (5 epochs per round, learning rate 0.01).
  - **Modes:** *active* boards train in every round; *standby* boards stay connected but out of the rounds. Every board starts in standby after a reboot, always. `join` and `leave` from `hardware/tools/fl_control.py` switch the mode: a join takes effect from the next round, a leave at once. A reconnect (e.g. after a Wi-Fi drop) keeps the mode.
  - **Secure aggregation:** `protect_update()` is the marked hook where it will go; for now it passes the weights through.
- `src/sensor/main.cpp` (env `sensor`): publishes fake sensor values on `fog/client<ID>/data` at a rate set live on `fog/client<ID>/control`. It feeds the Pi's MQTT worker (`workload/mqtt_worker.py`).
- `src/secagg_bench/` (env `secagg_bench`): not an FL client. A one-off benchmark for one test board: it times the client side of pairwise masking and Paillier, records the free heap and publishes the messages once on `bench/<id>/...` so their size can be measured. Results and how to run it: `results/secagg_benchmark/report.md`.
- `lib/fognet/`: Wi-Fi, the mDNS lookup of the broker and MQTT with a Last Will, all reconnecting by themselves. Used by the FL client.
- `include/secrets.example.h`: copy it to `include/secrets.h` and fill in the Wi-Fi. `secrets.h` is git-ignored.

## FL protocol (MQTT, JSON)

| Topic | From | Message |
|---|---|---|
| `fog/<id>/status` | client | `online-standby` or `online-active` after every connect and every command, retained. The broker publishes `offline` (retained, the Last Will) when a client disappears. (The firmware before join/leave sent plain `online`.) |
| `fog/<id>/control` | `fl_control.py` | `join` or `leave`, never retained |
| `fog/global/model` | aggregator | `{"run", "round", "rounds", "weights": [b, w1, w2, w3, w4]}`, retained, so a late client gets it too |
| `fog/<id>/update` | client | `{"run", "round", "weights", "num_samples", "loss", "loss_before"}` after local training (active boards only) |

`loss_before` is the mean squared error of the global model on the client's data, `loss` the same after local training. The aggregator is `pi/aggregator/aggregator.py`.

A command must never be stored (retained) on the broker, or a rebooted board would get it again and rejoin by itself. PubSubClient can't tell a stored message from a new one, so on every connect the board first deletes any stored command on its control topic (an empty retained message) and only then subscribes to it.

## Build and flash

```bash
cd esp32
cp include/secrets.example.h include/secrets.h        # then fill in WIFI_SSID and WIFI_PASSWORD
pio run -t upload --upload-port /dev/ttyUSB0          # FL client; repeat for every board's port
pio device monitor --port /dev/ttyUSB0                # serial log, 115200 baud
pio run -e sensor -t upload                           # the sensor firmware instead (client 1)
PLATFORMIO_BUILD_FLAGS="-DCLIENT_ID=2" pio run -e sensor -t upload   # sensor firmware, client 2
```

A board that prints `E BOD: Brownout detector was triggered` right after Wi-Fi starts is not getting enough current (hub port, cable or board). It restarts in a loop.
