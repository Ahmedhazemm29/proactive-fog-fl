"""Read-only MQTT 3.1.1 subscriber, Python standard library only.

It never publishes anything. Useful on a machine without mosquitto_sub or
paho-mqtt installed.

    python3 hardware/tools/mqtt_watch.py fognode1.local 'fog/+/status' --seconds 5

Prints one line per message:  <epoch time> <retained|fresh> <topic> <payload>
  retained = stored message the broker sends right after we subscribe
  fresh    = message sent live while we are subscribed
Prints "subscribed <epoch time>" once the subscription is active.
"""

import argparse
import os
import select
import socket
import struct
import sys
import time

KEEPALIVE_S = 60  # we send a ping at least this often, or the broker drops us


# ---- MQTT packet helpers ----

def mqtt_string(text):
    """MQTT string: 2-byte length, then the UTF-8 bytes."""
    data = text.encode()
    return struct.pack("!H", len(data)) + data


def packet(first_byte, body):
    """Fixed header (packet type/flags + remaining length) and the body."""
    length, n = b"", len(body)
    while True:
        digit, n = n % 128, n // 128
        length += bytes([digit | (0x80 if n else 0)])
        if not n:
            return bytes([first_byte]) + length + body


def recv_exact(sock, n):
    """Read exactly n bytes from the socket."""
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError("broker closed the connection")
        data += chunk
    return data


def read_packet(sock):
    """Read one packet: returns (first byte, body)."""
    first = recv_exact(sock, 1)[0]
    length, shift = 0, 0
    while True:
        digit = recv_exact(sock, 1)[0]
        length += (digit & 0x7F) << shift
        shift += 7
        if not digit & 0x80:
            break
    return first, recv_exact(sock, length)


# ---- Main ----

def main():
    parser = argparse.ArgumentParser(description="Print MQTT messages (read-only).")
    parser.add_argument("host", help="broker host name, e.g. fognode1.local")
    parser.add_argument("topic", help="topic filter, e.g. 'fog/+/status'")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--seconds", type=float, default=10, help="how long to listen")
    args = parser.parse_args()

    sock = socket.create_connection((args.host, args.port), timeout=10)

    # CONNECT: protocol "MQTT" level 4 (3.1.1), clean session, no will, no login
    client_id = f"mqtt-watch-{os.getpid()}"
    sock.sendall(packet(0x10, mqtt_string("MQTT") + bytes([4, 0x02])
                        + struct.pack("!H", KEEPALIVE_S) + mqtt_string(client_id)))
    first, body = read_packet(sock)
    if first >> 4 != 2 or body[1] != 0:
        sys.exit(f"CONNECT refused (return code {body[1] if len(body) > 1 else '?'})")

    # SUBSCRIBE (packet id 1) with QoS 0
    sock.sendall(packet(0x82, struct.pack("!H", 1) + mqtt_string(args.topic) + bytes([0])))

    end = time.time() + args.seconds
    last_ping = time.time()
    while time.time() < end:
        if time.time() - last_ping > KEEPALIVE_S / 2:
            sock.sendall(bytes([0xC0, 0]))  # PINGREQ
            last_ping = time.time()
        ready, _, _ = select.select([sock], [], [], 0.5)
        if not ready:
            continue
        first, body = read_packet(sock)
        kind = first >> 4
        if kind == 9:  # SUBACK
            print(f"subscribed {time.time():.3f}", flush=True)
        elif kind == 3:  # PUBLISH
            retained = first & 0x01  # set only for stored messages sent on subscribe
            qos = (first >> 1) & 0x03
            topic_len = struct.unpack("!H", body[:2])[0]
            topic = body[2:2 + topic_len].decode(errors="replace")
            start = 2 + topic_len + (2 if qos else 0)  # QoS > 0 adds a packet id
            payload = body[start:].decode(errors="replace")
            print(f"{time.time():.3f} {'retained' if retained else 'fresh'} {topic} {payload}",
                  flush=True)

    sock.sendall(bytes([0xE0, 0]))  # DISCONNECT
    sock.close()


if __name__ == "__main__":
    main()
