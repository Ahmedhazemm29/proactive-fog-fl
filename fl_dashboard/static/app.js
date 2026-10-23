// FL live dashboard: asks the local server for the state every second and
// draws the boards, the round, the loss chart and the rounds table.
// All text from the server is set with textContent, never as HTML.
"use strict";

const POLL_MS = 1000;
const $ = (id) => document.getElementById(id);

const STATUS = {
  active: { icon: "●", label: "Active" },
  standby: { icon: "◐", label: "Standby" },
  offline: { icon: "✕", label: "Offline" },
  unknown: { icon: "?", label: "Unknown" },
};

// ---- Small helpers ----

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function clock(epoch) {
  return epoch ? new Date(epoch * 1000).toLocaleTimeString([], { hour12: false }) : "–";
}

function ago(seconds) {
  if (seconds < 60) return `${Math.max(0, Math.round(seconds))} s ago`;
  return `${Math.round(seconds / 60)} min ago`;
}

function loss(value) {
  return value === null || value === undefined ? "–" : value.toFixed(4);
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

// "+ESP-5 −ESP-2", or "+3 −1" when there are many
function changes(joined, left) {
  const names = [...joined.map((n) => `+${n}`), ...left.map((n) => `−${n}`)];
  return names.length > 2 ? `+${joined.length} −${left.length}` : names.join(" ");
}

// ---- Broker indicator ----

function showConnection(state) {
  const box = $("broker");
  const icon = box.querySelector(".conn-icon");
  let kind, symbol, text;
  if (!state) {
    [kind, symbol, text] = ["conn-down", "✕", "Dashboard server not running"];
  } else {
    const b = state.broker;
    const where = `${b.host}:${b.port}`;
    if (b.connected) {
      [kind, symbol, text] = ["conn-ok", "●", `Connected to broker ${where}`];
    } else if (!b.error) {
      [kind, symbol, text] = ["conn-wait", "…", `Connecting to broker ${where}…`];
    } else {
      [kind, symbol, text] = ["conn-down", "✕", `Disconnected from broker ${where}, retrying (${b.error})`];
    }
  }
  box.className = `conn ${kind}`;
  icon.textContent = symbol;
  $("broker-text").textContent = text;
  document.body.classList.toggle("broker-down", !state || !state.broker.connected);
}

// ---- 1. Boards ----

function boardCard(board) {
  const status = STATUS[board.status] || STATUS.unknown;
  const card = el("article", `board ${board.status}`);
  card.append(el("div", "board-name", board.name), el("div", "board-id", board.fl_id));

  const badge = el("div", `badge ${board.status}`);
  const icon = el("span", "", status.icon);
  icon.setAttribute("aria-hidden", "true");
  badge.append(icon, el("span", "", status.label));
  card.append(badge);

  let detail;
  if (board.status === "unknown") {
    detail = board.stored ? `Stored status: ${board.stored} (may be old)` : "No status yet";
  } else {
    detail = `Live ${board.seen_what} at ${clock(board.seen)}`;
  }
  if (!board.expected) detail += " · not in the board list";
  card.append(el("div", "board-detail", detail));
  return card;
}

function showBoards(state) {
  $("boards").replaceChildren(...state.boards.map(boardCard));
  const count = (status) => state.boards.filter((b) => b.status === status).length;
  let summary = ["active", "standby", "offline", "unknown"]
    .map((status) => `${count(status)} ${status}`).join(" · ");
  if (!state.broker.connected) summary += " · broker connection lost, statuses may be out of date";
  $("clients-summary").textContent = summary;
}

// ---- 2. Round counter ----

function showRun(state) {
  const run = state.run;
  const current = state.rounds.length ? state.rounds[state.rounds.length - 1] : null;
  let total = "";
  if (run && run.state === "finished") total = `of ${run.round}`;
  else if (state.total_rounds === 0) total = "no round limit";
  else if (state.total_rounds) total = `of ${state.total_rounds}`;
  else if (run) total = "of ?";

  $("round-now").textContent = run && run.round !== null ? run.round : "–";
  $("round-total").textContent = total;

  let headline, detail;
  if (!run) {
    headline = "No FL round running";
    detail = "Rounds appear here by themselves as soon as the aggregator starts on the Pi.";
  } else if (run.state === "stale") {
    headline = "No live round right now";
    detail = `The broker still stores round ${run.round} of the run started at ${clock(run.id)}; it may be old.`;
  } else if (run.state === "finished") {
    headline = `Run finished after ${run.round} rounds`;
    detail = `Started ${clock(run.id)}, finished ${clock(run.finished)}.`;
  } else {
    headline = current && current.in_progress ? "Round in progress" : "Between rounds";
    detail = `Run started ${clock(run.id)} · last FL message ${ago(state.now - run.last_message)}`;
    if (current && current.active !== null) detail += ` · ${current.active} active in this round`;
  }
  $("run-state").textContent = headline;
  $("run-detail").textContent = detail;
}

// ---- 3. Loss chart, with join/leave markers ----

let chart = null;
let chartKey = "";

// Draws the join/leave markers: a dashed line before the round where joins or
// leaves took effect, a dotted line in a round that a board left mid-round.
// A few lines of our own instead of an extra chart library.
const joinLeaveMarkers = {
  id: "joinLeaveMarkers",
  afterDatasetsDraw(c) {
    const area = c.chartArea;
    const ctx = c.ctx;
    ctx.save();
    ctx.strokeStyle = ctx.fillStyle = cssVar("--text");
    ctx.lineWidth = 1.5;
    ctx.font = "13px system-ui, sans-serif";
    ctx.textAlign = "center";
    for (const mark of c.$marks || []) {
      const x = c.scales.x.getPixelForValue(mark.x);
      if (x < area.left || x > area.right) continue;
      ctx.setLineDash(mark.dotted ? [2, 3] : [7, 4]);
      ctx.beginPath();
      ctx.moveTo(x, area.top + 16);
      ctx.lineTo(x, area.bottom);
      ctx.stroke();
      ctx.fillText(mark.label, x, area.top + 11);
    }
    ctx.restore();
  },
};

function makeChart() {
  Chart.defaults.font.size = 14;                // readable on a demo screen
  chart = new Chart($("loss-chart"), {
    type: "line",
    data: {
      datasets: [
        { label: "Global loss (before local training)", data: [], borderWidth: 3,
          pointRadius: 4, pointStyle: "circle" },
        { label: "Avg loss (after local training)", data: [], borderWidth: 3,
          borderDash: [8, 5], pointRadius: 5, pointStyle: "triangle" },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      layout: { padding: { top: 6 } },
      interaction: { mode: "nearest", axis: "x", intersect: false },
      scales: {
        // Linear, so a marker can sit between two rounds (at 2.5, say); one tick per round
        x: { type: "linear", title: { display: true, text: "Round" }, ticks: {}, grid: {},
             afterBuildTicks: (scale) => {
               const ticks = [];
               for (let v = Math.ceil(scale.min); v <= scale.max; v++) ticks.push({ value: v });
               scale.ticks = ticks;
             } },
        y: { title: { display: true, text: "Loss (mean squared error)" }, beginAtZero: true,
             ticks: {}, grid: {} },
      },
      plugins: {
        legend: { labels: { usePointStyle: true, boxWidth: 12, boxHeight: 8 } },   // small markers
        tooltip: { callbacks: { title: (items) => `Round ${items[0].parsed.x}`,
                                label: (c) => `${c.dataset.label}: ${c.parsed.y.toFixed(4)}` } },
      },
    },
    plugins: [joinLeaveMarkers],
  });
  applyTheme();
}

function applyTheme() {
  // Colors come from the CSS variables, so the chart follows light and dark mode
  const [globalSet, avgSet] = chart.data.datasets;
  globalSet.borderColor = globalSet.backgroundColor = cssVar("--global");
  avgSet.borderColor = avgSet.backgroundColor = cssVar("--avg");
  for (const axis of ["x", "y"]) {
    const scale = chart.options.scales[axis];
    scale.ticks.color = scale.title.color = cssVar("--muted");
    scale.grid.color = cssVar("--grid");
  }
  chart.options.plugins.legend.labels.color = cssVar("--text");
  chart.update();
}

function logTickLabel(value) {
  // On the log axis, label only 1, 2 and 5 times a power of ten, so labels don't overlap
  const leading = value / 10 ** Math.floor(Math.log10(value));
  return [1, 2, 5].some((x) => Math.abs(leading - x) < 1e-9) ? String(value) : "";
}

function setScale() {
  // A log axis shows the later rounds too: the loss often drops 30x after round 1.
  // It can't start at 0, so only the linear axis does.
  const log = $("log-scale").checked;
  const y = chart.options.scales.y;
  y.type = log ? "logarithmic" : "linear";
  y.beginAtZero = !log;
  if (log) y.ticks.callback = logTickLabel;
  else delete y.ticks.callback;               // back to Chart.js's own labels
  chart.update();
}

function showChart(state) {
  const withLoss = state.rounds.filter((r) => r.global_loss !== null);
  $("chart-empty").hidden = withLoss.length > 0;
  const marks = [];
  for (const r of state.rounds) {
    if (r.joined.length || r.left.length) marks.push({ x: r.round - 0.5, label: changes(r.joined, r.left) });
    if (r.dropped.length) marks.push({ x: r.round, label: changes([], r.dropped), dotted: true });
  }
  const key = JSON.stringify([withLoss.map((r) => [r.round, r.global_loss, r.avg_loss]), marks]);
  if (key === chartKey) return;                 // nothing new: don't redraw
  chartKey = key;
  const last = state.rounds.length ? state.rounds[state.rounds.length - 1].round : 1;
  chart.options.scales.x.min = 0.5;
  chart.options.scales.x.max = last + 0.5;
  chart.data.datasets[0].data = withLoss.map((r) => ({ x: r.round, y: r.global_loss }));
  chart.data.datasets[1].data = withLoss.map((r) => ({ x: r.round, y: r.avg_loss }));
  chart.$marks = marks;
  chart.update();
}

// ---- 4. Rounds table ----

function showRounds(state) {
  const rows = [...state.rounds].reverse().map((r) => {
    const tr = el("tr", r.in_progress ? "in-progress" : "");
    let missing;
    if (r.in_progress) missing = r.missing.length ? `waiting for ${r.missing.join(", ")}` : "all answered";
    else missing = r.missing.length ? r.missing.join(", ") : "all answered";
    const moves = [changes(r.joined, r.left), ...r.dropped.map((n) => `−${n} (mid-round)`)]
      .filter((text) => text).join(", ");
    tr.append(
      el("td", "num", r.in_progress ? `${r.round} (running)` : String(r.round)),
      el("td", "num", r.active === null ? "–" : String(r.active)),
      el("td", "num", `${r.answered} / ${r.active === null ? state.expected : r.active}`),
      el("td", "num", r.round_s === null ? "–" : `${r.round_s.toFixed(2)} s`),
      el("td", "wrap", missing),
      el("td", "wrap", moves || "–"),
      el("td", "num", loss(r.global_loss)),
      el("td", "num", loss(r.avg_loss)),
    );
    return tr;
  });
  $("rounds-body").replaceChildren(...rows);
  $("rounds-empty").hidden = rows.length > 0;
}

// ---- Main loop ----

async function poll() {
  try {
    const response = await fetch("/api/state", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const state = await response.json();
    showConnection(state);
    showBoards(state);
    showRun(state);
    showChart(state);
    showRounds(state);
  } catch (error) {
    showConnection(null);                       // keep the last data, but say the server is gone
  } finally {
    setTimeout(poll, POLL_MS);
  }
}

makeChart();
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", applyTheme);
$("log-scale").addEventListener("change", setScale);
poll();
