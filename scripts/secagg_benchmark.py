"""
Decision support, laptop only: the aggregation CPU cost per FL round of
  (a) plain FedAvg, as in pi/aggregator/aggregator.py,
  (b) pairwise-masking secure aggregation (Bonawitz et al., CCS 2017), and
  (c) Paillier homomorphic encryption (python-paillier with gmpy2), 2048 and
      3072-bit keys, one ciphertext per value or all values packed into one,
for 4, 7, 10, 20 and 50 clients with our 5-weight model. Nothing here touches
the Pi or the ESP32s, and nothing goes into the firmware or the aggregator.

Run it in this worktree's venv (scripts/requirements-secagg.txt), isolated from
other Python paths and on one performance core:

    taskset -c 0 .venv/bin/python -I scripts/secagg_benchmark.py

Writes results/secagg_benchmark/timings.csv and server_cost.png; the report is
results/secagg_benchmark/report.md.

Each client sends 6 values per round: its 5 weights times its num_samples, and
num_samples (the aggregator needs the sum of both for the weighted average).
Times are CPU time of this process, the median of several repetitions:
  server  all the aggregator computes for one round. FedAvg: the weighted
          average. Masking: the sum of the masked inputs and the unmasking
          (rebuilding the self-mask seeds of the survivors and the keys of the
          dropped clients from Shamir shares, and recomputing the dropped
          clients' pairwise masks), with no dropout and with 10% dropout.
          Paillier: the homomorphic sum and the decryption. Relaying messages
          (no computing) is not timed; the report lists the message sizes.
  client  what one client computes for one round: masking with fresh keys every
          round (2 key pairs, 2 key agreements per other client, Shamir shares
          of 2 secrets, encrypting and decrypting the shares, the masks),
          counted in operations and timed per operation; Paillier: encrypting
          its values.
Every method's result is checked against plain FedAvg.
"""
import csv
import hashlib
import random
import secrets
import statistics
import time
from functools import reduce
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from phe import paillier

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "secagg_benchmark"

CLIENT_COUNTS = [4, 7, 10, 20, 50]
KEY_BITS = [2048, 3072]
NUM_WEIGHTS = 5
VALUES = NUM_WEIGHTS + 1        # the 5 weighted weights and num_samples
DROPOUT = 0.1                   # share of clients that drop after sending their shares (at least 1)
REPEAT = 7                      # repetitions of each server timing (the median is kept)

SCALE = 2 ** 24                 # fixed point for masking and packed Paillier
MOD = 2 ** 64                   # masked values are mod 2^64
PRIME = 2 ** 521 - 1            # field for Shamir's secret sharing (bigger than a 32-byte secret)
SLOT = 64                       # packed Paillier: bits per value
OFFSET = 2 ** 40                # packed Paillier: makes every value positive


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def cpu_time(fn, repeat=REPEAT, inner=1):
    """Median CPU time in seconds of one call of fn, over repeat x inner calls."""
    times = []
    for _ in range(repeat):
        start = time.process_time()
        for _ in range(inner):
            fn()
        times.append((time.process_time() - start) / inner)
    return statistics.median(times)


def make_updates(n, rng):
    """n clients' updates: 5 weights and num_samples (146 to 296, like the ESP32s)."""
    return [{"weights": [rng.uniform(-1.5, 1.5) for _ in range(NUM_WEIGHTS)],
             "num_samples": rng.randint(146, 296)} for _ in range(n)]


def fedavg(updates):
    """The same as fedavg() in pi/aggregator/aggregator.py."""
    total = sum(u["num_samples"] for u in updates)
    return [sum(u["weights"][i] * u["num_samples"] for u in updates) / total
            for i in range(NUM_WEIGHTS)]


def check(result, updates, what):
    """The secure result must equal plain FedAvg (up to the fixed-point rounding)."""
    expected = fedavg(updates)
    assert all(abs(a - b) < 1e-5 for a, b in zip(result, expected)), (what, result, expected)


# ----------------------------------------------------------------------
# (b) Pairwise masking (Bonawitz et al. 2017), fresh keys every round
# ----------------------------------------------------------------------
def prg(seed):
    """VALUES numbers mod 2^64 from a 32-byte seed: AES-256 in counter mode."""
    data = Cipher(algorithms.AES(seed), modes.CTR(bytes(16))).encryptor().update(bytes(8 * VALUES))
    return [int.from_bytes(data[8 * i:8 * i + 8], "little") for i in range(VALUES)]


