# Options Learning Playground Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an interactive Black–Scholes playground where moving sliders for spot/strike/time/IV/rate/dividend updates the premium and all five Greeks live, teaching the user how each input moves the price.

**Architecture:** Python `black_scholes()` stays the canonical, tested math engine and gains a few teaching outputs (d1, d2, N(d2), prob-ITM, moneyness). A faithful JS twin (`static/bs.js`) drives the sliders with zero latency; a Node parity test asserts JS agrees with Python across a generated grid. A new `/playground` page wires sliders to the JS twin. The existing strategy calculator flips to BS-on by default.

**Tech Stack:** Python 3.12, Flask 3, vanilla JS (no framework), HTML canvas, Node 22 built-in `node:test` (no npm installs), pytest.

## Global Constraints

- Python: `Flask>=3.0,<4.0`, `gunicorn>=21.2` — no new runtime deps.
- JS: no browser dependencies, no npm packages; tests use Node's built-in `node:test`/`node:assert` only.
- One contract = 100 shares (`SHARES_PER_CONTRACT = 100`); year = 365 days (`DAYS_PER_YEAR = 365`).
- BS conventions are fixed and must match between Python and JS: theta is **per calendar day**, vega and rho are **per 1% (1 point) move**. Volatility/rate/dividend are decimals internally (0.30 = 30%).
- European options only; no early exercise. State this in the playground UI.
- All money in USD.
- Existing 18 pytest cases must stay green (except the documented manual-premium test update in Task 6).

---

### Task 1: Extend Python Black–Scholes with teaching outputs

**Files:**
- Modify: `options.py:255-320` (`black_scholes` return dicts — both the degenerate branch and the main branch)
- Test: `test_options.py` (append new tests)

**Interfaces:**
- Consumes: existing `black_scholes(*, type, spot, strike, days_to_expiration, volatility, risk_free_rate=0.04, dividend_yield=0.0) -> dict` and `norm_cdf(x)`.
- Produces: `black_scholes(...)` returns the same dict **plus** keys `d1`, `d2`, `n_d1`, `n_d2`, `prob_itm`, `moneyness` (all `float`). `prob_itm` = N(d2) for calls, N(−d2) for puts. `moneyness` = spot/strike. In the degenerate branch (T≤0, σ≤0, S≤0, K≤0) these are: `d1=d2=0.0`, `n_d1=n_d2=0.0`, `prob_itm` = 1.0 if currently ITM else 0.0, `moneyness` = spot/strike if strike>0 else 0.0.

- [ ] **Step 1: Write the failing test**

Append to `test_options.py`:

```python
def test_black_scholes_teaching_outputs():
    r = opt.black_scholes(
        type="call", spot=100, strike=100, days_to_expiration=365,
        volatility=0.2, risk_free_rate=0.05,
    )
    # d1, d2 for ATM 1y 20% vol 5% rate (known values)
    assert r["d1"] == pytest.approx(0.35, abs=0.01)
    assert r["d2"] == pytest.approx(0.15, abs=0.01)
    assert r["n_d1"] == pytest.approx(opt.norm_cdf(r["d1"]), abs=1e-9)
    assert r["n_d2"] == pytest.approx(opt.norm_cdf(r["d2"]), abs=1e-9)
    # Call prob-ITM is N(d2); put prob-ITM is N(-d2); they sum to 1.
    p = opt.black_scholes(
        type="put", spot=100, strike=100, days_to_expiration=365,
        volatility=0.2, risk_free_rate=0.05,
    )
    assert r["prob_itm"] == pytest.approx(r["n_d2"], abs=1e-9)
    assert r["prob_itm"] + p["prob_itm"] == pytest.approx(1.0, abs=1e-9)
    assert r["moneyness"] == pytest.approx(1.0)


def test_black_scholes_teaching_outputs_degenerate():
    r = opt.black_scholes(
        type="call", spot=110, strike=100, days_to_expiration=0, volatility=0.2,
    )
    assert r["d1"] == 0.0 and r["d2"] == 0.0
    assert r["prob_itm"] == 1.0          # currently in-the-money
    assert r["moneyness"] == pytest.approx(1.1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test_options.py::test_black_scholes_teaching_outputs test_options.py::test_black_scholes_teaching_outputs_degenerate -v`
