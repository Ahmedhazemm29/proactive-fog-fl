"""
Laptop side of the ESP32 secure-aggregation benchmark (esp32/src/secagg_bench/).

    .venv/bin/python -I scripts/secagg_esp32_tools.py keys
    .venv/bin/python -I scripts/secagg_esp32_tools.py listen --seconds 3600
    .venv/bin/python -I scripts/secagg_esp32_tools.py check

  keys    makes new Paillier test keys (2048 and 3072 bits): the public keys go
          to esp32/src/secagg_bench/paillier_keys.h (flashed onto the board),
          the private keys to data/secagg_esp32/paillier_private.json, which
          git ignores. Only needed for a new key pair; rebuild the firmware after.
  listen  subscribes to bench/<board>/# on the Pi's broker and logs the real
          size of every message (payload and whole MQTT packet) to
          data/secagg_esp32/message_sizes.csv; each payload is saved in
          data/secagg_esp32/payloads/. It never publishes. Start it before
          flashing: the board publishes once, after all measurements.
  check   decrypts the board's Paillier messages with the private keys and
          checks they give the update the firmware encrypted.
"""
import argparse
import base64
import csv
import json
import os
import socket
import struct
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "secagg_esp32"
HEADER = ROOT / "esp32" / "src" / "secagg_bench" / "paillier_keys.h"

# The update the firmware encrypts (WEIGHTS and NUM_SAMPLES in main.cpp)
WEIGHTS, NUM_SAMPLES = [0.1234, -0.3456, 0.5678, -0.7891, 0.9012], 236
SCALE, OFFSET, SLOT = 2 ** 24, 2 ** 40, 64


# ----------------------------------------------------------------------
# keys
# ----------------------------------------------------------------------
def make_keys():
    from phe import paillier
    DATA.mkdir(parents=True, exist_ok=True)
    private = {}
    lines = ["// Paillier public keys (n, g = n + 1) for the ESP32 secure-aggregation",
             "// benchmark. Test keys only, made on the laptop with python-paillier 1.5.0;",
             "// the private keys stay on the laptop (to check the board's ciphertexts).",
             "#pragma once", ""]
    for bits in (2048, 3072):
        public_key, private_key = paillier.generate_paillier_keypair(n_length=bits)
        private[str(bits)] = {"n": str(public_key.n), "p": str(private_key.p),
                              "q": str(private_key.q)}
        lines.append(f'const char* PAILLIER_N_{bits} = "{public_key.n:x}";')
    (DATA / "paillier_private.json").write_text(json.dumps(private))
    HEADER.write_text("\n".join(lines) + "\n")
    print(f"wrote {HEADER} and {DATA / 'paillier_private.json'} (git-ignored)")


# ----------------------------------------------------------------------
# listen: a subscribe-only MQTT 3.1.1 client (standard library)
# ----------------------------------------------------------------------
def mqtt_string(text):
    data = text.encode()
    return struct.pack("!H", len(data)) + data


def packet(first_byte, body):
    length, n = b"", len(body)
    while True:
        digit, n = n % 128, n // 128
        length += bytes([digit | (0x80 if n else 0)])
        if not n:
            return bytes([first_byte]) + length + body


def recv_exact(sock, n):
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError("broker closed the connection")
        data += chunk
    return data


def read_packet(sock):
    """One packet: (first byte, body, size of the whole packet in bytes)."""
    first = recv_exact(sock, 1)[0]
    length, shift, header = 0, 0, 1
    while True:
        digit = recv_exact(sock, 1)[0]
        header += 1
        length += (digit & 0x7F) << shift
        shift += 7
        if not digit & 0x80:
            return first, recv_exact(sock, length), header + length


