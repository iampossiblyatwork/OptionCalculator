"use strict";

// Field metadata mirrors the labels Flask renders; kept here so we can rebuild
// the strategy-specific inputs on the client without a round-trip.
const FIELD_LABELS = {
  strike: "Strike ($)",
  premium: "Premium / share ($)",
  strike2: "Strike — short leg ($)",
  premium2: "Premium — short leg ($)",
  costBasis: "Your cost basis / share ($) — optional",
  currentPrice: "Current share price ($)",
};

const DEFAULTS = {
  strike: 260,
  premium: 22.7,
  strike2: 120,
  premium2: 1,
  costBasis: "", // optional — leave blank to price the trade off today's price
  currentPrice: 261,
};

const BLURBS = {};
const STRATEGY_FIELDS = {};

const $ = (id) => document.getElementById(id);
const form = $("opt-form");
const strategySel = $("strategy");
const fieldsHost = $("strategy-fields");
const usePricer = $("usePricer");

// Read strategy blurbs/fields from the rendered <option> data attributes and a
// lookup we build from the server-provided list embedded in the page.
function initStrategyMeta() {
  Array.from(strategySel.options).forEach((o) => {
    STRATEGY_FIELDS[o.value] = (o.dataset.fields || "").split(",").filter(Boolean);
  });
}

// Blurbs aren't in the DOM, so fetch the first calc lazily isn't needed —
// instead we keep a small client copy keyed by id.
Object.assign(BLURBS, {
  "covered-call":
    "You own the shares and sell a call against them to collect premium. Capped upside at the strike; premium cushions a drop. Cost basis is optional — returns are measured against today's share price.",
  "cash-secured-put":
    "Sell a put and set aside cash to buy the shares if assigned. You collect premium; your effective buy price is the strike minus premium.",
  "long-call":
    "Pay premium for upside. Loss capped at the premium; profit unlimited above breakeven.",
  "long-put":
    "Pay premium for downside protection or a bearish bet. Loss capped at premium.",
  "short-call":
    "Sell a call without owning the shares. You collect premium but the loss is unlimited above the strike — high risk.",
  "short-put":
    "Sell a put to collect premium. Same payoff as a cash-secured put but without setting cash aside.",
  "bull-call-spread":
    "Buy a lower-strike call, sell a higher-strike call. Defined risk and defined reward.",
  "bear-put-spread":
    "Buy a higher-strike put, sell a lower-strike put. Defined risk and defined reward.",
});

function currentValues() {
  const v = {};
  fieldsHost.querySelectorAll("input").forEach((el) => {
    v[el.dataset.key] = el.value;
  });
  return v;
}

function renderFields() {
  const id = strategySel.value;
  $("blurb").textContent = BLURBS[id] || "";
  let fields = STRATEGY_FIELDS[id] || [];
  if (usePricer.checked) {
    fields = fields.filter((f) => f !== "premium" && f !== "premium2");
  }
  const existing = currentValues();
  fieldsHost.innerHTML = "";
  for (let i = 0; i < fields.length; i += 2) {
    const row = document.createElement("div");
    row.className = "opt-field-row";
    fields.slice(i, i + 2).forEach((f) => {
      const label = document.createElement("label");
      label.className = "field inline";
      const span = document.createElement("span");
      span.className = "field-label";
      span.textContent = FIELD_LABELS[f];
      const input = document.createElement("input");
      input.className = "num";
      input.type = "number";
      input.step = "any";
      input.min = "0"; // strikes, premiums and prices are never negative
      input.inputMode = "decimal";
      input.dataset.key = f;
      input.value = existing[f] ?? DEFAULTS[f] ?? "";
      input.addEventListener("input", calculate);
      label.append(span, input);
      row.append(label);
    });
    fieldsHost.append(row);
  }
}

function collectPayload() {
  const payload = {
    strategy: strategySel.value,
    contracts: $("contracts").value,
    days: $("days").value,
    usePricer: usePricer.checked,
    spot: $("spot").value,
    ivPct: $("ivPct").value,
    ratePct: $("ratePct").value,
    divPct: $("divPct").value,
  };
  Object.assign(payload, currentValues());
  return payload;
}

