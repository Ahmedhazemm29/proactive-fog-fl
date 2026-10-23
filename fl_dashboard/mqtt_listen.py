"""
Read-only MQTT 3.1.1 client for the dashboard, Python standard library only.

It sends only CONNECT, SUBSCRIBE, PINGREQ and DISCONNECT, never a PUBLISH, so it
can't change anything on the broker. It subscribes with QoS 0 (nothing to
acknowledge) and a clean session (the broker keeps nothing for us). The client
ID "fl-dashboard-<pid>" can't clash with the aggregator ("fl-aggregator") or a
board ("esp32-..."): the broker drops a client when another one connects
with the same ID.

The packet helpers are the same as in hardware/tools/mqtt_watch.py. After a
lost connection the listener tries again every RETRY_S seconds.
"""
import os
import select
import socket
import struct
import sys
import threading
import time

KEEPALIVE_S = 30   # we ping every KEEPALIVE_S / 2 seconds; silence for longer = connection lost
RETRY_S = 3        # wait before connecting again


# ----------------------------------------------------------------------
# MQTT packets
# ----------------------------------------------------------------------
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
            raise ConnectionError("the broker closed the connection")
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


# ----------------------------------------------------------------------
# The listener
# ----------------------------------------------------------------------
class Listener(threading.Thread):
    """
    Connects, subscribes to `topics` and calls
        on_message(topic, payload, retained, now)  for every message, and
        on_connection(connected, now, error)       when the connection comes or goes.
    """

    def __init__(self, host, port, topics, on_message, on_connection):
        super().__init__(daemon=True)       # ends with the program
        self.host, self.port, self.topics = host, port, topics
        self.on_message, self.on_connection = on_message, on_connection
        self.stopping = threading.Event()

    def stop(self):
        self.stopping.set()

    def run(self):
        while not self.stopping.is_set():
            try:
                self.session()
            except Exception as error:      # network trouble, or a bad packet: try again
                reason = str(error) or type(error).__name__
                if not isinstance(error, (OSError, ConnectionError)):
                    print(f"mqtt: unexpected {type(error).__name__}: {error}", file=sys.stderr)
                self.on_connection(False, time.time(), reason)
            self.stopping.wait(RETRY_S)

    def session(self):
        """One connection: connect, subscribe, then read messages until it breaks or we stop."""
        with socket.create_connection((self.host, self.port), timeout=10) as sock:
            # CONNECT: protocol "MQTT" level 4 (3.1.1), clean session, no will, no login
            client_id = f"fl-dashboard-{os.getpid()}"
            sock.sendall(packet(0x10, mqtt_string("MQTT") + bytes([4, 0x02])
                                + struct.pack("!H", KEEPALIVE_S) + mqtt_string(client_id)))
            first, body = read_packet(sock)
            if first >> 4 != 2 or len(body) < 2 or body[1] != 0:
                code = body[1] if len(body) > 1 else "?"
                raise ConnectionError(f"the broker refused the connection (code {code})")

            # SUBSCRIBE (packet id 1): every topic with QoS 0
            filters = b"".join(mqtt_string(topic) + bytes([0]) for topic in self.topics)
            sock.sendall(packet(0x82, struct.pack("!H", 1) + filters))

            last_ping = last_heard = time.time()
            while not self.stopping.is_set():
                now = time.time()
                if now - last_ping >= KEEPALIVE_S / 2:
                    sock.sendall(bytes([0xC0, 0]))      # PINGREQ: the broker answers PINGRESP
                    last_ping = now
                if now - last_heard > KEEPALIVE_S:
                    raise ConnectionError("no answer from the broker")
                ready, _, _ = select.select([sock], [], [], 0.5)
                if not ready:
                    continue
                first, body = read_packet(sock)
                last_heard = time.time()
                kind = first >> 4
                if kind == 9:                           # SUBACK: one code per topic, 0x80 = refused
                    if 0x80 in body[2:]:
                        raise ConnectionError("the broker refused a subscription")
                    self.on_connection(True, last_heard, None)
                elif kind == 3:                         # PUBLISH from the broker
                    retained = bool(first & 0x01)       # set only for stored messages
                    qos = (first >> 1) & 0x03
                    topic_len = struct.unpack("!H", body[:2])[0]
                    topic = body[2:2 + topic_len].decode("utf-8", errors="replace")
                    start = 2 + topic_len + (2 if qos else 0)   # QoS > 0 adds a packet id
                    self.on_message(topic, body[start:], retained, last_heard)
                # PINGRESP needs nothing more: last_heard is updated
            sock.sendall(bytes([0xE0, 0]))              # DISCONNECT: we stop