def kdf(shared_secret):
    return hashlib.sha256(shared_secret).digest()


def shamir_share(secret, n, t):
    """n shares (x, y) of an integer; any t of them rebuild it."""
    coeffs = [secret] + [secrets.randbelow(PRIME) for _ in range(t - 1)]
    shares = []
    for x in range(1, n + 1):
        y = 0
        for c in reversed(coeffs):          # Horner
            y = (y * x + c) % PRIME
        shares.append((x, y))
    return shares


def lagrange_at_zero(xs):
    """The Lagrange coefficients for rebuilding at x = 0 from shares at the points xs."""
    coefficients = []
    for j, xj in enumerate(xs):
        num = den = 1
        for m, xm in enumerate(xs):
            if m != j:
                num = num * -xm % PRIME
                den = den * (xj - xm) % PRIME
        coefficients.append(num * pow(den, -1, PRIME) % PRIME)
    return coefficients


def shamir_rebuild(shares, coefficients):
    """The secret from t shares (x, y), with the coefficients of their points."""
    return sum(y * c for (_, y), c in zip(shares, coefficients)) % PRIME


def to_fixed(update):
    w, n = update["weights"], update["num_samples"]
    return [round(x * n * SCALE) % MOD for x in w] + [n % MOD]


def from_fixed(total):
    signed = [v - MOD if v >= MOD // 2 else v for v in total]
    samples = signed[NUM_WEIGHTS]
    return [v / SCALE / samples for v in signed[:NUM_WEIGHTS]]


class MaskingClient:
    """One client's side of one SecAgg round."""

    def __init__(self, index, update):
        self.index, self.x = index, to_fixed(update)

    def advertise(self):
        """Round 0: two fresh key pairs (c: encrypting shares, s: masks)."""
        self.c_sk, self.s_sk = X25519PrivateKey.generate(), X25519PrivateKey.generate()
        return self.c_sk.public_key(), self.s_sk.public_key()

    def share_keys(self, public_keys, t):
        """Round 1: Shamir-share the mask key s_sk and the self-mask seed b; encrypt each peer's shares."""
        self.public_keys, n = public_keys, len(public_keys)
        self.b = secrets.token_bytes(32)
        b_shares = shamir_share(int.from_bytes(self.b, "big"), n, t)
        s_shares = shamir_share(int.from_bytes(self.s_sk.private_bytes_raw(), "big"), n, t)
        self.keys, out = {}, {}
        for v, (c_pk, _) in enumerate(public_keys):
            if v == self.index:
                self.own = (b_shares[v], s_shares[v])
                continue
            self.keys[v] = kdf(self.c_sk.exchange(c_pk))
            nonce = secrets.token_bytes(12)
            payload = b_shares[v][1].to_bytes(66, "big") + s_shares[v][1].to_bytes(66, "big")
            out[v] = nonce + AESGCM(self.keys[v]).encrypt(nonce, payload, None)
        return out

    def masked_input(self, received):
        """Round 2: decrypt the shares from the others, then send x + self mask +- pairwise masks."""
        self.held = {}
        for v, blob in received.items():
            plain = AESGCM(self.keys[v]).decrypt(blob[:12], blob[12:], None)
            self.held[v] = (int.from_bytes(plain[:66], "big"), int.from_bytes(plain[66:], "big"))
        y = [(a + b) % MOD for a, b in zip(self.x, prg(self.b))]
        for v, (_, s_pk) in enumerate(self.public_keys):
            if v != self.index:
                mask = prg(kdf(self.s_sk.exchange(s_pk)))
                sign = 1 if self.index < v else -1
                y = [(a + sign * m) % MOD for a, m in zip(y, mask)]
        return y

    def unmask_shares(self, survivors, dropped):
        """Round 3: for each survivor its share of b, for each dropped client its share of s_sk."""
        own_b, own_s = self.own
        shares = {}
        for v in survivors:
            shares[("b", v)] = own_b if v == self.index else (self.index + 1, self.held[v][0])
        for v in dropped:
            shares[("s", v)] = (self.index + 1, self.held[v][1])
        return shares


def masking_round(updates, dropout):
    """Rounds 0 to 3 for all clients (not timed). Returns what the server gets."""
    n = len(updates)
    t = n // 2 + 1                                  # threshold: a majority
    clients = [MaskingClient(i, u) for i, u in enumerate(updates)]
    public_keys = [c.advertise() for c in clients]
    outboxes = [c.share_keys(public_keys, t) for c in clients]
    dropped = set(range(n - max(1, round(dropout * n)), n)) if dropout else set()
    survivors = [i for i in range(n) if i not in dropped]
    inputs = {}
    for u in survivors:                             # the dropped ones never send their input
        received = {v: outboxes[v][u] for v in range(n) if v != u}
        inputs[u] = clients[u].masked_input(received)
    shares = [clients[u].unmask_shares(survivors, dropped) for u in survivors]
    return {"t": t, "public_keys": public_keys, "inputs": inputs, "survivors": survivors,
            "dropped": sorted(dropped), "shares": shares}


def masking_server(r):
    """The server's work: sum the masked inputs, remove the self masks and the dropped clients' masks."""
    t = r["t"]
    total = [0] * VALUES
    for y in r["inputs"].values():
        total = [(a + b) % MOD for a, b in zip(total, y)]
    # Every secret is rebuilt from the shares of the same t survivors, so the
    # Lagrange coefficients of their points are computed once per round
    first = r["shares"][:t]
    points = [s[("b", r["survivors"][0])][0] for s in first]
    coefficients = lagrange_at_zero(points)
    for u in r["survivors"]:
        seed = shamir_rebuild([s[("b", u)] for s in first], coefficients)
        total = [(a - m) % MOD for a, m in zip(total, prg(seed.to_bytes(32, "big")))]
    for v in r["dropped"]:
        s_sk = shamir_rebuild([s[("s", v)] for s in first], coefficients)
        key = X25519PrivateKey.from_private_bytes(s_sk.to_bytes(32, "big"))
        for u in r["survivors"]:
            mask = prg(kdf(key.exchange(r["public_keys"][u][1])))
            sign = 1 if u < v else -1               # what survivor u added for v
            total = [(a - sign * m) % MOD for a, m in zip(total, mask)]
    return from_fixed(total)


def masking_unit_costs():
    """Laptop CPU time of each client-side operation, in seconds."""
    peer = X25519PrivateKey.generate().public_key()
    me = X25519PrivateKey.generate()
    key, nonce, payload = bytes(32), bytes(12), bytes(132)
    blob = AESGCM(key).encrypt(nonce, payload, None)
    return {
        "x25519_keygen": cpu_time(X25519PrivateKey.generate, inner=200),
        "x25519_exchange": cpu_time(lambda: me.exchange(peer), inner=200),
        "aes_gcm_encrypt": cpu_time(lambda: AESGCM(key).encrypt(nonce, payload, None), inner=200),
        "aes_gcm_decrypt": cpu_time(lambda: AESGCM(key).decrypt(nonce, blob, None), inner=200),
        "prg": cpu_time(lambda: prg(key), inner=200),
        "kdf": cpu_time(lambda: kdf(key), inner=200),
    }


def masking_client_ops(n):
    """Operations one client does in one round (fresh keys every round)."""
    t = n // 2 + 1
    return {"x25519_keygen": 2, "x25519_exchange": 2 * (n - 1), "aes_gcm_encrypt": n - 1,
            "aes_gcm_decrypt": n - 1, "prg": n, "kdf": 2 * (n - 1),
            "shamir_mults": 2 * n * t}            # Horner: 2 secrets, n shares, t coefficients


# ----------------------------------------------------------------------
# (c) Paillier (python-paillier with gmpy2)
# ----------------------------------------------------------------------
def paillier_values(update):
    w, n = update["weights"], update["num_samples"]
    return [x * n for x in w] + [n]


def paillier_client(public_key, update):
    """One ciphertext per value."""
    return [public_key.encrypt(v, precision=1 / SCALE) for v in paillier_values(update)]


def paillier_server(private_key, ciphertexts):
    sums = [reduce(lambda a, b: a + b, column) for column in zip(*ciphertexts)]
    values = [private_key.decrypt(s) for s in sums]
    return [v / values[NUM_WEIGHTS] for v in values[:NUM_WEIGHTS]]


def pack(update):
    """All 6 values in one plaintext: fixed point, made positive, SLOT bits each."""
    packed = 0
    for i, v in enumerate(paillier_values(update)):
        packed |= (round(v * SCALE) + OFFSET) << (SLOT * i)
    return packed


def paillier_packed_client(public_key, update):
    """One ciphertext for all values."""
    return public_key.raw_encrypt(pack(update))


def paillier_packed_server(private_key, ciphertexts, n):
    nsquare = private_key.public_key.nsquare
    total = reduce(lambda a, b: a * b % nsquare, ciphertexts)       # homomorphic sum
    packed = private_key.raw_decrypt(total)
    values = [((packed >> (SLOT * i)) & (2 ** SLOT - 1)) - n * OFFSET for i in range(VALUES)]
    samples = values[NUM_WEIGHTS] / SCALE
    return [v / SCALE / samples for v in values[:NUM_WEIGHTS]]


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    rng = random.Random(1)
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []

    def add(method, side, clients, seconds, key_bits=""):
        rows.append({"method": method, "side": side, "key_bits": key_bits, "clients": clients,
                     "cpu_ms": round(seconds * 1000, 4)})
        print(f"{method:26} {side:6} {str(key_bits):5} n={clients:<3} {seconds * 1000:10.3f} ms", flush=True)

    # Client-side unit costs of masking, and the counted client cost per round
    units = masking_unit_costs()
    # A Shamir step: one multiply-add mod PRIME (the 521-bit field used here)
    a, b = secrets.randbelow(PRIME), secrets.randbelow(PRIME)
    units["shamir_mults"] = cpu_time(lambda: (a * 37 + b) % PRIME, inner=2000)
    for name, seconds in units.items():
        rows.append({"method": f"unit:{name}", "side": "client", "key_bits": "", "clients": "",
                     "cpu_ms": round(seconds * 1000, 6)})

    keys = {}
    for bits in KEY_BITS:
        start = time.process_time()
        keys[bits] = paillier.generate_paillier_keypair(n_length=bits)
        add("paillier_keygen", "once", "", time.process_time() - start, bits)

    for n in CLIENT_COUNTS:
        updates = make_updates(n, rng)

        # (a) FedAvg
        add("fedavg", "server", n, cpu_time(lambda: fedavg(updates), inner=2000))

        # (b) Masking: server with no dropout and with 10% dropout; client counted
        for dropout, name in ((0.0, "masking"), (DROPOUT, "masking_10pct_dropout")):
            r = masking_round(updates, dropout)
            check(masking_server(r), [updates[u] for u in r["survivors"]], name)
            add(name, "server", n, cpu_time(lambda: masking_server(r)))
        ops = masking_client_ops(n)
        add("masking", "client", n, sum(count * units[op] for op, count in ops.items()))

        # (c) Paillier, one ciphertext per value and packed
        for bits in KEY_BITS:
            public_key, private_key = keys[bits]
            cts = [paillier_client(public_key, u) for u in updates]
            check(paillier_server(private_key, cts), updates, f"paillier {bits}")
            add("paillier", "server", n, cpu_time(lambda: paillier_server(private_key, cts)), bits)
            packed = [paillier_packed_client(public_key, u) for u in updates]
            check(paillier_packed_server(private_key, packed, n), updates, f"packed {bits}")
            add("paillier_packed", "server", n,
                cpu_time(lambda: paillier_packed_server(private_key, packed, n)), bits)

    # Paillier client cost does not depend on n: time one client's encryption
    for bits in KEY_BITS:
        public_key = keys[bits][0]
        update = make_updates(1, rng)[0]
        add("paillier", "client", "any", cpu_time(lambda: paillier_client(public_key, update), repeat=5), bits)
        add("paillier_packed", "client", "any",
            cpu_time(lambda: paillier_packed_client(public_key, update), repeat=5), bits)

    with open(OUT / "timings.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["method", "side", "key_bits", "clients", "cpu_ms"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {OUT / 'timings.csv'}")


if __name__ == "__main__":
    main()
