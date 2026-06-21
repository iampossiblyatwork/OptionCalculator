"""Options Premium Calculator -- Flask web app.

Serves a single-page UI and a JSON endpoint that runs all the trade math in
Python (see options.py). Designed to deploy as a Docker container; in production
it runs under gunicorn and binds to the port Render provides via $PORT.
"""

from __future__ import annotations

from datetime import date

from flask import Flask, jsonify, render_template, request

import marketdata as md
import options as opt

# Sweet-spot grid axes: strikes span just below today's price out to comfortably
# OTM (where covered calls usually live), and a spread of standard expirations.
SWEET_SPOT_STRIKE_LO = 0.95
SWEET_SPOT_STRIKE_HI = 1.20
SWEET_SPOT_STRIKE_COUNT = 12
SWEET_SPOT_DAYS = [7, 14, 21, 30, 45, 60, 90, 120]


def _sweet_spot_strikes(spot: float) -> list[float]:
    """Evenly spaced strikes around the spot, rounded to whole dollars."""
    if spot <= 0:
        return []
    lo, hi = spot * SWEET_SPOT_STRIKE_LO, spot * SWEET_SPOT_STRIKE_HI
    n = SWEET_SPOT_STRIKE_COUNT
    strikes = [round(lo + (hi - lo) * i / (n - 1)) for i in range(n)]
    # Drop any collisions from rounding while preserving order.
    seen: set[float] = set()
    return [s for s in strikes if not (s in seen or seen.add(s))]

def _live_strikes_and_days(ticker: str, spot: float) -> tuple[list[float], list[float]]:
    """Real listed call strikes/expirations for a ticker, shaped like the
    synthetic sweet-spot grid: near-the-money strikes, a handful of upcoming
    expirations (in days). Raises MarketDataError if the API call fails.
    """
    contracts = md.get_option_contracts(ticker, contract_type="call", expired=False)
    if not contracts:
        raise md.MarketDataError(f"No listed call contracts found for {ticker}")

    lo, hi = spot * SWEET_SPOT_STRIKE_LO, spot * SWEET_SPOT_STRIKE_HI
    strikes = sorted({c["strike_price"] for c in contracts if lo <= c["strike_price"] <= hi})
    if len(strikes) > SWEET_SPOT_STRIKE_COUNT:
        n = SWEET_SPOT_STRIKE_COUNT
        idx = sorted({round(i * (len(strikes) - 1) / (n - 1)) for i in range(n)})
        strikes = [strikes[i] for i in idx]

    today = date.today()
    days_list = sorted(
        {
            (date.fromisoformat(c["expiration_date"]) - today).days
            for c in contracts
            if date.fromisoformat(c["expiration_date"]) > today
        }
    )[: len(SWEET_SPOT_DAYS)]

    return strikes, [float(d) for d in days_list]


app = Flask(__name__)

# Each strategy declares which input fields it needs and how to assemble a
# Position from the posted inputs. Keeping this data-driven keeps the form (sent
# to the browser) and the math in lock-step.
STRATEGIES = [
    {
        "id": "covered-call",
        "label": "Covered call",
        "blurb": "You own the shares and sell a call against them to collect premium. "
        "Capped upside at the strike; premium cushions a drop. Cost basis is "
        "optional — returns are measured against today's share price.",
        "fields": ["currentPrice", "strike", "premium", "costBasis"],
        "income": "coveredCall",
    },
    {
        "id": "cash-secured-put",
        "label": "Cash-secured put",
        "blurb": "Sell a put and set aside cash to buy the shares if assigned. You collect "
        "premium; your effective buy price is the strike minus premium.",
        "fields": ["strike", "premium"],
        "income": "cashSecuredPut",
    },
    {
        "id": "long-call",
        "label": "Long call (buy call)",
        "blurb": "Pay premium for upside. Loss capped at the premium; profit unlimited "
        "above breakeven.",
        "fields": ["strike", "premium"],
    },
    {
        "id": "long-put",
        "label": "Long put (buy put)",
        "blurb": "Pay premium for downside protection or a bearish bet. Loss capped at "
        "premium.",
        "fields": ["strike", "premium"],
    },
    {
        "id": "short-call",
        "label": "Short call (naked)",
        "blurb": "Sell a call without owning the shares. You collect premium but the loss "
        "is unlimited above the strike -- high risk.",
        "fields": ["strike", "premium"],
    },
    {
        "id": "short-put",
        "label": "Short put (naked)",
        "blurb": "Sell a put to collect premium. Same payoff as a cash-secured put but "
        "without setting cash aside.",
        "fields": ["strike", "premium"],
    },
    {
        "id": "bull-call-spread",
        "label": "Bull call spread",
        "blurb": "Buy a lower-strike call, sell a higher-strike call. Defined risk and "
        "defined reward.",
        "fields": ["strike", "premium", "strike2", "premium2"],
    },
    {
        "id": "bear-put-spread",
        "label": "Bear put spread",
        "blurb": "Buy a higher-strike put, sell a lower-strike put. Defined risk and "
        "defined reward.",
        "fields": ["strike", "premium", "strike2", "premium2"],
    },
]

