# Secure aggregation: cost per FL round, measured (decision support)

How much would secure aggregation cost per round compared with the plain FedAvg
the aggregator runs now? Compared:
- **plain FedAvg**;
- **pairwise masking** (SecAgg, Bonawitz et al. 2017), fresh keys every round,
  with and without dropouts;
- **Paillier** homomorphic encryption with 2048 and 3072-bit keys.

The model is ours: 5 weights plus `num_samples` per update.

**Every number here is measured** on the real hardware:
- **Aggregator:** on the Raspberry Pi 5 (fognode1).
- **Client:** on one ESP32 (ESP-5) with Wi-Fi and MQTT connected.
- **Message sizes:** from the real MQTT messages.

All measurements are from 2026-10-24. Nothing is integrated into the FL firmware or the aggregator, and ESP-5 runs the FL firmware again. This is input for a decision, not the decision.

## Results

| Method | Pi 5 aggregator, 7 clients | Pi 5 aggregator, 50 clients | ESP32 client, per round | ESP32 lowest free heap | Upload per client per round |
|---|---|---|---|---|---|
| FedAvg (no protection) | 0.007 ms | 0.035 ms | (no extra work) | – | 144 B |
| Masking, no dropout | 0.14 ms | 2.0 ms | 1.9–2.2 s (7 clients), 14.5–16.7 s (50) | 102 KB (7), 76 KB (50) | 2,494 B (7), 16,941 B (50) |
| Masking, 10% dropout | 1.3 ms | 42.5 ms | the same | the same | 2,493 B (7), 16,940 B (50) |
| Paillier 2048, 6 ciphertexts | 64.8 ms | 70.9 ms | 2.25 s | 67 KB | 4,172 B |
| Paillier 2048, packed | 11.0 ms | 13.7 ms | 0.37 s | 63 KB | 735 B |
| Paillier 3072, 6 ciphertexts | 161.6 ms | 172.5 ms | **fails with mbedTLS**; 1,392 s (23 min) in plain software | 48 KB | 6,212 B |
| Paillier 3072, packed | 27.5 ms | 33.1 ms | **fails with mbedTLS**; 232 s (3.9 min) in plain software | 46 KB | 1,075 B |

How to read the table:
- **Packed:** all 6 values of an update in one ciphertext (64 bits each), so
  the client encrypts once and the aggregator decrypts once.
- **Pi 5:** CPU time of everything the aggregator computes in one round, the
  median of 7 repetitions.
- **ESP32 time:** wall time of one client's work in one round, at 240 MHz.
  - Two full runs. Where they differ the table shows both: masking was 13–15%
    faster in the second run; the Paillier times differed by under 0.5%.
  - The 2048-bit Paillier times use mbedTLS, which runs on the ESP32's
    big-number hardware.
- **ESP32 heap:** the lowest free heap during the step, out of 276 KB in total.
  The heap was 109.8 KB at the start, with Wi-Fi, MQTT and a 16 KB MQTT buffer.
  It went down over the run because the board kept every message in RAM to
  publish at the end, so these are worst cases.
- **Upload:** the JSON payloads one client publishes in one round, binary data
  in base64. The MQTT packets add 35–52 bytes each, mostly the topic name.
  Downloads were not measured: the other clients' keys and shares that each
  client receives through the broker.

![Aggregator CPU time per round on the Pi 5, measured](server_cost.png)

At one round per second, 10 ms of CPU per round is 1% of one Pi 5 core.

## Would it put meaningful load on the Pi 5?

No, for all three methods.
- The most expensive case is Paillier 3072 with 6 ciphertexts and 50 clients:
  173 ms per round, 17% of one core at one round per second.
- Packed Paillier stays under 34 ms.
- Masking stays under 2 ms without dropouts and reaches 42.5 ms at 50 clients
  with 10% dropout: the aggregator then redoes the dropped clients' masks.
- The aggregator container's 1.0 CPU limit is not at risk.

## What it costs on the ESP32

The cost lands on the boards.

- **Masking:** about 2 s per round with 7 clients and 14.5–16.7 s with 50.
  - The time is mostly X25519. One key agreement plus SHA-256 takes 131–153 ms
    with mbedTLS, and one key pair 128–151 ms. A client does 2 + 2(n−1) of these
    per round with fresh keys.
  - With 50 clients the round takes longer than the aggregator's current round
    timeout (`ROUND_TIMEOUT_S`, 10 s).
  - RAM is not a problem: the steps took at most 5.8 KB beyond what was allocated
    before them.
  - The 50-client shares message alone is 11.4 KB, far above the FL firmware's
    current 512-byte MQTT buffer.