const fmtCurrency = (v) => {
  if (v === null) return "Unlimited";
  if (!Number.isFinite(v)) return "—";
  const sign = v < 0 ? "-" : "";
  return (
    sign +
    "$" +
    Math.abs(v).toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })
  );
};
const fmtPct = (v) => (Number.isFinite(v) ? (v * 100).toFixed(2) + "%" : "—");

function metric(label, value, tone) {
  const cell = document.createElement("div");
  cell.className = "opt-metric";
  const l = document.createElement("span");
  l.className = "opt-metric-label";
  l.textContent = label;
  const val = document.createElement("span");
  val.className = "opt-metric-value " + (tone || "");
  val.textContent = value;
  cell.append(l, val);
  return cell;
}

function showError(msg) {
  const el = $("calc-error");
  el.textContent = msg;
  el.hidden = !msg;
}

async function calculate() {
  let res;
  try {
    res = await fetch("/api/calculate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectPayload()),
    });
  } catch (e) {
    showError("Couldn't reach the server — check your connection and try again.");
    return;
  }
  if (!res.ok) {
    showError("Check your inputs — that combination couldn't be priced.");
    return;
  }
  showError("");
  const data = await res.json();
  render(data);
}

function render(d) {
  // Headline
  const credit = d.netPremium;
  $("headline-label").textContent =
    credit >= 0 ? "Net premium collected" : "Net premium paid";
  const hv = $("headline-value");
  hv.textContent = fmtCurrency(Math.abs(credit));
  hv.className = "opt-headline-value " + (credit >= 0 ? "good" : "bad");

  // Core metrics
  const core = $("core-metrics");
  core.innerHTML = "";
  const be = d.breakevens.length
    ? d.breakevens.map((b) => "$" + b.toFixed(2)).join(", ")
    : "—";
  core.append(metric("Breakeven", be));
  core.append(
    metric("Max profit", d.maxProfit === null ? "Unlimited" : fmtCurrency(d.maxProfit), "good"),
  );
  core.append(
    metric("Max loss", d.maxLoss === null ? "Unlimited" : fmtCurrency(d.maxLoss), "bad"),
  );

  // Income metrics
  const inc = $("income-metrics");
  inc.innerHTML = "";
  if (d.incomeType === "coveredCall" && d.income) {
    const r = d.income;
    inc.append(metric("Premium collected", fmtCurrency(r.premium_collected), "good"));
    inc.append(metric("If unchanged", fmtCurrency(r.max_profit_if_unchanged)));
    inc.append(metric("If called away", fmtCurrency(r.max_profit_if_called), "good"));
    inc.append(metric("Static return", fmtPct(r.static_return)));
    inc.append(metric("Static annualized", fmtPct(r.static_return_annualized)));
    inc.append(metric("Return if called", fmtPct(r.return_if_called), "good"));
    inc.append(metric("Annualized (called)", fmtPct(r.return_if_called_annualized)));
    inc.append(metric("Downside protection", fmtPct(r.downside_protection)));
    // Cost basis is optional accounting detail — only shown when you supply it.
    if (r.net_cost_basis !== undefined) {
      inc.append(metric("Net cost basis", "$" + r.net_cost_basis.toFixed(2)));
      inc.append(metric("Total gain if called", fmtCurrency(r.total_gain_if_called)));
      inc.append(metric("Total return if called", fmtPct(r.total_return_if_called)));
    }
  } else if (d.incomeType === "cashSecuredPut" && d.income) {
    const r = d.income;
    inc.append(metric("Cash to secure", fmtCurrency(r.cash_secured)));
    inc.append(metric("Effective buy price", "$" + r.effective_buy_price.toFixed(2)));
    inc.append(metric("Return on cash", fmtPct(r.return_on_cash), "good"));
    inc.append(metric("Annualized", fmtPct(r.return_on_cash_annualized)));
  }

  // Estimator chips
  const chips = $("estimates");
  chips.innerHTML = "";
  if (d.usePricer) {
    d.legs.forEach((leg) => {
      const c = document.createElement("span");
      c.className = "opt-estimate-chip";
      c.innerHTML =
        `${leg.side === "short" ? "Sell" : "Buy"} ${leg.type} ${leg.strike}: ` +
        `<strong>$${leg.premium.toFixed(2)}</strong> · Δ ${leg.delta.toFixed(2)}`;
      chips.append(c);
    });
  }

  drawPayoff(d);
}