Expected: FAIL with `KeyError: 'd1'`.

- [ ] **Step 3: Write minimal implementation**

In `options.py`, in the degenerate branch (currently returns the dict at lines ~276-283), add the new keys:

```python
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        price = intrinsic(type, K, S)
        itm = (S > K) if type == "call" else (S < K)
        return {
            "price": price,
            "delta": (1.0 if type == "call" else -1.0) if itm else 0.0,
            "gamma": 0.0,
            "theta": 0.0,
            "vega": 0.0,
            "rho": 0.0,
            "d1": 0.0,
            "d2": 0.0,
            "n_d1": 0.0,
            "n_d2": 0.0,
            "prob_itm": 1.0 if itm else 0.0,
            "moneyness": (S / K) if K > 0 else 0.0,
        }
```

In the main branch, just before the final `return {...}` (currently lines ~313-320), compute prob-ITM and extend the dict:

```python
    prob_itm = norm_cdf(d2) if type == "call" else norm_cdf(-d2)

    return {
        "price": price,
        "delta": delta,
        "gamma": gamma,
        "theta": theta,
        "vega": vega,
        "rho": rho,
        "d1": d1,
        "d2": d2,
        "n_d1": norm_cdf(d1),
        "n_d2": norm_cdf(d2),
        "prob_itm": prob_itm,
        "moneyness": S / K,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest test_options.py -v`
Expected: all PASS (the 2 new tests plus the existing 18).

- [ ] **Step 5: Commit**

```bash
git add options.py test_options.py
git commit -m "feat: add d1/d2/prob-ITM/moneyness teaching outputs to black_scholes"
```

---

### Task 2: JS Black–Scholes twin + Python↔JS parity test

**Files:**
- Create: `static/bs.js`
- Create: `tests/gen_bs_fixture.py`
- Create: `tests/fixtures/bs_parity.json` (generated — committed so the Node test is self-contained)
- Create: `tests/bs_parity.test.js`

**Interfaces:**
- Consumes: Python `opt.black_scholes(...)` (Task 1) for fixture generation.
- Produces: a global/CommonJS function `blackScholes({type, spot, strike, daysToExpiration, volatility, riskFreeRate, dividendYield})` returning `{price, delta, gamma, theta, vega, rho, d1, d2, nD1, nD2, probItm, moneyness}`. Note JS uses camelCase keys (`nD1`, `nD2`, `probItm`); the fixture maps Python snake_case → JS camelCase. `bs.js` also exports `normCdf(x)` and `erf(x)`.

- [ ] **Step 1: Write the JS twin**

Create `static/bs.js`:

