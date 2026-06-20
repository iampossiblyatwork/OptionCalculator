"""Tests for the options math and the Flask API."""

import math

import pytest

import options as opt
from app import app


# ---------------------------------------------------------------------------
# Math
# ---------------------------------------------------------------------------


def test_intrinsic():
    assert opt.intrinsic("call", 100, 110) == 10
    assert opt.intrinsic("call", 100, 90) == 0
    assert opt.intrinsic("put", 100, 90) == 10
    assert opt.intrinsic("put", 100, 110) == 0


def test_single_leg_pnl():
    long_call = opt.OptionLeg("call", "long", 100, 2, 1)
    assert opt.leg_pnl_at_expiration(long_call, 95) == pytest.approx(-200)
    assert opt.leg_pnl_at_expiration(long_call, 102) == pytest.approx(0)
    assert opt.leg_pnl_at_expiration(long_call, 112) == pytest.approx(1000)

    short_put = opt.OptionLeg("put", "short", 100, 3, 1)
    assert opt.leg_pnl_at_expiration(short_put, 105) == pytest.approx(300)
    assert opt.leg_pnl_at_expiration(short_put, 90) == pytest.approx(-700)


def test_net_premium_nets_credit_against_debit():
    pos = opt.Position(
        legs=[
            opt.OptionLeg("call", "short", 110, 1.5, 1),
            opt.OptionLeg("call", "long", 120, 0.5, 1),
        ]
    )
    assert opt.net_premium(pos) == pytest.approx(100)


def test_summarize_long_call():
    pos = opt.Position(legs=[opt.OptionLeg("call", "long", 100, 2, 1)])
    s = opt.summarize_position(pos)
    assert s.max_loss == pytest.approx(-200)
    assert s.max_profit is None  # unlimited
    assert s.breakevens == [102]


def test_summarize_short_put():
    pos = opt.Position(legs=[opt.OptionLeg("put", "short", 100, 3, 1)])
    s = opt.summarize_position(pos)
    assert s.max_profit == pytest.approx(300)
    assert s.max_loss == pytest.approx(-9700)
    assert s.breakevens == [97]


def test_summarize_covered_call():
    pos = opt.Position(
        legs=[opt.OptionLeg("call", "short", 110, 3, 1)],
        stock=opt.StockLeg(shares=100, cost_basis=100),
    )
    s = opt.summarize_position(pos)
    assert s.max_profit == pytest.approx(1300)
    assert s.max_profit is not None  # upside capped
    assert s.breakevens == [97]


def test_summarize_bull_call_spread():
    pos = opt.Position(
        legs=[
            opt.OptionLeg("call", "long", 100, 4, 1),
            opt.OptionLeg("call", "short", 110, 1.5, 1),
        ]
    )
    s = opt.summarize_position(pos)
    assert s.net_premium == pytest.approx(-250)
    assert s.max_loss == pytest.approx(-250)
    assert s.max_profit == pytest.approx(750)
    assert s.breakevens[0] == pytest.approx(102.5)


def test_covered_call_returns_off_current_price():
    # Returns are measured against today's share price, not cost basis.
    r = opt.covered_call(
        shares=100, current_price=105, strike=110, premium=3,
        days_to_expiration=30,
    )
    assert r["premium_collected"] == pytest.approx(300)
    assert r["capital_at_risk"] == pytest.approx(10500)
    assert r["breakeven"] == pytest.approx(102)  # current price - premium
    assert r["max_profit_if_unchanged"] == pytest.approx(300)
    assert r["max_profit_if_called"] == pytest.approx(800)  # (110-105+3)*100
    assert r["static_return"] == pytest.approx(3 / 105)
    assert r["return_if_called"] == pytest.approx((110 - 105 + 3) / 105)
    assert r["static_return_annualized"] == pytest.approx((3 / 105) * (365 / 30))
    assert r["downside_protection"] == pytest.approx(3 / 105)
    # No cost basis given -> no accounting-only metrics.
    assert "net_cost_basis" not in r
    assert "total_gain_if_called" not in r


