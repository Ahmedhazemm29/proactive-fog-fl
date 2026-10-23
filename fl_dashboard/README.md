# fl_dashboard

A live web page for the federated learning on the fog node, for demos: the
ESP32 FL clients, the current round, the loss per round and one row per round.

It runs on the laptop and only **listens** to the Pi's MQTT broker. It never
publishes, so it changes nothing on the broker, the Pi or the boards, and it
doesn't start a run. Start a run as usual with `pi/deploy.sh` (see
[pi/README.md](../pi/README.md)); the page follows it by itself.

## Start

From the repo root. No virtual environment is needed, because it uses only the
standard library:

```
python3 fl_dashboard/dashboard.py --rounds 5
```

Then open http://127.0.0.1:8766. Stop it with Ctrl+C.

The aggregator sends the run's total number of rounds with every round, so the
page shows "Round 3 of 5" by itself. `--rounds N` is only needed for an older
aggregator without join/leave; without it, such a run shows "of ?" until it is over.

| Option | Default | |
|---|---|---|
| `--rounds N` | not set | total rounds, for an older aggregator (0 = no limit) |
| `--broker` | `fognode1.local` | MQTT broker |
| `--broker-port` | `1883` | |
| `--port` | `8766` | port of the page, on 127.0.0.1 only |
| `--clients` | `hardware/esp_clients.md` | board table: names and MACs |
| `--skip` | `ESP-7` | boards of the table not shown (ESP-7 is faulty); `--skip ""` shows all |

## What the page shows

1. **Clients**: one card per board of `hardware/esp_clients.md` (by default
   ESP-1 to ESP-6 and ESP-8) with its FL ID (`esp32-` + the last 2 bytes of its
   MAC). The status has a color, an icon and a word:
   - **Active** (green ●): a fresh `online-active` status (or the older
     firmware's plain `online`), or a fresh update from the board. It trains in the rounds.
   - **Standby** (amber ◐): a fresh `online-standby`: connected, but out of the
     rounds. Every board starts in standby; `hardware/tools/fl_control.py join` makes it active.
   - **Offline** (red ✕): a fresh `offline`; the broker sends the board's Last Will when it drops.
   - **Unknown** (grey ?): only an old status stored (retained) on the broker.
     Right after the start every board is unknown until it sends something
     live, for example its update in the next round.

   A stored status that disagrees with the last live one (it changed while the
   broker connection was down) puts the board back to unknown. A board that
   isn't in the table appears only after a fresh message.
2. **Round**: the current round and the total, and the run's state: no run,
   round in progress, between rounds, finished, or only an old model still
   stored on the broker.
3. **Loss per round**: global loss (the global model on the clients' data,
   before local training) and avg loss (after local training), both weighted
   by `num_samples` as in the aggregator. "Log scale" shows the later rounds
   better. Joins and leaves are marked: a dashed line with "+ESP-5 −ESP-2"
   before the round where they took effect, a dotted line inside a round that a
   board left while it ran.
4. **Rounds**: per round, the active boards (the participants when it
   started), how many of them answered, the round time, which didn't answer
   (for the running round: which it is still waiting for), the joins and
   leaves, and both losses.

The pill at the top says whether the dashboard is connected to the broker
(it reconnects by itself) or whether the dashboard server has stopped.

**Whose numbers:** a finished round shows the aggregator's own numbers from its
`fog/global/round` message, the same as in `rounds.csv`. A running round, or
every round of an older aggregator without that message, is counted here; its
round time is then measured on the laptop, from the global model message to
the last client update. The joins and leaves come from the participants of
consecutive rounds, so they need the aggregator's messages too.

## How it works

A browser can't speak plain MQTT (port 1883). That would need a WebSocket
listener on the broker, which is a change on the Pi. So a small server on the
laptop does the listening:

- `mqtt_listen.py`: read-only MQTT 3.1.1 client. It subscribes to
  `fog/+/status`, `fog/+/update`, `fog/global/model` and `fog/global/round` with QoS 0 and a clean
  session, and sends only CONNECT, SUBSCRIBE, PINGREQ and DISCONNECT, never
  PUBLISH. Its client ID `fl-dashboard-<pid>` can't clash with the aggregator or
  a board. After a lost connection it tries again every 3 s.
- `fl_state.py`: the boards, rounds and losses, built from the messages. It has
  no network code, so it can be unit-tested on its own.
- `dashboard.py`: serves `static/` and `/api/state` on 127.0.0.1:8766. The page
  asks for the state every second. Only the page's own files are served, and
  only to requests for 127.0.0.1 or localhost.
- `static/`: `index.html`, `style.css` (light and dark mode follow the system
  setting), `app.js`, and the chart library in `static/vendor/`.

## Libraries and packages

| Name | Version | File | License |
|---|---|---|---|
| Chart.js | 4.5.1 | `static/vendor/chart-4.5.1.umd.min.js` | MIT, `static/vendor/chart-4.5.1-LICENSE.md` |

The Chart.js file is `package/dist/chart.umd.min.js` from the npm package
`chart.js@4.5.1`, checked against the registry's sha512 checksum (sha256 of the
file: `48444a82d4edcb5bec0f1965faacdde18d9c17db3063d042abada2f705c9f54a`).
The newest version, 4.6.1, was only a day old (2026-10-22), so the one before it was used.

**Python packages: none.** Only the standard library is used (Python 3.8 or
newer; tested with 3.10.12). The page loads nothing from the internet, only
files from this folder, so it works offline as long as the laptop can reach
the broker on the local network.

## Tests

```
.venv/bin/python -m unittest discover -s tests -p test_fl_dashboard.py -v
```

`tests/test_fl_dashboard.py` covers the board and round rules. It also runs the
listener against a fake broker on 127.0.0.1 that records every packet the
listener sends: only CONNECT, SUBSCRIBE and DISCONNECT, never PUBLISH.
