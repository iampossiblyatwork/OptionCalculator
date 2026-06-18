(function (root, factory) {
  const api = factory(root.BS || (typeof require !== "undefined" ? require("./bs.js") : null));
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Playground = api;
})(typeof window !== "undefined" ? window : globalThis, function (BS) {

  const GREEK_MEANING = {
    Delta: "$ change in premium per $1 move in the stock",
    Gamma: "how fast Delta changes per $1 move — peaks at-the-money",
    Theta: "$ the premium decays each day, all else equal",
    Vega: "$ change in premium per 1-point move in IV",
    Rho: "$ change in premium per 1-point move in interest rates",
  };

  function readInputs(v) {
    return {
      type: v.type,
      spot: Number(v.spot),
      strike: Number(v.strike),
      daysToExpiration: Number(v.days),
      volatility: Number(v.iv) / 100,
      riskFreeRate: Number(v.rate) / 100,
      dividendYield: Number(v.div) / 100,
    };
  }

  const usd = (n) => (n < 0 ? "-$" : "$") + Math.abs(n).toFixed(2);

  function formatPrice(r) { return usd(r.price); }

  function formatGreeks(r) {
    return [
      { name: "Delta", value: r.delta.toFixed(4) },
      { name: "Gamma", value: r.gamma.toFixed(4) },
      { name: "Theta", value: usd(r.theta) + "/day" },
      { name: "Vega", value: usd(r.vega) },
      { name: "Rho", value: usd(r.rho) },
    ].map((c) => ({ ...c, meaning: GREEK_MEANING[c.name] }));
  }

  function formatProb(r) {
    return (r.probItm * 100).toFixed(1) + "% chance of finishing in-the-money "
      + `(d1=${r.d1.toFixed(3)}, d2=${r.d2.toFixed(3)})`;
  }

  function wire(doc) {
    const ids = ["type", "spot", "strike", "days", "iv", "rate", "div"];
    const read = () => Object.fromEntries(ids.map((id) => [id, doc.getElementById(id).value]));

    function update() {
      const raw = read();
      ids.filter((i) => i !== "type").forEach((id) => {
        const out = doc.getElementById(id + "-val");
        if (out) out.textContent = raw[id];
      });
      const r = BS.blackScholes(readInputs(raw));
      doc.getElementById("price-out").textContent = "Premium: " + formatPrice(r);
      doc.getElementById("prob-out").textContent = formatProb(r);
      doc.getElementById("greeks-out").innerHTML = formatGreeks(r)
        .map((c) => `<div class="greek"><strong>${c.name}</strong> ${c.value}`
          + `<span class="meaning">${c.meaning}</span></div>`).join("");
      drawSweep(doc, raw);
    }

    ids.forEach((id) => doc.getElementById(id).addEventListener("input", update));
    ["sweep-var", "sweep-metric"].forEach((id) => {
      const el = doc.getElementById(id);
      if (el) el.addEventListener("change", update);
    });
    update();
  }

  const RANGES = { spot: [1, 300], strike: [1, 300], days: [1, 730],
    iv: [1, 200], rate: [0, 15], div: [0, 15] };

  function sweep({ raw, variable, metric, steps = 60 }) {
    const [lo, hi] = RANGES[variable];
    const pts = [];
    for (let i = 0; i <= steps; i++) {
      const x = lo + (hi - lo) * i / steps;
      const r = BS.blackScholes(readInputs({ ...raw, [variable]: x }));
      pts.push({ x, y: r[metric] });
    }
    return pts;
  }

  function drawSweep(doc, raw) {
    const canvas = doc.getElementById("sweep-chart");
    if (!canvas || !canvas.getContext) return;
    const variable = doc.getElementById("sweep-var").value;
    const metric = doc.getElementById("sweep-metric").value;
    const pts = sweep({ raw, variable, metric });
    const ctx = canvas.getContext("2d");
    const W = canvas.width, H = canvas.height, pad = 36;
    ctx.clearRect(0, 0, W, H);
    const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
    const xMin = Math.min(...xs), xMax = Math.max(...xs);
    const yMin = Math.min(...ys), yMax = Math.max(...ys);
    const sx = (x) => pad + (W - 2 * pad) * (x - xMin) / (xMax - xMin || 1);
    const sy = (y) => H - pad - (H - 2 * pad) * (y - yMin) / (yMax - yMin || 1);
    ctx.strokeStyle = "#888"; ctx.beginPath();
    ctx.moveTo(pad, H - pad); ctx.lineTo(W - pad, H - pad);
    ctx.moveTo(pad, pad); ctx.lineTo(pad, H - pad); ctx.stroke();
    ctx.strokeStyle = "#2b8a3e"; ctx.lineWidth = 2; ctx.beginPath();
    pts.forEach((p, i) => (i ? ctx.lineTo(sx(p.x), sy(p.y)) : ctx.moveTo(sx(p.x), sy(p.y))));
    ctx.stroke();
    ctx.fillStyle = "#444"; ctx.font = "12px system-ui";
    ctx.fillText(`${metric} vs ${variable}`, pad, pad - 12);
  }

  if (typeof document !== "undefined") {
    document.addEventListener("DOMContentLoaded", () => wire(document));
  }

  return { readInputs, formatPrice, formatGreeks, formatProb, wire, sweep, drawSweep };
});
