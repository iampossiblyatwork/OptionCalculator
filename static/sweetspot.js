"use strict";

// Strike x expiration heatmap of covered-call risk-adjusted yield. Each cell's
// colour and headline number are the same metric -- the expected annualized
// yield (annualized premium yield x probability of keeping the shares) -- so the
// brightest cell is always the ringed sweet spot.

const SHARES_PER_CONTRACT = 100;

const $ = (id) => document.getElementById(id);
const heatmap = $("ss-heatmap");
const detail = $("ss-detail");

// Colour ramp: deep blue-grey (low) -> teal -> bright green (high).
const STOPS = [
  [0.0, [17, 35, 58]],
  [0.5, [31, 122, 90]],
  [1.0, [124, 246, 176]],
];

function rampRgb(t) {
  t = Math.max(0, Math.min(1, t));
  for (let i = 1; i < STOPS.length; i++) {
    const [t0, c0] = STOPS[i - 1];
    const [t1, c1] = STOPS[i];
    if (t <= t1) {
      const f = (t - t0) / (t1 - t0 || 1);
      return c0.map((v, k) => Math.round(v + (c1[k] - v) * f));
    }
  }
  return STOPS[STOPS.length - 1][1];
}

// Dark text reads fine on the bright-green end of the ramp but disappears on
// the near-black low end, so pick the label colour from the cell's own
// luminance instead of hardcoding one in CSS.
function textColorFor([r, g, b]) {
  const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return luminance > 0.5 ? "#06121b" : "#eaf6ef";
}

const fmtPct = (v) => (Number.isFinite(v) ? (v * 100).toFixed(1) + "%" : "—");
const fmtPct0 = (v) => (Number.isFinite(v) ? Math.round(v * 100) + "%" : "—");
const fmtUsd = (v) =>
  Number.isFinite(v)
    ? "$" + v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : "—";

let current = null; // last grid response

function payload() {
  return {
    ticker: $("ticker").value,
    spot: $("spot").value,
    ivPct: $("ivPct").value,
    ratePct: $("ratePct").value,
    divPct: $("divPct").value,
  };
}

function setSourceNote(text) {
  const el = $("ss-source");
  if (!el) return;
  el.hidden = !text;
  el.textContent = text || "";
}

async function load() {
  let res;
  try {
    res = await fetch("/api/sweet-spot", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload()),
    });
  } catch (e) {
    heatmap.innerHTML = "";
    detail.innerHTML =
      '<div class="ss-detail-title">Couldn\'t reach the server</div>' +
      '<p class="opt-note">Check your connection and try again.</p>';
    setSourceNote("");
    return;
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    heatmap.innerHTML = "";
    detail.innerHTML = '<div class="ss-detail-title">Check your inputs</div>';
    setSourceNote(body.error || "Couldn't load the grid — check your inputs.");
    return;
  }
  current = await res.json();
  renderGrid(current);
  selectCell(current.best.row, current.best.col);
  setSourceNote(
    current.dataSource === "live"
      ? `Live strikes & expirations for ${current.ticker}, from Massive.`
      : "Synthetic strike/expiration grid — enter a ticker above for live listed contracts.",
  );
}

function renderGrid(d) {
  const strikes = d.strikes;
  const days = d.days;

  // Normalise scores for colouring.
  let min = Infinity;
  let max = -Infinity;
  d.grid.forEach((row) =>
    row.forEach((c) => {
      if (c.risk_adjusted_score < min) min = c.risk_adjusted_score;
      if (c.risk_adjusted_score > max) max = c.risk_adjusted_score;
    }),
  );
  const span = max - min || 1;

  heatmap.style.gridTemplateColumns = `auto repeat(${strikes.length}, minmax(40px, 1fr))`;
  heatmap.innerHTML = "";

  // Header row: empty corner + strike labels.
  const corner = document.createElement("div");
  corner.className = "ss-corner";
  corner.textContent = "DTE \\ K";
  heatmap.append(corner);
  strikes.forEach((k) => {
    const h = document.createElement("div");
    h.className = "ss-colhead";
    h.textContent = k;
    heatmap.append(h);
  });

  // Body rows.
  d.grid.forEach((row, di) => {
    const rh = document.createElement("div");
    rh.className = "ss-rowhead";
    rh.textContent = days[di] + "d";
    heatmap.append(rh);

    row.forEach((c, si) => {
      const cell = document.createElement("button");
      cell.type = "button";
      cell.className = "ss-cell";
      const rgb = rampRgb((c.risk_adjusted_score - min) / span);
      cell.style.background = `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;
      cell.style.color = textColorFor(rgb);
      cell.textContent = fmtPct0(c.risk_adjusted_score);
      cell.dataset.row = di;
      cell.dataset.col = si;
      if (di === d.best.row && si === d.best.col) cell.classList.add("best");
      cell.addEventListener("click", () => selectCell(di, si));
      heatmap.append(cell);
    });
  });
}

function selectCell(row, col) {
  if (!current) return;
  heatmap.querySelectorAll(".ss-cell.selected").forEach((el) =>
    el.classList.remove("selected"),
  );
  const cellEl = heatmap.querySelector(
    `.ss-cell[data-row="${row}"][data-col="${col}"]`,
  );
  if (cellEl) cellEl.classList.add("selected");

  const c = current.grid[row][col];
  const isBest = row === current.best.row && col === current.best.col;
  const rows = [
    ["Expected annualized yield", fmtPct(c.risk_adjusted_score), "good"],
    ["Premium / share", fmtUsd(c.premium)],
    ["Premium / contract", fmtUsd(c.premium * SHARES_PER_CONTRACT)],
    ["Annualized premium yield", fmtPct(c.annualized_yield)],
    ["Yield over the period", fmtPct(c.static_yield)],
    ["Chance you keep shares", fmtPct(c.prob_keep_shares)],
    ["Chance of assignment", fmtPct(c.prob_assigned)],
    ["Annualized if called", fmtPct(c.return_if_called_annualized)],
    ["Delta", c.delta.toFixed(2)],
  ];

  detail.innerHTML = "";
  const title = document.createElement("div");
  title.className = "ss-detail-title";
  title.innerHTML =
    `Sell the <strong>$${c.strike}</strong> call · <strong>${c.days}</strong> days` +
    (isBest ? ' <span class="ss-badge">sweet spot</span>' : "");
  detail.append(title);

  rows.forEach(([label, value, tone]) => {
    const r = document.createElement("div");
    r.className = "ss-detail-row";
    const l = document.createElement("span");
    l.className = "ss-detail-label";
    l.textContent = label;
    const v = document.createElement("span");
    v.className = "ss-detail-value " + (tone || "");
    v.textContent = value;
    r.append(l, v);
    detail.append(r);
  });

  const note = document.createElement("p");
  note.className = "opt-note";
  note.textContent =
    "Expected annualized yield = annualized premium yield × the chance the call " +
    "expires worthless. It rewards income you're likely to actually keep.";
  detail.append(note);
}

["ticker", "spot", "ivPct", "ratePct", "divPct"].forEach((id) =>
  $(id).addEventListener("input", load),
);

load();