def listen(host, board, seconds):
    topic = f"bench/{board}/#"
    (DATA / "payloads").mkdir(parents=True, exist_ok=True)
    sock = socket.create_connection((host, 1883), timeout=10)
    sock.sendall(packet(0x10, mqtt_string("MQTT") + bytes([4, 0x02]) + struct.pack("!H", 60)
                        + mqtt_string(f"secagg-sizes-{os.getpid()}")))
    read_packet(sock)
    sock.sendall(packet(0x82, struct.pack("!H", 1) + mqtt_string(topic) + bytes([0])))
    sock.settimeout(1)
    out = DATA / "message_sizes.csv"
    new = not out.exists()
    with open(out, "a", newline="") as f:
        writer = csv.writer(f)
        if new:
            writer.writerow(["epoch", "kind", "topic", "payload_bytes", "mqtt_packet_bytes"])
        end, last_ping = time.time() + seconds, time.time()
        while time.time() < end:
            if time.time() - last_ping > 30:
                sock.sendall(bytes([0xC0, 0]))   # PINGREQ
                last_ping = time.time()
            try:
                first, body, size = read_packet(sock)
            except socket.timeout:
                continue
            if first >> 4 == 9:
                print(f"subscribed to {topic}", flush=True)
            elif first >> 4 == 3:                # PUBLISH
                kind = "retained" if first & 1 else "fresh"
                topic_len = struct.unpack("!H", body[:2])[0]
                name = body[2:2 + topic_len].decode()
                payload = body[2 + topic_len + (2 if (first >> 1) & 3 else 0):]
                writer.writerow([f"{time.time():.3f}", kind, name, len(payload), size])
                f.flush()
                (DATA / "payloads" / name.split("/")[-1]).write_bytes(payload)
                print(f"{name}: payload {len(payload)} B, packet {size} B, {kind}", flush=True)
    sock.sendall(bytes([0xE0, 0]))   # DISCONNECT
    sock.close()


# ----------------------------------------------------------------------
# check
# ----------------------------------------------------------------------
def check():
    from phe import paillier
    keys = json.loads((DATA / "paillier_private.json").read_text())
    expected = [round(w * NUM_SAMPLES * SCALE) for w in WEIGHTS] + [round(NUM_SAMPLES * SCALE)]
    files = sorted((DATA / "payloads").glob("paillier*"))
    if not files:
        print("no Paillier messages in", DATA / "payloads")
    for path in files:
        message = json.loads(path.read_text())
        k = keys[str(message["key_bits"])]
        n = int(k["n"])
        private_key = paillier.PaillierPrivateKey(paillier.PaillierPublicKey(n), int(k["p"]), int(k["q"]))
        texts = message["c"] if isinstance(message["c"], list) else [message["c"]]
        plain = [private_key.raw_decrypt(int.from_bytes(base64.b64decode(t), "big")) for t in texts]
        if len(plain) == 1:   # packed: 6 slots of 64 bits, each shifted by OFFSET
            got = [((plain[0] >> (SLOT * i)) & (2 ** SLOT - 1)) - OFFSET for i in range(6)]
        else:                 # negative values were encrypted as n - |v|
            got = [v - n if v > n // 2 else v for v in plain]
        verdict = "decrypts to the update" if got == expected else f"WRONG: {got}"
        print(f"{path.name:32} {len(texts)} ciphertext(s): {verdict}")


def main():
    parser = argparse.ArgumentParser(description="Laptop side of the ESP32 secagg benchmark.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("keys", help="make new Paillier test keys")
    p = sub.add_parser("listen", help="log the size of every benchmark message")
    p.add_argument("--host", default="fognode1.local")
    p.add_argument("--board", default="esp32-4470", help="FL ID of the benchmark board")
    p.add_argument("--seconds", type=float, default=3600)
    sub.add_parser("check", help="decrypt and check the Paillier messages")
    args = parser.parse_args()
    if args.command == "keys":
        make_keys()
    elif args.command == "listen":
        listen(args.host, args.board, args.seconds)
    else:
        check()


if __name__ == "__main__":
    main()