```javascript
// Black–Scholes twin of options.py:black_scholes — keep formulas in sync.
// Conventions: theta per calendar day; vega & rho per 1% move; rates/vol as decimals.
(function (root) {
  const DAYS_PER_YEAR = 365;

  // Abramowitz & Stegun 7.1.26 — max abs error ~1.5e-7, ample for parity.
  function erf(x) {
    const sign = x < 0 ? -1 : 1;
    x = Math.abs(x);
    const a1 = 0.254829592, a2 = -0.284496736, a3 = 1.421413741;
    const a4 = -1.453152027, a5 = 1.061405429, p = 0.3275911;
    const t = 1 / (1 + p * x);
    const y = 1 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * Math.exp(-x * x);
    return sign * y;
  }

  function normCdf(x) { return 0.5 * (1 + erf(x / Math.SQRT2)); }
  function normPdf(x) { return 0.3989422804014327 * Math.exp(-x * x / 2); }
  function intrinsic(type, strike, price) {
    return type === "call" ? Math.max(price - strike, 0) : Math.max(strike - price, 0);
  }

  function blackScholes({ type, spot, strike, daysToExpiration, volatility,
                          riskFreeRate = 0.04, dividendYield = 0 }) {
    const r = riskFreeRate, q = dividendYield, S = spot, K = strike;
    const T = daysToExpiration / DAYS_PER_YEAR, sigma = volatility;

    if (T <= 0 || sigma <= 0 || S <= 0 || K <= 0) {
      const price = intrinsic(type, K, S);
      const itm = type === "call" ? S > K : S < K;
      return {
        price, delta: itm ? (type === "call" ? 1 : -1) : 0,
        gamma: 0, theta: 0, vega: 0, rho: 0,
        d1: 0, d2: 0, nD1: 0, nD2: 0,
        probItm: itm ? 1 : 0, moneyness: K > 0 ? S / K : 0,
      };
    }

    const sqrtT = Math.sqrt(T);
    const d1 = (Math.log(S / K) + (r - q + sigma * sigma / 2) * T) / (sigma * sqrtT);
    const d2 = d1 - sigma * sqrtT;
    const discR = Math.exp(-r * T), discQ = Math.exp(-q * T);

    let price, delta, rho, theta;
    if (type === "call") {
      price = S * discQ * normCdf(d1) - K * discR * normCdf(d2);
      delta = discQ * normCdf(d1);
      rho = K * T * discR * normCdf(d2) / 100;
      theta = (-(S * discQ * normPdf(d1) * sigma) / (2 * sqrtT)
               - r * K * discR * normCdf(d2)
               + q * S * discQ * normCdf(d1)) / DAYS_PER_YEAR;
    } else {
      price = K * discR * normCdf(-d2) - S * discQ * normCdf(-d1);
      delta = discQ * (normCdf(d1) - 1);
      rho = -K * T * discR * normCdf(-d2) / 100;
      theta = (-(S * discQ * normPdf(d1) * sigma) / (2 * sqrtT)
               + r * K * discR * normCdf(-d2)
               - q * S * discQ * normCdf(-d1)) / DAYS_PER_YEAR;
    }
    const gamma = discQ * normPdf(d1) / (S * sigma * sqrtT);
    const vega = S * discQ * normPdf(d1) * sqrtT / 100;
    const probItm = type === "call" ? normCdf(d2) : normCdf(-d2);

    return { price, delta, gamma, theta, vega, rho, d1, d2,
             nD1: normCdf(d1), nD2: normCdf(d2), probItm, moneyness: S / K };
  }

  const api = { blackScholes, normCdf, erf };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else { root.BS = api; }
})(typeof window !== "undefined" ? window : globalThis);
```

- [ ] **Step 2: Write the fixture generator**

Create `tests/gen_bs_fixture.py`:

```python
"""Generate the Python↔JS parity grid. Run: python tests/gen_bs_fixture.py"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import options as opt

GRID = []
for typ in ("call", "put"):
    for spot in (50, 90, 100, 110, 150):
        for strike in (80, 100, 120):
            for days in (1, 30, 180, 365):
                for ivpct in (10, 30, 80):
                    for ratepct in (0, 4):
                        for divpct in (0, 3):
                            inp = dict(type=typ, spot=spot, strike=strike,
                                       days_to_expiration=days,
                                       volatility=ivpct / 100,
                                       risk_free_rate=ratepct / 100,
                                       dividend_yield=divpct / 100)
                            out = opt.black_scholes(**inp)
                            GRID.append({"input": inp, "expected": out})

path = os.path.join(os.path.dirname(__file__), "fixtures", "bs_parity.json")
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "w") as f:
    json.dump(GRID, f, indent=2)
print(f"wrote {len(GRID)} cases to {path}")
```

- [ ] **Step 3: Generate the fixture**

Run: `python tests/gen_bs_fixture.py`
Expected: `wrote 720 cases to .../tests/fixtures/bs_parity.json` and the file exists.

- [ ] **Step 4: Write the Node parity test**

Create `tests/bs_parity.test.js`:

```javascript
const { test } = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const { blackScholes } = require("../static/bs.js");

const grid = JSON.parse(
  fs.readFileSync(path.join(__dirname, "fixtures", "bs_parity.json"), "utf8")
);

// Python snake_case -> JS camelCase
const KEY = { price: "price", delta: "delta", gamma: "gamma", theta: "theta",
  vega: "vega", rho: "rho", d1: "d1", d2: "d2", n_d1: "nD1", n_d2: "nD2",
  prob_itm: "probItm", moneyness: "moneyness" };

test("JS Black-Scholes matches Python across the grid", () => {
  for (const { input, expected } of grid) {
    const got = blackScholes({
      type: input.type, spot: input.spot, strike: input.strike,
      daysToExpiration: input.days_to_expiration, volatility: input.volatility,
      riskFreeRate: input.risk_free_rate, dividendYield: input.dividend_yield,
    });
    for (const [pyKey, jsKey] of Object.entries(KEY)) {
      const tol = pyKey === "price" ? 1e-3 : 1e-4;
      assert.ok(Math.abs(got[jsKey] - expected[pyKey]) <= tol,
        `${jsKey} mismatch for ${JSON.stringify(input)}: ` +
        `js=${got[jsKey]} py=${expected[pyKey]}`);
    }
  }
});
```

- [ ] **Step 5: Run the parity test (and confirm it can fail)**

Run: `node --test tests/`
Expected: PASS, `1 passing`.
Sanity-check the guard works: temporarily change `a1 = 0.254829592` to `0.25` in `bs.js`, re-run, confirm it FAILS, then revert.

- [ ] **Step 6: Commit**

```bash
git add static/bs.js tests/gen_bs_fixture.py tests/fixtures/bs_parity.json tests/bs_parity.test.js
git commit -m "feat: add JS Black-Scholes twin with Python parity test"
```

---

### Task 3: Playground route + page skeleton

**Files:**
- Modify: `app.py` (add route near the `/` route, ~line 126)
- Create: `templates/playground.html`
- Test: `test_options.py` (append a route test)

**Interfaces:**
- Consumes: Flask `app` and `render_template` (already imported in `app.py`).
- Produces: `GET /playground` returns 200 HTML containing the slider controls (ids `spot`, `strike`, `days`, `iv`, `rate`, `div`), a `type` toggle, output containers (ids `price-out`, `greeks-out`, `prob-out`), a `<canvas id="sweep-chart">`, and `<script src="/static/bs.js">` + `<script src="/static/playground.js">`.

- [ ] **Step 1: Write the failing test**

Append to `test_options.py`:

```python
def test_playground_serves_html(client):
    resp = client.get("/playground")
    assert resp.status_code == 200
    body = resp.data
    for token in (b'id="spot"', b'id="strike"', b'id="iv"', b'id="days"',
                  b'id="sweep-chart"', b'bs.js', b'playground.js'):
        assert token in body
    assert b"European" in body  # early-exercise disclaimer
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test_options.py::test_playground_serves_html -v`
Expected: FAIL with 404.

- [ ] **Step 3: Add the route**

In `app.py`, after the existing `@app.get("/")` handler, add:

```python
@app.get("/playground")
def playground():
    return render_template("playground.html")
```

- [ ] **Step 4: Create the template**

Create `templates/playground.html`:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Options Learning Playground</title>
  <link rel="stylesheet" href="/static/style.css" />
