"""Options Premium Calculator -- Flask web app.

Serves a single-page UI and a JSON endpoint that runs all the trade math in
Python (see options.py). Designed to deploy as a Docker container; in production
it runs under gunicorn and binds to the port Render provides via $PORT.
"""

from __future__ import annotations

from flask import Flask, jsonify, render_template, request

import options as opt

app = Flask(__name__)

# Each strategy declares which input fields it needs and how to assemble a
# Position from the posted inputs. Keeping this data-driven keeps the form (sent
# to the browser) and the math in lock-step.
STRATEGIES = [
    {
        "id": "covered-call",
        "label": "Covered call",
        "blurb": "You own the shares and sell a call against them to collect premium. "
        "Capped upside at the strike; premium cushions a drop.",
        "fields": ["costBasis", "currentPrice", "strike", "premium"],
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
    "costBasis": "Your cost basis / share ($)",
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

    stock = None
    if strategy_id == "covered-call":
        stock = opt.StockLeg(
            shares=inputs["contracts"] * opt.SHARES_PER_CONTRACT,
            cost_basis=inputs["costBasis"],
        )

    position = opt.Position(legs=legs, stock=stock, multiplier=opt.SHARES_PER_CONTRACT)
    summary = opt.summarize_position(position)

    primary_premium = legs[0].premium if legs else 0.0
    income = None
    if strategy.get("income") == "coveredCall":
        income = opt.covered_call(
            shares=inputs["contracts"] * opt.SHARES_PER_CONTRACT,
            cost_basis=inputs["costBasis"],
            current_price=inputs["currentPrice"],
            strike=inputs["strike"],
            premium=primary_premium,
            days_to_expiration=inputs["days"],
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
