"""
Load generator of step 4B: replays traffic step by step against the load balancer.

Open loop: every request has a planned send time, and it is sent then, no
matter how slow the earlier ones are. Step k gets counts[k] requests, spread
evenly over its step_seconds. The response time is measured from the planned
send time, so waiting for a free connection counts too.

A request fails when the answer is not "200 OK", the connection breaks, or no
answer comes within `timeout` seconds of the planned send time.

Standard library only (asyncio). A pool of keep-alive connections sends the
requests; a request waits in a queue while all connections are busy. The pool
must be large: an overloaded request holds its connection up to about 1 s
(HAProxy's queue timeout), and the peak is about 3,000 requests per second.
With 256 connections the generator itself became the bottleneck under
overload, and almost every request expired in its own queue.
"""
import asyncio
import collections
import time

import numpy as np

OK, HTTP_ERROR, TIMEOUT, BROKEN = 1, 2, 3, 4     # outcome of a request (0 = not done yet)


def schedule(counts, step_seconds):
    """
    Planned send times (seconds from the start) and the step of every request.
    counts[k] requests in step k, evenly spaced: k*step + i*step/counts[k].
    """
    times, steps = [], []
    for k, n in enumerate(counts):
        n = int(n)
        times.append(k * step_seconds + np.arange(n) * (step_seconds / n) if n else np.empty(0))
        steps.append(np.full(n, k))
    return np.concatenate(times), np.concatenate(steps).astype(np.int64)


class Replay:
    """
    One replay. After run(), for every request: outcome, latency (s, NaN if
    failed), queue delay (when the generator queued it, minus the planned time:
    the generator's own timing) and send delay (when it went out on a
    connection, minus the planned time: also counts waiting for a free one).
    """

    def __init__(self, host, port, counts, step_seconds, timeout=2.0, connections=6000, path="/work"):
        self.host, self.port, self.path = host, port, path
        self.times, self.steps = schedule(counts, step_seconds)
        self.timeout = timeout
        self.connections = connections
        n = len(self.times)
        self.outcome = np.zeros(n, dtype=np.int8)
        self.latency = np.full(n, np.nan)
        self.queue_delay = np.full(n, np.nan)
        self.send_delay = np.full(n, np.nan)
        self.errors = collections.Counter()        # why requests broke, for the run report
        self.request = f"GET {path} HTTP/1.1\r\nHost: {host}\r\n\r\n".encode()

    async def run(self, start):
        """Send everything. `start` is the time.monotonic() of planned time 0."""
        queue = asyncio.Queue()
        senders = [asyncio.create_task(self.sender(queue, start)) for _ in range(self.connections)]
        # Put each request in the queue at its planned time (all that are due, then sleep).
        i, n = 0, len(self.times)
        while i < n:
            now = time.monotonic() - start
            while i < n and self.times[i] <= now:
                queue.put_nowait(i)
                self.queue_delay[i] = now - self.times[i]
                i += 1
            if i < n:
                await asyncio.sleep(max(0.0, self.times[i] - (time.monotonic() - start)))
        for _ in senders:
            queue.put_nowait(None)
        await asyncio.gather(*senders)

    async def sender(self, queue, start):
        """One connection: take the next request, send it, read the answer."""
        reader = writer = None
        while (i := await queue.get()) is not None:
            planned = start + self.times[i]
            deadline = planned + self.timeout
            try:
                if time.monotonic() >= deadline:
                    raise asyncio.TimeoutError
                if writer is None:
                    reader, writer = await asyncio.wait_for(
                        asyncio.open_connection(self.host, self.port), deadline - time.monotonic())
                self.send_delay[i] = time.monotonic() - planned
                writer.write(self.request)
                status, keep = await asyncio.wait_for(read_response(reader), deadline - time.monotonic())
                self.latency[i] = time.monotonic() - planned
                self.outcome[i] = OK if status == 200 else HTTP_ERROR
                if not keep:
                    writer.close()
                    reader = writer = None
            except asyncio.TimeoutError:
                self.outcome[i] = TIMEOUT
                writer = close(writer)
            except (OSError, asyncio.IncompleteReadError, ValueError) as error:
                self.outcome[i] = BROKEN
                self.errors[type(error).__name__] += 1
                writer = close(writer)
            if self.outcome[i] != OK:
                self.latency[i] = np.nan
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    def per_step(self, steps):
        """Requests sent, failed (of those: 503 or other error status, timed out), median and p95 time (ms) per step."""
        rows = []
        for k in range(steps):
            mine = self.steps == k
            ok = mine & (self.outcome == OK)
            ms = self.latency[ok] * 1000
            rows.append({
                "sent": int(mine.sum()),
                "failed": int((mine & (self.outcome != OK)).sum()),
                "rejected": int((mine & (self.outcome == HTTP_ERROR)).sum()),
                "timeouts": int((mine & (self.outcome == TIMEOUT)).sum()),
                "p50_ms": float(np.median(ms)) if len(ms) else float("nan"),
                "p95_ms": float(np.percentile(ms, 95)) if len(ms) else float("nan"),
            })
        return rows


async def read_response(reader):
    """Status code of one HTTP/1.1 answer, and whether the connection stays open. Reads the body too."""
    head = await reader.readuntil(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    status = int(lines[0].split()[1])
    headers = {}
    for line in lines[1:]:
        if ":" in line:
            name, value = line.split(":", 1)
            headers[name.strip().lower()] = value.strip().lower()
    await reader.readexactly(int(headers.get("content-length", "0")))
    return status, headers.get("connection") != "close"


def close(writer):
    if writer is not None:
        writer.close()
    return None