- **Paillier 2048:** works with the ESP32's big-number hardware: 0.37 s packed,
  2.25 s for 6 ciphertexts. A step took at most 10.3 KB of heap.
- **Paillier 3072:** **not possible with the ESP32's mbedTLS.**
  - `mbedtls_mpi_exp_mod` returns `-14` (`MBEDTLS_ERR_MPI_NOT_ACCEPTABLE`): the
    modulus n² has 6144 bits, more than the 4096 bits the big-number hardware
    accepts.
  - The Arduino core's ESP-IDF build has the software fallback for such numbers
    turned off (`CONFIG_MBEDTLS_LARGE_KEY_SOFTWARE_MPI` is not set).
  - My own plain-C Montgomery code (`esp32/src/secagg_bench/montgomery.h`)
    works and fits in RAM (at most 13.5 KB for a step), but needs 232 s per
    round packed. It is a simple implementation, not an optimized library; the
    same code takes 69 s for a packed 2048-bit encryption, against 0.37 s with
    the hardware.
- Every ciphertext the board made was decrypted on the laptop and gave the
  exact update. The masking shares were decrypted and authenticated on the
  board, and both sides of an X25519 agreement got the same key.

## Points for the decision

- **What each method protects.**
  - *Masking:* the aggregator learns only the sum, as long as fewer than t
    clients (here a majority) collude with it. It survives dropouts. But each
    round takes 4 message rounds instead of 1, and every client exchanges
    messages with every other client (through the broker).
  - *Paillier:* whoever holds the private key can decrypt every single update.
    If the Pi aggregator holds the key, it protects nothing against the Pi. It
    needs a separate key holder that only ever decrypts the sum (for example
    the laptop), or threshold Paillier (much more complex).
  - *Neither* stops a client from sending a bad update.
- **Measured cost on the client:**
  - Packed Paillier 2048 is the cheapest secure option: 0.37 s and 735 bytes
    per round.
  - Masking with fresh keys costs about 2 s with our 7 clients and grows with
    the number of clients.
  - Paillier 3072 needs a software big-number library on the ESP32 first.
- **Not measured, so open:**
  - Masking with pairwise keys agreed once per run (as in later SecAgg
    versions), which would remove most X25519 work per round.
  - An optimized software path for 3072-bit keys.
  - Downloads and the time messages spend on the network.

## Method

**Pi 5 (aggregator):**
- `scripts/secagg_benchmark.py`, unchanged, run on fognode1: Raspberry Pi 5,
  4 GB, Python 3.13.5, pinned to core 3 (`taskset -c 3`).
- Governor ondemand, 2.4 GHz during the run, no throttling
  (`vcgencmd get_throttled` = 0x0), 44–49 °C.
- The `fl-worker-1` container was idle the whole time (0.1% CPU), and the FL
  aggregator was not running.
- Every method's result is checked against plain FedAvg (fixed point with
  2^-24 resolution).
- `pi5/timings.csv` holds every number. Its `masking client` rows are operation
  counts times per-operation times on the Pi; they are not used here. The
  client cost comes from the ESP32.

**ESP32 (client):**
- Board: ESP-5 (MAC f4:2d:c9:8a:44:70, ESP32-D0WD-V3 rev v3.1), 240 MHz.
- Firmware: `esp32/src/secagg_bench/` (PlatformIO env `secagg_bench`), Arduino
  core 3.3.12 with ESP-IDF 5.5.5 and its mbedTLS.
- What runs:
  - The same client steps as `MaskingClient` in the Python benchmark: X25519,
    SHA-256, AES-256-GCM, AES-256-CTR masks, and Shamir shares in the field
    2^521 − 1. This client is index 0, and the other clients' public keys are
    made beforehand, untimed.
  - Paillier: c = (1 + n·m) · rⁿ mod n². The 6-ciphertext case encrypts each
    fixed-point value (negative ones as n − |v|); the packed case puts 6 slots
    of 64 bits into one plaintext.
