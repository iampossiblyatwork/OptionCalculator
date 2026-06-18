# Options Learning Playground — Design

**Date:** 2026-06-17
**Status:** Approved (design); pending implementation plan
**Repo:** `~/OptionCalculator`

## Goal

Turn the existing Options Premium Calculator into a tool that *teaches the
options math* — specifically, an interactive Black–Scholes playground where
moving sliders for spot, strike, time, IV, rate, and dividend updates the
premium and all five Greeks live, so the user learns by watching how each input
moves the price. Black–Scholes becomes the default premium source rather than an
opt-in estimator.

This is a learning tool for one user (James). Correctness of the math matters
more than breadth of features.

## Non-Goals (YAGNI)

- No live market data / broker quotes — BS theoretical pricing only.
- No accounts, persistence, or auth.
- No multi-leg strategies in the playground — the teaching unit is a *single*
  option. (The existing strategy calculator keeps its multi-leg support.)
- American options / early exercise are out of scope. European Black–Scholes
  only, stated plainly in the UI.

## Decisions (locked during brainstorming)

1. **BS becomes the default** premium source in the existing calculator
   (`usePricer` defaults true; manual premium entry remains as an override).
2. **Teaching mode = interactive playground** (sliders → live price + Greeks).
3. **Math runs client-side in JS** for zero-latency slider response. Python
   remains the canonical, tested implementation; a parity test asserts the JS
   twin agrees with Python.

## Architecture

### 1. Math engine — Python (`options.py`, mostly done)

`black_scholes()` is already correct (full Greeks with continuous dividend
yield, correct degenerate-case handling, theta per-day, vega/rho per 1%). It
stays the canonical source of truth.

**Additions** (for teaching — no rewrite of existing logic):

- Return `d1`, `d2`, `n_d1` (= N(d1)), `n_d2` (= N(d2)) in the result dict.
- Return `prob_itm` = N(d2) for calls, N(−d2) for puts, framed as "probability
  of finishing in-the-money" (risk-neutral).
- Return `moneyness` (S/K) for display.

Existing keys (`price`, `delta`, `gamma`, `theta`, `vega`, `rho`) are unchanged
so nothing downstream breaks.

### 2. JS math twin — `static/bs.js`

A faithful port of `black_scholes` to browser JavaScript:

- `normCdf(x)` via a standard erf approximation (JS has no built-in erf).
- Same formulas, same scaling conventions (theta per-day, vega/rho per 1%).
- Same degenerate-case branch (T≤0, σ≤0, S≤0, K≤0 → intrinsic).

Drives all slider updates with no network round-trip.

**Parity guarantee:** a pytest writes a grid of input cases plus Python-computed
expected outputs to a JSON fixture (`tests/fixtures/bs_parity.json`). A small
Node test reads the same fixture, runs `bs.js`, and asserts agreement:
price within $0.01, Greeks within a small epsilon (e.g. 1e-6 absolute or 1e-4
relative). This is the safety net for maintaining two implementations.

### 3. Playground page — `/playground` (new Flask route)

A new page, separate from the existing strategy calculator at `/`.

- **Controls (left):** range sliders + paired number inputs for **spot,
  strike, days-to-expiration, IV %, risk-free %, dividend %**, plus a call/put
  toggle. Number inputs and sliders stay in sync.
- **Outputs (right), updating live on every slider input event:**
  - **Premium** — large headline number, with the BS price formula shown and
    the current numbers plugged in.
  - **Five Greek cards** — delta, gamma, theta, vega, rho; each shows its
    current value and a one-line plain-English meaning.
  - **Probability of finishing ITM** — `N(d2)` (or `N(−d2)` for puts) shown as
    a percentage, with `d1`/`d2` visible.
  - **Sweep chart** — select one input variable (e.g. IV); plot how premium
    *or* a chosen Greek varies across that variable's range, holding the others
    fixed. This is the core "watch the inputs move the price" learning loop.
    Rendered on a canvas (consistent with the existing payoff chart).

All math is client-side via `bs.js`; the page needs no API calls for updates.

### 4. Existing calculator (`/`) — default flip

`usePricer` defaults to **true**. When on, premium comes from BS using the
IV/rate/dividend/days inputs; the user can still switch to manual premium entry.
Behavior is otherwise unchanged.

## Data Flow

```
Playground (browser)
  sliders/inputs  ── on input ──▶  bs.js: blackScholes(...)
                                      │
                                      ▼
                    { price, delta, gamma, theta, vega, rho,
                      d1, d2, n_d1, n_d2, prob_itm, moneyness }
                                      │
                                      ▼
                    DOM update: headline price, Greek cards,
                    prob-ITM, sweep chart redraw
  (no server round-trip)

Server's role: serve the page + static assets; the existing /api/calculate
remains for the strategy calculator.
```

## Error Handling / Edge Cases

- Degenerate inputs (T≤0, σ≤0, S≤0, K≤0) → intrinsic value, matching Python's
  branch. Greeks degrade to the documented degenerate values (delta 0/±1,
  others 0).
- Slider ranges are bounded to sane values (e.g. IV 1–200%, days 1–730, rate
  0–15%, dividend 0–15%) so the user can't drive the model into nonsense.
- Division-by-zero guards mirror Python (`sigma*sqrt(T)` denominator only
  reached when both are positive).

## Testing

- **Existing 18 pytest cases stay green** (no behavior change to current API).
- **New Python tests:**
  - The added BS outputs: `d1`, `d2`, `n_d2`, `prob_itm`, `moneyness` on known
    cases.
  - **Put–call parity** as an independent correctness check:
    `C − P = S·e^(−qT) − K·e^(−rT)` within a tight tolerance across a grid.
- **Parity fixture + Node test:** JS `bs.js` matches Python across the grid
  (price ≤ $0.01, Greeks within epsilon).

## Layout (files)

- `options.py` — extend `black_scholes()` return dict (additive only).
- `app.py` — add `GET /playground` route.
- `static/bs.js` — JS Black–Scholes twin.
- `static/playground.js` — slider wiring, DOM updates, sweep chart.
- `templates/playground.html` — playground page.
- `test_options.py` — new BS-output + put–call-parity tests + fixture generator.
- `tests/fixtures/bs_parity.json` — generated parity grid.
- `tests/bs_parity.test.js` (+ minimal Node runner) — JS↔Python parity.
- `README.md` — document the playground and the BS-default change.

## Open Questions

None blocking. (Sweep-chart styling and Greek-card copy will be refined during
implementation.)