def test_covered_call_cost_basis_is_optional_extra():
    # Supplying cost basis adds accounting metrics but leaves the current-price
    # returns untouched.
    r = opt.covered_call(
        shares=100, current_price=105, strike=110, premium=3,
        days_to_expiration=30, cost_basis=100,
    )
    assert r["static_return"] == pytest.approx(3 / 105)  # unchanged by cost basis
    assert r["net_cost_basis"] == pytest.approx(97)
    assert r["total_gain_if_called"] == pytest.approx(1300)  # (110-100+3)*100
    assert r["total_return_if_called"] == pytest.approx(0.13)
    assert r["total_return_if_called_annualized"] == pytest.approx(0.13 * (365 / 30))


def test_cash_secured_put_returns():
    r = opt.cash_secured_put(strike=50, premium=1.25, contracts=2, days_to_expiration=45)
    assert r["premium_collected"] == pytest.approx(250)
    assert r["cash_secured"] == pytest.approx(10000)
    assert r["breakeven"] == pytest.approx(48.75)
    assert r["return_on_cash"] == pytest.approx(1.25 / 50)
    assert r["return_on_cash_annualized"] == pytest.approx((1.25 / 50) * (365 / 45))


def test_covered_call_sweet_spot_grid_shape_and_scoring():
    strikes = [100, 105, 110]
    days_list = [30, 60]
    r = opt.covered_call_sweet_spot(
        spot=100, volatility=0.3, strikes=strikes, days_list=days_list,
    )
    assert len(r["grid"]) == 2  # one row per expiration
    assert all(len(row) == 3 for row in r["grid"])  # one cell per strike

    # Every cell's score is annualized yield * probability of keeping the shares,
    # and prob_keep + prob_assigned == 1.
    for row in r["grid"]:
        for c in row:
            assert c["prob_keep_shares"] + c["prob_assigned"] == pytest.approx(1.0)
            assert c["risk_adjusted_score"] == pytest.approx(
                c["annualized_yield"] * c["prob_keep_shares"]
            )

    # The reported best cell really is the grid-wide maximum score.
    flat = [c for row in r["grid"] for c in row]
    top = max(flat, key=lambda c: c["risk_adjusted_score"])
    best = r["grid"][r["best"]["row"]][r["best"]["col"]]
    assert best["risk_adjusted_score"] == pytest.approx(top["risk_adjusted_score"])


def test_covered_call_sweet_spot_skips_thin_far_otm():
    # The deep-OTM strike pays a thin premium, so it should never be the
    # risk-adjusted winner even though it's the most likely to expire worthless.
    strikes = [100, 105, 110, 115, 120, 125]
    r = opt.covered_call_sweet_spot(
        spot=100, volatility=0.4, strikes=strikes, days_list=[45],
    )
    assert r["best"]["col"] < len(strikes) - 1


def test_norm_cdf():
    assert opt.norm_cdf(0) == pytest.approx(0.5, abs=1e-4)
    assert opt.norm_cdf(1.96) == pytest.approx(0.975, abs=1e-3)
    assert opt.norm_cdf(-1.96) == pytest.approx(0.025, abs=1e-3)


def test_black_scholes_benchmark():
    call = opt.black_scholes(
        type="call", spot=100, strike=100, days_to_expiration=365,
        volatility=0.2, risk_free_rate=0.05,
    )
    put = opt.black_scholes(
        type="put", spot=100, strike=100, days_to_expiration=365,
        volatility=0.2, risk_free_rate=0.05,
    )
    assert call["price"] == pytest.approx(10.45, abs=0.05)
    assert put["price"] == pytest.approx(5.57, abs=0.05)
    # Put-call parity: C - P = S - K e^{-rT}
    parity = 100 - 100 * math.exp(-0.05 * 1)
    assert call["price"] - put["price"] == pytest.approx(parity, abs=0.01)
    assert 0.5 < call["delta"] < 0.7
    assert put["delta"] < 0
    assert call["theta"] < 0
    assert call["vega"] > 0
    assert call["gamma"] > 0


def test_black_scholes_at_expiration_is_intrinsic():
    expired = opt.black_scholes(
        type="call", spot=110, strike=100, days_to_expiration=0, volatility=0.2,
    )
    assert expired["price"] == pytest.approx(10)


