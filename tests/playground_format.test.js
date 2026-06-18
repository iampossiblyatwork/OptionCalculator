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
