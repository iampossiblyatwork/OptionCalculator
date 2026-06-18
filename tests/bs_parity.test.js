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
  // Guard: KEY must mirror every key black_scholes() returns (catches drift).
  const expectedKeys = Object.keys(grid[0].expected).sort();
  assert.deepStrictEqual(Object.keys(KEY).sort(), expectedKeys,
    "KEY map must mirror all keys returned by black_scholes()");

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