def test_covered_call_pnl_capped_above_strike():
    pos = opt.Position(
        legs=[opt.OptionLeg("call", "short", 110, 3, 1)],
        stock=opt.StockLeg(shares=100, cost_basis=100),
    )
    assert opt.position_pnl_at_expiration(pos, 110) == pytest.approx(1300)
    assert opt.position_pnl_at_expiration(pos, 130) == pytest.approx(1300)
    assert opt.position_pnl_at_expiration(pos, 97) == pytest.approx(0)


# ---------------------------------------------------------------------------
# Flask API
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_index_serves_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Options Premium Calculator" in resp.data


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_calculate_covered_call(client):
    resp = client.post(
        "/api/calculate",
        json={
            "strategy": "covered-call",
            "contracts": 1,
            "days": 30,
            "costBasis": 100,
            "currentPrice": 105,
            "strike": 110,
            "premium": 3,
            "usePricer": False,
        },
    )
    assert resp.status_code == 200
    d = resp.get_json()
    assert d["netPremium"] == pytest.approx(300)
    assert d["breakevens"] == [97]
    assert d["maxProfit"] == pytest.approx(1300)
    assert d["incomeType"] == "coveredCall"
    assert d["income"]["return_if_called"] == pytest.approx((110 - 105 + 3) / 105)
    assert d["income"]["total_return_if_called"] == pytest.approx(0.13)  # cost basis given
    assert len(d["payoff"]) == 121


def test_calculate_covered_call_without_cost_basis(client):
    # Cost basis omitted: the trade still prices off the current share price and
    # the breakeven / chart use today's price instead of a purchase price.
    resp = client.post(
        "/api/calculate",
        json={
            "strategy": "covered-call",
            "contracts": 1,
            "days": 30,
            "currentPrice": 105,
            "strike": 110,
            "premium": 3,
            "usePricer": False,
        },
    )
    assert resp.status_code == 200
    d = resp.get_json()
    assert d["netPremium"] == pytest.approx(300)
    assert d["breakevens"] == [102]  # current price - premium
    assert d["income"]["static_return"] == pytest.approx(3 / 105)
    assert "net_cost_basis" not in d["income"]


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


def test_calculate_with_pricer(client):
    resp = client.post(
        "/api/calculate",
        json={
            "strategy": "long-call",
            "contracts": 1,
            "days": 365,
            "strike": 100,
            "usePricer": True,
            "spot": 100,
            "ivPct": 20,
            "ratePct": 5,
        },
    )
    d = resp.get_json()
    # Estimated premium should match the Black-Scholes benchmark (~10.45/share).
    assert d["legs"][0]["premium"] == pytest.approx(10.45, abs=0.05)
    assert d["maxProfit"] is None  # unlimited upside


def test_calculate_unknown_strategy(client):
    resp = client.post("/api/calculate", json={"strategy": "nope"})
    assert resp.status_code == 400


def test_sweet_spot_page_serves_html(client):
    resp = client.get("/sweet-spot")
    assert resp.status_code == 200
    assert b"sweetspot.js" in resp.data
    assert b"Sweet Spot" in resp.data


def test_api_sweet_spot_returns_grid(client):
    resp = client.post(
        "/api/sweet-spot",
        json={"spot": 261, "ivPct": 78.88, "ratePct": 4, "divPct": 0},
    )
    assert resp.status_code == 200
    d = resp.get_json()
    assert len(d["strikes"]) >= 8
    assert len(d["days"]) == len(d["grid"])
    assert len(d["grid"][0]) == len(d["strikes"])
    # best indices point at a real cell
    assert 0 <= d["best"]["row"] < len(d["grid"])
    assert 0 <= d["best"]["col"] < len(d["strikes"])


def test_api_sweet_spot_rejects_bad_inputs(client):
    resp = client.post("/api/sweet-spot", json={"spot": 0, "ivPct": 30})
    assert resp.status_code == 400


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


def test_playground_serves_html(client):
    resp = client.get("/playground")
    assert resp.status_code == 200
    body = resp.data
    for token in (b'id="spot"', b'id="strike"', b'id="iv"', b'id="days"',
                  b'id="sweep-chart"', b'bs.js', b'playground.js'):
        assert token in body
    assert b"European" in body  # early-exercise disclaimer
