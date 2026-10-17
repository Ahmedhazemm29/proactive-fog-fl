"""
Tests for the live demo of step 4B (no Docker needed). Run all tests with:

    .venv/bin/python -m unittest discover -s tests -v

1. Load generator: the planned send times, and real replays against a tiny
   local HTTP server: on time, counted per step, timeouts and errors.
2. Scaler logic: the step-by-step cooldown loop equals step 4A's run(), the
   20-worker cap, KHPA from CPU, requested workers from CPU, CPU per step from
   cgroup readings, and the settings of the three scalers.
3. Cluster safety: the HAProxy config and that cleanup only touches containers
   with the thesis.live=1 label.
"""
import asyncio
import os
import sys
import time
import unittest
from unittest import mock

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from autoscaler import cluster, live, loadgen, scalers  # noqa: E402
import live_run  # noqa: E402


# ----------------------------------------------------------------------
# 1. Load generator
# ----------------------------------------------------------------------
async def serve(handler, body):
    """A tiny HTTP/1.1 server on a free local port. Returns (server, port)."""
    server = await asyncio.start_server(lambda r, w: handler(r, w, body), "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


def answer(status, delay=0.0):
    async def handler(reader, writer, body):
        try:
            while await reader.readuntil(b"\r\n\r\n"):
                await asyncio.sleep(delay)
                writer.write(f"HTTP/1.1 {status}\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()
    return handler


def replay_against(handler, counts, step_seconds, timeout=1.0):
    async def go():
        server, port = await serve(handler, b'{"ok": true}')
        replay = loadgen.Replay("127.0.0.1", port, counts, step_seconds, timeout=timeout, connections=8)
        started = time.monotonic()
        await replay.run(started + 0.05)
        seconds = time.monotonic() - started
        server.close()
        await server.wait_closed()
        await asyncio.sleep(0.05)            # let the server's handlers see the closed connections
        return replay, seconds
    return asyncio.run(go())


class LoadGenerator(unittest.TestCase):

    def test_schedule_spreads_each_step_evenly(self):
        times, steps = loadgen.schedule([4, 0, 2], 10.0)
        np.testing.assert_allclose(times, [0, 2.5, 5, 7.5, 20, 25])
        np.testing.assert_array_equal(steps, [0, 0, 0, 0, 2, 2])

    def test_schedule_stays_inside_its_step(self):
        counts = [1, 7, 1650, 29700]
        times, steps = loadgen.schedule(counts, 10.0)
        self.assertEqual(len(times), sum(counts))
        self.assertTrue(np.all(times >= steps * 10.0) and np.all(times < (steps + 1) * 10.0))
        self.assertTrue(np.all(np.diff(times) > 0))

    def test_replay_is_on_time_and_counted_per_step(self):
        replay, seconds = replay_against(answer("200 OK"), [20, 40], 0.5)
        rows = replay.per_step(2)
        self.assertEqual([r["sent"] for r in rows], [20, 40])
        self.assertEqual([r["failed"] for r in rows], [0, 0])
        self.assertTrue(np.all(replay.outcome == loadgen.OK))
        # Every request was queued within 20 ms of its planned time, and the
        # whole replay took the planned 1 s (plus the last answer).
        self.assertLess(np.max(replay.queue_delay), 0.02)
        self.assertGreater(seconds, 0.95)
        self.assertLess(seconds, 1.3)

    def test_slow_answers_are_timeouts(self):
        replay, _ = replay_against(answer("200 OK", delay=0.3), [5], 0.25, timeout=0.1)
        rows = replay.per_step(1)
        self.assertEqual((rows[0]["sent"], rows[0]["failed"], rows[0]["timeouts"]), (5, 5, 5))
        self.assertTrue(np.all(np.isnan(replay.latency)))

    def test_error_status_is_a_failure(self):
        replay, _ = replay_against(answer("503 Service Unavailable"), [6], 0.3)
        self.assertTrue(np.all(replay.outcome == loadgen.HTTP_ERROR))
        self.assertEqual(replay.per_step(1)[0]["failed"], 6)


# ----------------------------------------------------------------------
# 2. Scaler logic
# ----------------------------------------------------------------------
S = live_run.settings("planner", workload_pod=1650, fixed_pods=8)


class Scalers(unittest.TestCase):

    def test_stepper_equals_step_4a(self):
        # The same random wishes through run() of step 4A and through the Stepper
        wishes = np.random.default_rng(0).integers(1, 30, 200)
        s = scalers.Settings(pods_max=20)
        expected, ups, downs = scalers.run(lambda t, current: int(wishes[t]), 200, 8, s)
        stepper = live.Stepper(8, s.cdt_up, s.cdt_down, s.pods_max)
        got = [stepper.step(t, lambda current: int(wishes[t])) for t in range(200)]
        np.testing.assert_array_equal(got, expected)
        self.assertEqual((stepper.ups, stepper.downs), (ups, downs))
        self.assertLessEqual(max(got), 20)

    def test_stepper_cooldowns(self):
        # Up at step 0, locked for steps 1 and 2; down at 3, locked for 4 to 7; free at 8
        stepper = live.Stepper(5, 3, 5, 20)
        wishes = [10, 2, 2, 2, 9, 9, 9, 9, 9]
        got = [stepper.step(t, lambda current: wishes[t]) for t in range(9)]
        self.assertEqual(got, [10, 10, 10, 2, 2, 2, 2, 2, 9])

    def test_cap_of_20_workers(self):
        stepper = live.Stepper(8, 3, 5, cluster.MAX_WORKERS)
        self.assertEqual(stepper.step(0, lambda current: 45), 20)
        # A huge forecast asks the planner for more than 20; the Stepper caps it
        self.assertEqual(scalers.planner_step(np.full(5, 1650 * 40.0), 8, S), 40)

    def test_khpa_from_cpu(self):
        # 3.5 cores at 0.35 per worker is exactly 10 (no float error makes it 11)
        self.assertEqual(live.khpa_pods(3.5, 0.5, 0.7, 1), 10)
        self.assertEqual(live.khpa_pods(3.51, 0.5, 0.7, 1), 11)
        self.assertEqual(live.khpa_pods(0.0, 0.5, 0.7, 1), 1)

    def test_requested_from_cpu(self):
        np.testing.assert_array_equal(live.requested_from_cpu([0.0, 0.35, 0.36, 6.3], 0.5, 0.7), [1, 1, 2, 18])

    def test_cpu_per_step(self):
        before = {1: (10.0, 0.0), 3: (5.0, 0.0)}
        after = {1: (15.0, 1.0), 2: (2.0, 0.0), 3: (1.0, 0.0)}    # 2 started, 3 restarted
        used = live.cpu_per_step(before, after, 10.0)
        self.assertEqual(used, {1: (0.5, 0.1), 2: (0.2, 0.0), 3: (0.1, 0.0)})

    def test_fresh_cpu_waits_for_a_scrape_after_the_step_start(self):
        # Scrapes are stored at 98, 103, 108 s (fake clock). The step starts at 100 s, the newest
        # stored scrape is 98 s until the clock passes 103.4 s (storing takes 0.4 s).
        now = [100.0]
        stored = lambda: max(t for t in (98.0, 103.0, 108.0) if t + 0.4 <= now[0])  # noqa: E731
        asked = []
        cpu, scrape, waited, fresh = live.fresh_cpu(
            stored, lambda at: asked.append(at) or 3.0, 100.0, clock=lambda: now[0],
            sleep=lambda s: now.__setitem__(0, now[0] + s))
        self.assertEqual((cpu, scrape, fresh), (3.0, 103.0, True))
        self.assertEqual(asked, [103.0])                  # evaluated at the scrape's own time
        self.assertTrue(3.4 - 1e-9 <= waited <= 3.5 + 1e-9)    # within one poll of 0.1 s

    def test_fresh_cpu_gives_up_after_the_timeout(self):
        now = [100.0]
        cpu, scrape, waited, fresh = live.fresh_cpu(
            lambda: 98.0, lambda at: 2.0, 100.0, timeout=2.0, clock=lambda: now[0],
            sleep=lambda s: now.__setitem__(0, now[0] + s))
        self.assertEqual((cpu, scrape, fresh), (2.0, 98.0, False))
        self.assertGreaterEqual(waited, 2.0)

    def test_cpu_share(self):
        # prom[k] is read at the start of step k, so it is compared with the real CPU of step k - 1
        self.assertAlmostEqual(live.cpu_share([9.0, 2.0, 4.0, float("nan")], [2.0, 4.0, 6.0, 8.0]), 1.0)
        self.assertAlmostEqual(live.cpu_share([0.0, 1.6, 3.2], [2.0, 4.0, 6.0]), 0.8)

    def test_settings_of_the_three_scalers(self):
        # The planner gets the calibrated 1650 requests per step and worker, exactly
        self.assertEqual(S.capacity, 1650)
        self.assertEqual((S.pods_min, S.cdt_up, S.cdt_down, S.sdr, S.pods_max), (5, 3, 5, 0.3, 20))
        self.assertEqual(scalers.planner_step(np.full(5, 1650 * 10 + 1.0), 8, S), 11)
        self.assertEqual(live_run.settings("khpa", 1650, 8).pods_min, 1)
        self.assertEqual(live_run.settings("none", 1650, 8).fixed_pods, 8)


# ----------------------------------------------------------------------
# 3. Cluster safety
# ----------------------------------------------------------------------
class Cluster(unittest.TestCase):

    def test_haproxy_config(self):
        config = cluster.haproxy_config()
        self.assertIn("balance roundrobin", config)
        servers = [line for line in config.splitlines() if line.strip().startswith("server ")]
        self.assertEqual(len(servers), 20)
        self.assertTrue(all(line.endswith("disabled") for line in servers))

    def test_cleanup_only_touches_live_containers(self):
        calls = []

        def fake_docker(*args, check=True):
            calls.append(args)
            return "abc123" if args[:2] == ("ps", "-aq") else ""

        with mock.patch.object(cluster, "docker", fake_docker):
            cluster.cleanup(log=lambda *a: None)
        self.assertEqual(calls[0], ("ps", "-aq", "--filter", "label=thesis.live=1"))
        self.assertEqual(calls[1], ("rm", "-f", "abc123"))       # only what that filter found


if __name__ == "__main__":
    unittest.main()
