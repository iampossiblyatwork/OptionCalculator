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