- Measuring:
  - Times with `esp_timer_get_time`.
  - Heap with `heap_caps_get_free_size` before and after each step, and the
    lowest free heap during it with `heap_caps_monitor_local_minimum_free_size_*`.
  - Every step ran once per run; there were two full runs.
- The test Paillier keys were made on the laptop: the board has the public keys
  (`paillier_keys.h`), and the private keys stay in the git-ignored `data/`.
- Raw output: `esp32/run1_serial_part1.log` and `run1_serial_part2.log` (run 1,
  read in two parts; the board repeats all results at the end) and
  `esp32/run2_serial.log`.
- Run 1 published nothing: a bug in the publishing step (fixed) gave up on the
  messages while MQTT was reconnecting after the long computation. Run 2
  published all of them.

**Message sizes:**
- The board published each message once (not retained) on
  `bench/esp32-4470/<name>` on the Pi's broker.
- A subscribe-only client on the laptop logged the payload and the whole
  packet: `esp32/message_sizes.csv`, from run 2.

## Installed

- **Laptop:** a venv inside this worktree, `.venv/` (git-ignored), with
  `scripts/requirements-secagg.txt`: phe 1.5.0, gmpy2 2.3.2 (GMP 6.3.0),
  cryptography 50.0.2, matplotlib 3.10.9.
  - Dependencies: cffi 2.1.1, pycparser 3.11, typing_extensions 4.16.0, numpy
    2.2.6, contourpy 1.3.2, cycler 0.12.1, fonttools 4.65.0, kiwisolver 1.5.1,
    packaging 26.3, pillow 12.3.0, pyparsing 3.3.3, python-dateutil 3.0.0,
    six 1.17.0, tzdata 2026.5.
  - It runs in isolated mode (`python -I`), which keeps the laptop's ROS 2
    `PYTHONPATH` out.
- **Pi:** `~/secagg-bench/` (the benchmark script and a venv), Python 3.13.5:
  phe 1.5.0, gmpy2 2.3.2 (GMP 6.3.0), cryptography 50.0.2, with cffi 2.1.1 and
  pycparser 3.12; pip 25.1.1. Remove it with `rm -rf ~/secagg-bench`.
- **ESP32:** nothing beyond the Arduino core and the libraries of the FL
  firmware (PubSubClient 2.8, ArduinoJson 7).

## Reproduce

Pi 5 (aggregator):
```bash
ssh pi5@fognode1.local 'mkdir -p ~/secagg-bench/scripts && cd ~/secagg-bench && python3 -m venv .venv && .venv/bin/pip install phe==1.5.0 gmpy2==2.3.2 cryptography==50.0.2'
scp scripts/secagg_benchmark.py pi5@fognode1.local:secagg-bench/scripts/
ssh pi5@fognode1.local 'cd ~/secagg-bench && taskset -c 3 .venv/bin/python -I scripts/secagg_benchmark.py'   # about 90 s
scp pi5@fognode1.local:secagg-bench/results/secagg_benchmark/timings.csv results/secagg_benchmark/pi5/
.venv/bin/python -I scripts/plot_secagg_benchmark.py       # writes server_cost.png
```

ESP32 (client):
- One test board, identified by its MAC, with `esp32/include/secrets.h` in
  place. It takes about 45 minutes, mostly the software 3072-bit case.
- Afterwards, flash the FL firmware back with `hardware/tools/fl_flash_one.py`.

```bash
.venv/bin/python -I scripts/secagg_esp32_tools.py keys     # only for new keys
.venv/bin/python -I scripts/secagg_esp32_tools.py listen --seconds 3600 &
cd esp32 && ~/.platformio/penv/bin/pio run -e secagg_bench -t upload --upload-port /dev/ttyUSB0
~/.platformio/penv/bin/pio device monitor -p /dev/ttyUSB0   # RESULT and MESSAGE lines
cd .. && .venv/bin/python -I scripts/secagg_esp32_tools.py check
```

`timings.csv` in this folder holds the first runs, made on the laptop (Intel
i7-13620H). The report no longer uses them.

## Sources

- K. Bonawitz et al., "Practical Secure Aggregation for Privacy-Preserving
  Machine Learning", ACM CCS 2017.
- Ç. K. Koç, T. Acar, B. S. Kaliski, "Analyzing and Comparing Montgomery
  Multiplication Algorithms", IEEE Micro 16(3), 1996 (the CIOS method in
  `montgomery.h`).
