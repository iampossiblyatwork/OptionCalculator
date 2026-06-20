# Options Premium Calculator

A self-contained **Flask** web app for sizing up options trades: how much
premium you collect or pay, where the trade breaks even, the most you can make
or lose, an at-expiration profit/loss chart, and return metrics for income
strategies (covered calls and cash-secured puts).

> Black–Scholes is now the **default** premium source — the calculator prices
> each leg theoretically from spot, strike, time, volatility, and rate. Toggle
> it off if you have a market quote you'd rather type in manually.

## Strategies

Covered call · cash-secured put · long call · long put · short (naked) call ·
short (naked) put · bull call spread · bear put spread. One contract = 100
shares.

## Covered-Call Sweet Spot

Visit `/sweet-spot` for a strike × expiration heatmap that ranks covered calls by
**risk-adjusted yield** — the annualized premium yield scaled by the probability
the call expires worthless (you keep both the premium and your shares). Every
cell is one covered call; brighter green is a better score and the ringed cell is
the sweet spot. Tap any cell for the full breakdown (premium, annualized yield,
odds of keeping the shares, return if called, delta). Premiums are priced from
Black–Scholes off the spot/IV/rate/dividend inputs, and the grid is shaped so
live option-chain quotes can later drop straight in.

## Learning Playground

Visit `/playground` for an interactive Black–Scholes sandbox: drag sliders for
spot, strike, time, implied volatility, rate, and dividend and watch the premium
and all five Greeks (delta, gamma, theta, vega, rho) update live, plus the
probability of finishing in-the-money. The sweep chart plots how the premium or
any Greek responds as you vary one input. European options only — no early
exercise.

## Run locally

```bash
pip install -r requirements.txt
python app.py            # dev server on http://localhost:8000
```

Or with the production server:

```bash
gunicorn --bind 0.0.0.0:8000 app:app
```

## Run the tests

```bash
pip install pytest
pytest                   # math + Flask API
```

The JavaScript Black–Scholes twin and playground helpers have their own suite
(Node's built-in test runner — no install needed):

```bash
node --test tests/*.test.js
```

## Docker

```bash
docker build -t options-calculator .
docker run -p 8000:8000 options-calculator
# open http://localhost:8000
```

The container binds to `$PORT` (defaulting to 8000), so it works unchanged on
hosts that inject a port.

## Deploy to Render

Two ways:

**Blueprint (recommended).** This repo ships a `render.yaml` at its root. In
Render: **New → Blueprint**, connect the repo, and Render builds the Docker
image from the repo root and runs it. `$PORT` and the health check
(`/healthz`) are wired up for you.

**Manual web service.** In Render: **New → Web Service**, connect the repo, and
set:

- **Runtime:** Docker
- **Health Check Path:** `/healthz`

Leave Root Directory, Dockerfile Path, and Docker Build Context Directory at
their defaults — the Dockerfile lives at the repo root. Render provides
`$PORT` automatically; the Dockerfile's gunicorn command already binds to it.

## Layout

- `app.py` — Flask routes: the page (`/`), the playground (`/playground`), the calc API (`/api/calculate`), health (`/healthz`)
- `options.py` — pure trade-economics + Black–Scholes math (no dependencies)
- `templates/index.html`, `static/` — the UI (vanilla JS, canvas payoff chart)
- `static/bs.js` — pure JS Black–Scholes twin used by the playground (kept in parity with `options.py` via `tests/bs_parity.test.js`)
- `static/playground.js` — playground slider wiring + sweep chart
- `templates/playground.html` — the Learning Playground page
- `test_options.py` — pytest suite for the math and the API
- `Dockerfile`, `requirements.txt` — container + deps
