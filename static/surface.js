"use strict";

// 3D profit/loss surface for the current position: P/L plotted over the
// underlying price (one axis) and days-to-expiration (the other), valued with
// Black–Scholes so it shows the whole pre-expiration landscape, not just the
// payoff at T=0. The front edge (0 days left) is exactly the 2D payoff curve;
// the surface behind it is time value bleeding away via theta.
//
// Rendered on a plain 2D canvas with an orthographic projection + painter's
// algorithm. Drag to rotate. Depends on window.BS (bs.js).
(function (root) {
  const BS = root.BS;
  const NX = 34; // price samples
  const NT = 22; // time samples

  // Camera angles (radians). Tuned so price runs roughly left→right and time
  // recedes back-and-up.
  const view = { az: -0.62, el: 0.5 };

  let state = null; // { ctx, grid, geom }

  // P/L of the whole position at a given underlying price with `daysLeft` to go.
  function positionPnl(ctx, price, daysLeft) {
    let pnl = 0;
    for (const leg of ctx.legs) {
      const mark = BS.blackScholes({
        type: leg.type,
        spot: price,
        strike: leg.strike,
        daysToExpiration: daysLeft,
        volatility: ctx.iv,
        riskFreeRate: ctx.rate,
        dividendYield: ctx.div,
      }).price;
      const per = leg.side === "long" ? mark - leg.premium : leg.premium - mark;
      pnl += per * leg.contracts * 100;
    }
    if (ctx.stock) pnl += (price - ctx.stock.costBasis) * ctx.stock.shares;
    return pnl;
  }

  function computeGrid(ctx) {
    const { priceLo: lo, priceHi: hi } = ctx;
    const maxDays = Math.max(1, ctx.maxDays);
    const prices = Array.from({ length: NX }, (_, i) => lo + ((hi - lo) * i) / (NX - 1));
    // j = 0 is expiration (front edge); j = NT-1 is today (maxDays out).
    const days = Array.from({ length: NT }, (_, j) => (maxDays * j) / (NT - 1));
    const z = [];
    let zMin = Infinity;
    let zMax = -Infinity;
    for (let j = 0; j < NT; j++) {
      const row = [];
      for (let i = 0; i < NX; i++) {
        const p = positionPnl(ctx, prices[i], days[j]);
        row.push(p);
        if (p < zMin) zMin = p;
        if (p > zMax) zMax = p;
      }
      z.push(row);
    }
    const zAbs = Math.max(Math.abs(zMin), Math.abs(zMax), 1e-9);
    return { prices, days, z, zMin, zMax, zAbs, maxDays };
  }

  // Orthographic projector: world (x,y,z) centered near origin -> screen.
  function makeProjector(scale, cx, cy) {
    const ca = Math.cos(view.az), sa = Math.sin(view.az);
    const ce = Math.cos(view.el), se = Math.sin(view.el);
    return (x, y, z) => {
      const x1 = x * ca - y * sa;
      const y1 = x * sa + y * ca;
      const y2 = y1 * ce - z * se;
      const depth = y1 * se + z * ce; // larger = nearer the camera
      return { sx: cx + x1 * scale, sy: cy - y2 * scale, depth };
    };
  }

  function colorFor(pnl, zAbs) {
    const t = Math.max(-1, Math.min(1, pnl / zAbs));
    const a = (0.28 + 0.5 * Math.abs(t)).toFixed(3);
    return t >= 0 ? `rgba(95, 208, 160, ${a})` : `rgba(255, 110, 110, ${a})`;
  }

  function draw() {
    if (!state) return;
    const { ctx: data, grid } = state;
    const canvas = document.getElementById("surface");
    if (!canvas || !canvas.getContext) return;
    const g = canvas.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    const cssW = canvas.clientWidth || 320;
    const cssH = 300;
    canvas.width = cssW * dpr;
    canvas.height = cssH * dpr;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, cssW, cssH);

    const scale = Math.min(cssW, cssH) * 0.58;
    const project = makeProjector(scale, cssW / 2, cssH * 0.54);

    // World coords: x from price index, y from time index, z from P/L height.
    const wx = (i) => i / (NX - 1) - 0.5;
    const wy = (j) => j / (NT - 1) - 0.5;
    const wz = (pnl) => (pnl / grid.zAbs) * 0.42;

    const pt = (i, j) => project(wx(i), wy(j), wz(grid.z[j][i]));

    // Build quads with average depth for painter's algorithm.
    const quads = [];
    for (let j = 0; j < NT - 1; j++) {
      for (let i = 0; i < NX - 1; i++) {
        const a = pt(i, j), b = pt(i + 1, j), c = pt(i + 1, j + 1), d = pt(i, j + 1);
        const avgPnl =
          (grid.z[j][i] + grid.z[j][i + 1] + grid.z[j + 1][i + 1] + grid.z[j + 1][i]) / 4;
        quads.push({ a, b, c, d, depth: (a.depth + b.depth + c.depth + d.depth) / 4, avgPnl });
      }
    }
    quads.sort((p, q) => p.depth - q.depth); // far (small depth) first

    g.lineWidth = 0.5;
    g.strokeStyle = "rgba(20, 30, 42, 0.55)";
    quads.forEach((q) => {
      g.beginPath();
      g.moveTo(q.a.sx, q.a.sy);
      g.lineTo(q.b.sx, q.b.sy);
      g.lineTo(q.c.sx, q.c.sy);
      g.lineTo(q.d.sx, q.d.sy);
      g.closePath();
      g.fillStyle = colorFor(q.avgPnl, grid.zAbs);
      g.fill();
      g.stroke();
    });

    // Breakeven (P/L = 0) reference plane edge along the surface base.
    drawZeroPlane(g, project, wx, wy);

    // Front edge = the at-expiration payoff curve (j = 0). Highlight it.
    g.strokeStyle = "#5fb0ff";
    g.lineWidth = 2;
    g.beginPath();
    for (let i = 0; i < NX; i++) {
      const s = pt(i, 0);
      i === 0 ? g.moveTo(s.sx, s.sy) : g.lineTo(s.sx, s.sy);
    }
    g.stroke();

    drawLabels(g, project, wx, wy, data, grid);
  }

  // A faint quad showing the z = 0 (breakeven) plane the surface is measured
  // against, so the green/red split has a visible reference.
  function drawZeroPlane(g, project, wx, wy) {
    const corners = [
      project(wx(0), wy(0), 0),
      project(wx(NX - 1), wy(0), 0),
      project(wx(NX - 1), wy(NT - 1), 0),
      project(wx(0), wy(NT - 1), 0),
    ];
    g.beginPath();
    g.moveTo(corners[0].sx, corners[0].sy);
    corners.slice(1).forEach((c) => g.lineTo(c.sx, c.sy));
    g.closePath();
    g.fillStyle = "rgba(132, 153, 168, 0.06)";
    g.strokeStyle = "rgba(132, 153, 168, 0.35)";
    g.lineWidth = 1;
    g.fill();
    g.stroke();
  }

  function drawLabels(g, project, wx, wy, data, grid) {
    g.fillStyle = "#8499a8";
    g.font = "10px system-ui, sans-serif";

    // Price axis: front edge, two ends.
    const pL = project(wx(0), wy(0), 0);
    const pR = project(wx(NX - 1), wy(0), 0);
    g.textBaseline = "top";
    g.textAlign = "center";
    g.fillText("$" + data.priceLo.toFixed(0), pL.sx, pL.sy + 4);
    g.fillText("$" + data.priceHi.toFixed(0), pR.sx, pR.sy + 4);
    g.fillText("price →", (pL.sx + pR.sx) / 2, Math.max(pL.sy, pR.sy) + 16);

    // Time axis: along the right side, front (0d) to back (maxDays).
    const tFront = project(wx(NX - 1), wy(0), 0);
    const tBack = project(wx(NX - 1), wy(NT - 1), 0);
    g.textAlign = "left";
    g.textBaseline = "middle";
    g.fillText("0d", tFront.sx + 6, tFront.sy);
    g.fillText(Math.round(grid.maxDays) + "d", tBack.sx + 6, tBack.sy);
  }

  // Public: recompute from a fresh position context and redraw.
  function update(ctx) {
    if (!BS || !ctx || !ctx.legs || !ctx.legs.length) return;
    state = { ctx, grid: computeGrid(ctx) };
    draw();
  }

  function wire() {
    const canvas = document.getElementById("surface");
    if (!canvas) return;
    let dragging = false;
    let lastX = 0, lastY = 0;
    const down = (e) => {
      dragging = true;
      const p = e.touches ? e.touches[0] : e;
      lastX = p.clientX;
      lastY = p.clientY;
      if (e.cancelable && e.touches) e.preventDefault();
    };
    const move = (e) => {
      if (!dragging) return;
      const p = e.touches ? e.touches[0] : e;
      view.az += (p.clientX - lastX) * 0.01;
      view.el = Math.max(0.12, Math.min(1.35, view.el - (p.clientY - lastY) * 0.008));
      lastX = p.clientX;
      lastY = p.clientY;
      if (e.cancelable && e.touches) e.preventDefault();
      draw();
    };
    const up = () => (dragging = false);
    canvas.addEventListener("mousedown", down);
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
    canvas.addEventListener("touchstart", down, { passive: false });
    canvas.addEventListener("touchmove", move, { passive: false });
    canvas.addEventListener("touchend", up);
    window.addEventListener("resize", draw);
  }

  if (typeof document !== "undefined") {
    document.addEventListener("DOMContentLoaded", wire);
  }

  const api = { update, computeGrid, positionPnl };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Surface = api;
})(typeof window !== "undefined" ? window : globalThis);