</head>
<body>
  <main class="playground">
    <h1>Options Learning Playground</h1>
    <p class="note">European Black–Scholes pricing — no early exercise. Theoretical estimate only.</p>

    <section class="controls">
      <label>Type
        <select id="type"><option value="call">Call</option><option value="put">Put</option></select>
      </label>
      <label>Spot <input type="range" id="spot" min="1" max="300" step="1" value="100"><output id="spot-val">100</output></label>
      <label>Strike <input type="range" id="strike" min="1" max="300" step="1" value="100"><output id="strike-val">100</output></label>
      <label>Days to expiry <input type="range" id="days" min="1" max="730" step="1" value="30"><output id="days-val">30</output></label>
      <label>IV % <input type="range" id="iv" min="1" max="200" step="1" value="30"><output id="iv-val">30</output></label>
      <label>Risk-free % <input type="range" id="rate" min="0" max="15" step="0.1" value="4"><output id="rate-val">4</output></label>
      <label>Dividend % <input type="range" id="div" min="0" max="15" step="0.1" value="0"><output id="div-val">0</output></label>
    </section>

    <section class="outputs">
      <div id="price-out" class="price"></div>
      <div id="prob-out" class="prob"></div>
      <div id="greeks-out" class="greeks"></div>
    </section>

    <section class="sweep">
      <label>Sweep variable
        <select id="sweep-var">
          <option value="spot">Spot</option><option value="iv">IV</option>
          <option value="days">Days</option><option value="rate">Rate</option>
        </select>
      </label>
      <label>Plot
        <select id="sweep-metric">
          <option value="price">Premium</option><option value="delta">Delta</option>
          <option value="gamma">Gamma</option><option value="theta">Theta</option>
          <option value="vega">Vega</option>
        </select>
      </label>
      <canvas id="sweep-chart" width="640" height="320"></canvas>
    </section>
  </main>
  <script src="/static/bs.js"></script>
  <script src="/static/playground.js"></script>
</body>
</html>
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `pytest test_options.py::test_playground_serves_html -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app.py templates/playground.html test_options.py
git commit -m "feat: add /playground route and page skeleton"
```

---

### Task 4: Slider wiring — live premium, Greeks, prob-ITM

**Files:**
- Create: `static/playground.js`
- Create: `tests/playground_format.test.js`

**Interfaces:**
- Consumes: `window.BS.blackScholes(...)` (Task 2).
- Produces: pure, exported helpers `readInputs(values)` → BS input object, `formatPrice(result)` → string, `formatGreeks(result)` → array of `{name, value, meaning}`, `formatProb(result)` → string. `playground.js` exports these via CommonJS when `module` exists (for the Node test) and wires DOM listeners only when `document` exists.

- [ ] **Step 1: Write the failing test**

Create `tests/playground_format.test.js`:

```javascript
const { test } = require("node:test");
const assert = require("node:assert");
const { formatGreeks, formatProb, readInputs } = require("../static/playground.js");
const { blackScholes } = require("../static/bs.js");

test("readInputs maps raw slider values to BS inputs", () => {
  const got = readInputs({ type: "call", spot: 100, strike: 105, days: 30,
    iv: 30, rate: 4, div: 1 });
  assert.deepStrictEqual(got, { type: "call", spot: 100, strike: 105,
    daysToExpiration: 30, volatility: 0.30, riskFreeRate: 0.04, dividendYield: 0.01 });
});

test("formatGreeks returns all five Greeks with meanings", () => {
  const r = blackScholes(readInputs({ type: "call", spot: 100, strike: 100,
    days: 365, iv: 20, rate: 5, div: 0 }));
  const cards = formatGreeks(r);
  assert.strictEqual(cards.length, 5);
  assert.deepStrictEqual(cards.map(c => c.name),
    ["Delta", "Gamma", "Theta", "Vega", "Rho"]);
  cards.forEach(c => assert.ok(c.meaning.length > 0 && c.value.length > 0));
});

test("formatProb expresses prob-ITM as a percentage", () => {
  const r = blackScholes(readInputs({ type: "call", spot: 100, strike: 100,
    days: 365, iv: 20, rate: 5, div: 0 }));
  assert.match(formatProb(r), /\d+\.\d%/);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test tests/playground_format.test.js`
Expected: FAIL — cannot find module `../static/playground.js`.

- [ ] **Step 3: Write the implementation**

Create `static/playground.js`:

```javascript
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
      if (root.Playground && root.Playground.drawSweep) root.Playground.drawSweep(doc, raw);
    }

    ids.forEach((id) => doc.getElementById(id).addEventListener("input", update));
    ["sweep-var", "sweep-metric"].forEach((id) => {
      const el = doc.getElementById(id);
      if (el) el.addEventListener("change", update);
    });
    update();
  }

  if (typeof document !== "undefined") {
    document.addEventListener("DOMContentLoaded", () => wire(document));
  }

  return { readInputs, formatPrice, formatGreeks, formatProb, wire };
});
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test tests/playground_format.test.js`
Expected: PASS, `3 passing`.