STRATEGY_BY_ID = {s["id"]: s for s in STRATEGIES}

FIELD_LABELS = {
    "strike": "Strike ($)",
    "premium": "Premium / share ($)",
    "strike2": "Strike — short leg ($)",
    "premium2": "Premium — short leg ($)",
    "costBasis": "Your cost basis / share ($) — optional",
    "currentPrice": "Current share price ($)",
}


def _leg_defs(strategy_id: str, i: dict) -> list[dict]:
    """Option legs (without premium) for a strategy, from the posted inputs."""
    c = i["contracts"]
    if strategy_id == "covered-call":
        return [{"type": "call", "side": "short", "strike": i["strike"], "contracts": c}]
    if strategy_id in ("cash-secured-put", "short-put"):
        return [{"type": "put", "side": "short", "strike": i["strike"], "contracts": c}]
    if strategy_id == "long-call":
        return [{"type": "call", "side": "long", "strike": i["strike"], "contracts": c}]
    if strategy_id == "long-put":
        return [{"type": "put", "side": "long", "strike": i["strike"], "contracts": c}]
    if strategy_id == "short-call":
        return [{"type": "call", "side": "short", "strike": i["strike"], "contracts": c}]
    if strategy_id == "bull-call-spread":
        return [
            {"type": "call", "side": "long", "strike": i["strike"], "contracts": c},
            {"type": "call", "side": "short", "strike": i["strike2"], "contracts": c},
        ]
    if strategy_id == "bear-put-spread":
        return [
            {"type": "put", "side": "long", "strike": i["strike"], "contracts": c},
            {"type": "put", "side": "short", "strike": i["strike2"], "contracts": c},
        ]
    raise ValueError(f"Unknown strategy: {strategy_id!r}")


def _num(data: dict, key: str, default: float = 0.0) -> float:
    try:
        v = float(data.get(key, default))
    except (TypeError, ValueError):
        return default
    return v


@app.get("/")
def index():
    return render_template(
        "index.html",
        strategies=STRATEGIES,
        field_labels=FIELD_LABELS,
        shares_per_contract=opt.SHARES_PER_CONTRACT,
    )


@app.get("/playground")
def playground():
    return render_template("playground.html")


@app.get("/sweet-spot")
def sweet_spot():
    return render_template("sweetspot.html")


@app.post("/api/sweet-spot")
def api_sweet_spot():
    data = request.get_json(silent=True) or {}
    spot = max(0.0, _num(data, "spot", 261))
    volatility = max(0.0, _num(data, "ivPct", 78.88)) / 100.0
    rate = _num(data, "ratePct", 4) / 100.0
    div = _num(data, "divPct", 0) / 100.0
    ticker = (data.get("ticker") or "").strip().upper()

    data_source = "synthetic"
    if ticker:
        try:
            strikes, days_list = _live_strikes_and_days(ticker, spot)
            data_source = "live"
        except md.MarketDataError as e:
            return jsonify(error=f"{ticker}: {e}"), 502
        if not strikes or not days_list:
            return (
                jsonify(error=f"No near-the-money call contracts found for {ticker}"),
                400,
            )
    else:
        strikes = _sweet_spot_strikes(spot)
        days_list = SWEET_SPOT_DAYS

    if not strikes or volatility <= 0:
        return jsonify(error="Need a positive spot price and implied volatility"), 400

    result = opt.covered_call_sweet_spot(
        spot=spot,
        volatility=volatility,
        strikes=strikes,
        days_list=days_list,
        risk_free_rate=rate,
        dividend_yield=div,
    )
    result["ticker"] = ticker or None
    result["dataSource"] = data_source
    return jsonify(result)


