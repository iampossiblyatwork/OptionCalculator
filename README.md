# Options Premium Calculator

A self-contained **Flask** web app for sizing up options trades: how much
premium you collect or pay, where the trade breaks even, the most you can make
or lose, an at-expiration profit/loss chart, and return metrics for income
strategies (covered calls and cash-secured puts).

> Premium is set by the market, not derived from the strike. Enter the price you
> see quoted. If you don't have a quote, flip on the **Black–Scholes estimator**
> to get a theoretical price — but treat it as an estimate only.

## Strategies

Covered call · cash-secured put · long call · long put · short (naked) call ·
short (naked) put · bull call spread · bear put spread. One contract = 100
shares.

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

- `app.py` — Flask routes: the page (`/`), the calc API (`/api/calculate`), health (`/healthz`)
- `options.py` — pure trade-economics + Black–Scholes math (no dependencies)
- `templates/index.html`, `static/` — the UI (vanilla JS, canvas payoff chart)
- `test_options.py` — pytest suite for the math and the API
- `Dockerfile`, `requirements.txt` — container + deps