- [ ] **Step 5: Manual verification in the browser**

Run: `python app.py` then open `http://localhost:8000/playground`. Drag each slider; confirm the premium, Greek cards, and prob-ITM update live and the `<output>` values track the sliders. Stop the server.

- [ ] **Step 6: Commit**

```bash
git add static/playground.js tests/playground_format.test.js
git commit -m "feat: wire playground sliders to live premium, Greeks, prob-ITM"
```

---

### Task 5: Sweep chart

**Files:**
- Modify: `static/playground.js` (add `sweep()` + `drawSweep()` to the returned api)
- Test: `tests/playground_sweep.test.js`

**Interfaces:**
- Consumes: `readInputs` and `BS.blackScholes` (Task 4).
- Produces: pure `sweep({raw, variable, metric, steps})` → `[{x, y}]` data points across the variable's slider range, holding other inputs fixed; and `drawSweep(doc, raw)` which reads `#sweep-var`/`#sweep-metric` and renders to `#sweep-chart`. `sweep` is unit-tested; `drawSweep` (canvas) is verified manually.

- [ ] **Step 1: Write the failing test**

Create `tests/playground_sweep.test.js`:

```javascript
const { test } = require("node:test");
const assert = require("node:assert");
const { sweep } = require("../static/playground.js");

const raw = { type: "call", spot: 100, strike: 100, days: 30, iv: 30, rate: 4, div: 0 };

test("sweep over spot returns rising call premium", () => {
  const pts = sweep({ raw, variable: "spot", metric: "price", steps: 20 });
  assert.strictEqual(pts.length, 21);
  assert.ok(pts[pts.length - 1].y > pts[0].y, "call premium rises with spot");
  assert.ok(pts.every((p) => Number.isFinite(p.x) && Number.isFinite(p.y)));
});

test("sweep over iv returns rising premium (positive vega)", () => {
  const pts = sweep({ raw, variable: "iv", metric: "price", steps: 10 });
  assert.ok(pts[pts.length - 1].y > pts[0].y, "premium rises with IV");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test tests/playground_sweep.test.js`
Expected: FAIL — `sweep` is not a function.

- [ ] **Step 3: Add `sweep` and `drawSweep`**

In `static/playground.js`, add these inside the factory (before the final `return`), and add `sweep`, `drawSweep` to the returned object:

```javascript
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test tests/playground_sweep.test.js`
Expected: PASS, `2 passing`.

- [ ] **Step 5: Run the whole JS suite + manual chart check**

Run: `node --test tests/`
Expected: all PASS.
Then `python app.py`, open `/playground`, change the sweep variable/metric dropdowns, confirm the curve redraws. Stop the server.

- [ ] **Step 6: Commit**

```bash
git add static/playground.js tests/playground_sweep.test.js
git commit -m "feat: add sweep chart to playground"
```

---

### Task 6: Flip strategy calculator to BS-default + docs

**Files:**
- Modify: `app.py:164` (`use_pricer` default)
- Modify: `test_options.py` (update the manual-premium test; add a default-on test)
- Modify: `README.md`
- Modify: `templates/index.html` (link to the playground; reflect BS-on default in the pricer toggle)

**Interfaces:**
- Consumes: existing `/api/calculate` handler and `usePricer` flag.
- Produces: `/api/calculate` treats a missing `usePricer` as `True`. Callers wanting manual premium must send `usePricer: false`.

- [ ] **Step 1: Update tests to lock the new default**

In `test_options.py`, the existing `test_calculate_covered_call` relies on manual premium with no `spot`. Make its intent explicit by adding `"usePricer": False` to its JSON payload (insert after `"premium": 3,`):

```python
            "premium": 3,
            "usePricer": False,
```

Then append a new test asserting the default is now BS-on:

```python
def test_calculate_defaults_to_pricer(client):
    # No usePricer flag and no manual premium -> premium comes from Black-Scholes.
    resp = client.post(
        "/api/calculate",
        json={
            "strategy": "long-call", "contracts": 1, "days": 365,
            "strike": 100, "spot": 100, "ivPct": 20, "ratePct": 5,
        },
    )
    d = resp.get_json()
    assert d["legs"][0]["premium"] == pytest.approx(10.45, abs=0.05)
```

- [ ] **Step 2: Run tests to verify the new one fails**

Run: `pytest test_options.py::test_calculate_defaults_to_pricer test_options.py::test_calculate_covered_call -v`
Expected: `test_calculate_covered_call` PASSES (now explicit); `test_calculate_defaults_to_pricer` FAILS (premium is 0 because default is currently False).

- [ ] **Step 3: Flip the default**

In `app.py`, change line ~164 from:

```python
    use_pricer = bool(data.get("usePricer", False))
```

to:

```python
    use_pricer = bool(data.get("usePricer", True))
```

- [ ] **Step 4: Run the full pytest suite**

Run: `pytest -v`
Expected: all PASS (20 original/updated + the new default test).

- [ ] **Step 5: Update the UI and README**

In `templates/index.html`, add a link to the playground near the top (e.g. after the page heading): `<a href="/playground">Open the learning playground →</a>`. If the page has a pricer/estimator toggle input, set its default to checked/on so the UI matches the API default.

In `README.md`, under the intro/Strategies section, replace the "premium is opt-in estimate" framing with: Black–Scholes is now the **default** premium source (toggle off to type a quote manually), and add a short "Learning Playground" section:

```markdown
## Learning Playground

Visit `/playground` for an interactive Black–Scholes sandbox: drag sliders for
spot, strike, time, implied volatility, rate, and dividend and watch the premium
and all five Greeks (delta, gamma, theta, vega, rho) update live, plus the
probability of finishing in-the-money. The sweep chart plots how the premium or
any Greek responds as you vary one input. European options only — no early
exercise.
```

- [ ] **Step 6: Manual smoke test**

Run: `python app.py`. Confirm `/` still calculates (BS-on by default) and the playground link works. Stop the server.

- [ ] **Step 7: Commit**

```bash
git add app.py test_options.py templates/index.html README.md
git commit -m "feat: default to Black-Scholes pricing; link playground; update docs"
```

---

## Self-Review

**Spec coverage:**
- BS default flip → Task 6. ✓
- Interactive slider playground (spot/strike/days/IV/rate/div + call/put) → Task 3 (page) + Task 4 (wiring). ✓
- Live premium + five Greeks with plain-English meaning → Task 4. ✓
- prob-ITM / N(d2) / d1·d2 display → Task 1 (math) + Task 4 (display). ✓
- Sweep chart → Task 5. ✓
- JS twin + Python parity test → Task 2. ✓
- Python teaching outputs (d1/d2/N(d1)/N(d2)/prob_itm/moneyness) → Task 1. ✓
- Put–call parity correctness check → already covered by existing `test_black_scholes_benchmark` (parity assertion at line 127); the parity grid is implicitly exercised by Task 2's fixture across many cases. ✓
- Existing 18 tests stay green; documented exception (manual-premium test made explicit) → Task 6. ✓
- European-only disclaimer in UI → Task 3 template + Task 6 README. ✓
- Slider bounds (IV 1–200, days 1–730, rate 0–15, div 0–15) → Task 3 template + Task 5 `RANGES`. ✓
- No new deps; Node built-in test runner → respected throughout. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; no "handle edge cases" hand-waves. ✓

**Type consistency:** JS keys camelCase (`nD1`, `nD2`, `probItm`) consistent across `bs.js` (Task 2), the parity `KEY` map (Task 2), and `formatProb`/`sweep` (Tasks 4–5). Python keys snake_case consistent in Task 1 and the fixture generator. `readInputs` output shape matches `blackScholes` parameter names in all consumers. ✓