let lastPayoffData = null;

function drawPayoff(d, hoverX = null) {
  lastPayoffData = d;
  const canvas = $("payoff");
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth || 320;
  const cssH = 200;
  canvas.width = cssW * dpr;
  canvas.height = cssH * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);

  const pts = d.payoff;
  const lo = d.priceRange.lo;
  const hi = d.priceRange.hi;
  const pnls = pts.map((p) => p.pnl);
  let yMin = Math.min(...pnls, 0);
  let yMax = Math.max(...pnls, 0);
  if (yMin === yMax) {
    yMin -= 1;
    yMax += 1;
  }
  const pad = (yMax - yMin) * 0.12;
  yMin -= pad;
  yMax += pad;

  // Left gutter holds the P/L dollar labels so the chart is readable on both
  // axes, not just price.
  const padL = 52,
    padR = 10,
    padT = 12,
    padB = 22;
  const plotW = cssW - padL - padR;
  const plotH = cssH - padT - padB;
  const xFor = (price) => padL + ((price - lo) / (hi - lo)) * plotW;
  const yFor = (pnl) => padT + (1 - (pnl - yMin) / (yMax - yMin)) * plotH;

  // Y-axis P/L gridlines + labels (top = best case, bottom = worst case, 0).
  const yTicks = [yMax, (yMax + 0) / 2, 0, (yMin + 0) / 2, yMin].filter(
    (v, i, a) => a.indexOf(v) === i,
  );
  ctx.font = "10px system-ui, sans-serif";
  ctx.textBaseline = "middle";
  ctx.textAlign = "right";
  yTicks.forEach((v) => {
    const y = yFor(v);
    ctx.strokeStyle = v === 0 ? "#243140" : "#161f2a";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(padL, y);
    ctx.lineTo(cssW - padR, y);
    ctx.stroke();
    ctx.fillStyle = v > 0 ? "#5fd0a0" : v < 0 ? "#ff8a8a" : "#8499a8";
    ctx.fillText(fmtCompact(v), padL - 6, y);
  });
  const y0 = yFor(0);

  // Strike markers
  ctx.strokeStyle = "#1c2733";
  ctx.setLineDash([3, 3]);
  d.strikes.forEach((k) => {
    const x = xFor(k);
    ctx.beginPath();
    ctx.moveTo(x, padT);
    ctx.lineTo(x, cssH - padB);
    ctx.stroke();
  });
  ctx.setLineDash([]);

  const region = (positive, color) => {
    ctx.beginPath();
    ctx.moveTo(xFor(pts[0].price), y0);
    pts.forEach((p) => {
      const c = positive ? Math.max(p.pnl, 0) : Math.min(p.pnl, 0);
      ctx.lineTo(xFor(p.price), yFor(c));
    });
    ctx.lineTo(xFor(pts[pts.length - 1].price), y0);
    ctx.closePath();
    ctx.fillStyle = color;
    ctx.fill();
  };
  region(true, "rgba(95, 208, 160, 0.16)");
  region(false, "rgba(255, 110, 110, 0.14)");

  // Curve
  ctx.strokeStyle = "#5fb0ff";
  ctx.lineWidth = 2;
  ctx.beginPath();
  pts.forEach((p, i) => {
    const x = xFor(p.price);
    const y = yFor(p.pnl);
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.stroke();

  // Breakeven markers: where the trade crosses $0, the prices that actually
  // matter. Drawn on top of the curve with a dot + price label.
  (d.breakevens || []).forEach((b) => {
    if (b < lo || b > hi) return;
    const x = xFor(b);
    ctx.strokeStyle = "rgba(255, 209, 102, 0.7)";
    ctx.setLineDash([2, 2]);
    ctx.beginPath();
    ctx.moveTo(x, padT);
    ctx.lineTo(x, cssH - padB);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "#ffd166";
    ctx.beginPath();
    ctx.arc(x, y0, 3, 0, Math.PI * 2);
    ctx.fill();
  });

  // X-axis labels
  ctx.fillStyle = "#8499a8";
  ctx.font = "11px system-ui, sans-serif";
  ctx.textBaseline = "top";
  ctx.textAlign = "left";
  ctx.fillText("$" + lo.toFixed(0), padL, cssH - padB + 5);
  ctx.textAlign = "right";
  ctx.fillText("$" + hi.toFixed(0), cssW - padR, cssH - padB + 5);
  ctx.textAlign = "center";
  d.strikes.forEach((k) => ctx.fillText(String(k), xFor(k), cssH - padB + 5));

  // Hover crosshair: read the exact P/L at any underlying price.
  if (hoverX !== null) {
    const cx = Math.max(padL, Math.min(cssW - padR, hoverX));
    const price = lo + ((cx - padL) / plotW) * (hi - lo);
    const pnl = interpPnl(pts, price);
    const cy = yFor(pnl);

    ctx.strokeStyle = "rgba(132, 153, 168, 0.5)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(cx, padT);
    ctx.lineTo(cx, cssH - padB);
    ctx.stroke();

    ctx.fillStyle = pnl >= 0 ? "#5fd0a0" : "#ff8a8a";
    ctx.beginPath();
    ctx.arc(cx, cy, 3.5, 0, Math.PI * 2);
    ctx.fill();

    // Tooltip box, flipped to whichever side has room.
    const label = "$" + price.toFixed(2) + "  •  " + fmtCompact(pnl);
    ctx.font = "11px system-ui, sans-serif";
    const tw = ctx.measureText(label).width + 12;
    const th = 18;
    let bx = cx + 8;
    if (bx + tw > cssW - padR) bx = cx - 8 - tw;
    const by = padT + 2;
    ctx.fillStyle = "rgba(12, 18, 25, 0.92)";
    ctx.strokeStyle = "#243140";
    ctx.beginPath();
    ctx.rect(bx, by, tw, th);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = "#e8eef4";
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    ctx.fillText(label, bx + 6, by + th / 2);
  }
}

// Linear-interpolate the payoff curve's P/L at an arbitrary price.
function interpPnl(pts, price) {
  if (price <= pts[0].price) return pts[0].pnl;
  if (price >= pts[pts.length - 1].price) return pts[pts.length - 1].pnl;
  for (let i = 1; i < pts.length; i++) {
    if (price <= pts[i].price) {
      const a = pts[i - 1];
      const b = pts[i];
      const t = (price - a.price) / (b.price - a.price || 1);
      return a.pnl + t * (b.pnl - a.pnl);
    }
  }
  return pts[pts.length - 1].pnl;
}

// Compact dollar formatting for axis ticks: $1.2k, -$450, $0.
function fmtCompact(v) {
  const sign = v < 0 ? "-" : "";
  const a = Math.abs(v);
  if (a >= 1000) return sign + "$" + (a / 1000).toFixed(a >= 10000 ? 0 : 1) + "k";
  return sign + "$" + Math.round(a);
}

// Wire up
initStrategyMeta();
strategySel.addEventListener("change", () => {
  renderFields();
  calculate();
});
usePricer.addEventListener("change", () => {
  $("pricer").hidden = !usePricer.checked;
  renderFields();
  calculate();
});
["contracts", "days", "spot", "ivPct", "ratePct", "divPct"].forEach((id) =>
  $(id).addEventListener("input", calculate),
);
window.addEventListener("resize", calculate);

// Hover/touch the payoff chart to read the exact P/L at any price.
(function wirePayoffHover() {
  const canvas = $("payoff");
  const at = (e) => {
    const rect = canvas.getBoundingClientRect();
    const clientX = e.touches ? e.touches[0].clientX : e.clientX;
    return clientX - rect.left;
  };
  const move = (e) => {
    if (!lastPayoffData) return;
    if (e.cancelable && e.touches) e.preventDefault();
    drawPayoff(lastPayoffData, at(e));
  };
  const clear = () => lastPayoffData && drawPayoff(lastPayoffData, null);
  canvas.addEventListener("mousemove", move);
  canvas.addEventListener("mouseleave", clear);
  canvas.addEventListener("touchstart", move, { passive: false });
  canvas.addEventListener("touchmove", move, { passive: false });
  canvas.addEventListener("touchend", clear);
})();

$("pricer").hidden = !usePricer.checked;
renderFields();
calculate();