@app.get("/healthz")
def healthz():
    return jsonify(status="ok")


@app.post("/api/calculate")
def calculate():
    data = request.get_json(silent=True) or {}

    strategy_id = data.get("strategy", "covered-call")
    strategy = STRATEGY_BY_ID.get(strategy_id)
    if strategy is None:
        return jsonify(error=f"Unknown strategy: {strategy_id}"), 400

    inputs = {
        "contracts": max(0.0, _num(data, "contracts", 1)),
        "days": max(0.0, _num(data, "days", 30)),
        "strike": _num(data, "strike"),
        "premium": _num(data, "premium"),
        "strike2": _num(data, "strike2"),
        "premium2": _num(data, "premium2"),
        "costBasis": _num(data, "costBasis"),
        "currentPrice": _num(data, "currentPrice"),
        "spot": _num(data, "spot"),
        "ivPct": _num(data, "ivPct", 30),
        "ratePct": _num(data, "ratePct", 4),
        "divPct": _num(data, "divPct", 0),
    }
    use_pricer = bool(data.get("usePricer", True))

    leg_defs = _leg_defs(strategy_id, inputs)

    # Resolve each leg's premium: typed in, or estimated with Black-Scholes.
    manual = [inputs["premium"], inputs["premium2"]]
    legs = []
    estimates = []
    for idx, ld in enumerate(leg_defs):
        bs = opt.black_scholes(
            type=ld["type"],
            spot=inputs["spot"],
            strike=ld["strike"],
            days_to_expiration=inputs["days"],
            volatility=inputs["ivPct"] / 100.0,
            risk_free_rate=inputs["ratePct"] / 100.0,
            dividend_yield=inputs["divPct"] / 100.0,
        )
        estimates.append(bs)
        premium = max(0.0, bs["price"]) if use_pricer else (manual[idx] if idx < len(manual) else 0.0)
        legs.append(opt.OptionLeg(ld["type"], ld["side"], ld["strike"], premium, ld["contracts"]))

    # Cost basis is optional for a covered call: a blank/zero entry means "I don't
    # care what I paid -- price the trade off today's share price."
    cost_basis = inputs["costBasis"] if inputs["costBasis"] > 0 else None

    stock = None
    if strategy_id == "covered-call":
        stock = opt.StockLeg(
            shares=inputs["contracts"] * opt.SHARES_PER_CONTRACT,
            cost_basis=cost_basis if cost_basis is not None else inputs["currentPrice"],
        )

    position = opt.Position(legs=legs, stock=stock, multiplier=opt.SHARES_PER_CONTRACT)
    summary = opt.summarize_position(position)

    primary_premium = legs[0].premium if legs else 0.0
    income = None
    if strategy.get("income") == "coveredCall":
        income = opt.covered_call(
            shares=inputs["contracts"] * opt.SHARES_PER_CONTRACT,
            current_price=inputs["currentPrice"],
            strike=inputs["strike"],
            premium=primary_premium,
            days_to_expiration=inputs["days"],
            cost_basis=cost_basis,
        )
    elif strategy.get("income") == "cashSecuredPut":
        income = opt.cash_secured_put(
            strike=inputs["strike"],
            premium=primary_premium,
            contracts=inputs["contracts"],
            days_to_expiration=inputs["days"],
        )

    # Payoff curve range, centered on the strikes / cost basis.
    refs = [ld["strike"] for ld in leg_defs]
    if stock is not None:
        refs.append(stock.cost_basis)
    lo = max(0.0, min(refs) * 0.7)
    hi = max(refs) * 1.3
    payoff = opt.payoff_curve(position, lo, hi, 120)

    return jsonify(
        netPremium=summary.net_premium,
        breakevens=summary.breakevens,
        maxProfit=summary.max_profit,  # null in JSON = unlimited
        maxLoss=summary.max_loss,
        incomeType=strategy.get("income"),
        income=income,
        legs=[
            {
                "type": leg.type,
                "side": leg.side,
                "strike": leg.strike,
                "premium": leg.premium,
                "delta": estimates[idx]["delta"],
            }
            for idx, leg in enumerate(legs)
        ],
        usePricer=use_pricer,
        payoff=payoff,
        priceRange={"lo": lo, "hi": hi},
        strikes=[ld["strike"] for ld in leg_defs],
    )


if __name__ == "__main__":
    # Local development only. In the container, gunicorn serves the app.
    import os

    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=True)
