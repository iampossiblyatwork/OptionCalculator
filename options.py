"""Options trade calculator — pure, dependency-free math.

Two jobs live here:

1. Trade economics: given the premium you actually see quoted, what do you
   collect/pay, where is breakeven, what's the most you can make or lose, and
   (for income strategies like covered calls) what's the return.
2. Theoretical pricing: a Black-Scholes estimate of an option's premium for when
   you don't have a live quote handy. This is only an estimate -- the real
   premium is whatever the market is quoting (the bid/ask).

Everything is in US dollars. Standard US equity options cover 100 shares per
contract; that multiplier is configurable but defaults to 100.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal, Optional

SHARES_PER_CONTRACT = 100
DAYS_PER_YEAR = 365

OptionType = Literal["call", "put"]
Side = Literal["long", "short"]  # long = you buy/pay; short = you sell/collect


@dataclass
class OptionLeg:
    type: OptionType
    side: Side
    strike: float
    premium: float  # $ per share (the quoted price, not x100)
    contracts: float


@dataclass
class StockLeg:
    shares: float  # positive = long shares, negative = short
    cost_basis: float  # $ per share you paid (or sold short at)


@dataclass
class Position:
    legs: list[OptionLeg] = field(default_factory=list)
    stock: Optional[StockLeg] = None
    multiplier: int = SHARES_PER_CONTRACT


# ---------------------------------------------------------------------------
# Intrinsic value & payoff
# ---------------------------------------------------------------------------


def intrinsic(option_type: OptionType, strike: float, price: float) -> float:
    """Intrinsic value of one option (per share) at an underlying price."""
    if option_type == "call":
        return max(price - strike, 0.0)
    return max(strike - price, 0.0)


def leg_premium_cashflow(leg: OptionLeg, multiplier: int = SHARES_PER_CONTRACT) -> float:
    """Net premium cash flow for a leg, in dollars.

    Positive = you collect (short), negative = you pay (long).
    """
    gross = leg.premium * leg.contracts * multiplier
    return gross if leg.side == "short" else -gross


def leg_pnl_at_expiration(
    leg: OptionLeg, price: float, multiplier: int = SHARES_PER_CONTRACT
) -> float:
    """Profit/loss of a single leg at expiration for a given underlying price."""
    iv = intrinsic(leg.type, leg.strike, price)
    per_share = (iv - leg.premium) if leg.side == "long" else (leg.premium - iv)
    return per_share * leg.contracts * multiplier


def net_premium(position: Position) -> float:
    """Total premium cash flow of the whole position (sum of legs).

    Positive = net credit received, negative = net debit paid.
    """
    return sum(leg_premium_cashflow(leg, position.multiplier) for leg in position.legs)


def position_pnl_at_expiration(position: Position, price: float) -> float:
    """Total position P/L at expiration for a given underlying price."""
    pnl = sum(
        leg_pnl_at_expiration(leg, price, position.multiplier) for leg in position.legs
    )
    if position.stock is not None:
        pnl += (price - position.stock.cost_basis) * position.stock.shares
    return pnl


def payoff_curve(
    position: Position, min_price: float, max_price: float, steps: int = 80
) -> list[dict]:
    """A payoff curve: P/L sampled across a range of underlying prices."""
    lo = max(0.0, min_price)
    hi = max(lo + 1e-9, max_price)
    points = []
    for i in range(steps + 1):
        price = lo + (hi - lo) * i / steps
        points.append({"price": price, "pnl": position_pnl_at_expiration(position, price)})
    return points


# ---------------------------------------------------------------------------
# Position summary metrics
# ---------------------------------------------------------------------------


@dataclass
class PositionSummary:
    net_premium: float
    breakevens: list[float]
    max_profit: Optional[float]  # None = unbounded
    max_loss: Optional[float]  # None = unbounded


def summarize_position(position: Position) -> PositionSummary:
    """Summarize a position numerically.

    Breakevens are found by sign changes between the option strikes (where the
    piecewise-linear payoff can only bend); profit/loss extremes are read off
    the knots, then the unbounded tails are detected from the far slope.
    """
    strikes = [leg.strike for leg in position.legs]
    cost_basis = position.stock.cost_basis if position.stock else 0.0
    refs = [0.0, *strikes, cost_basis, (max([*strikes, cost_basis]) * 2 + 1)]
    knots = sorted(set(refs))

    breakevens: list[float] = []
    for a, b in zip(knots, knots[1:]):
        fa = position_pnl_at_expiration(position, a)
        fb = position_pnl_at_expiration(position, b)
        if fa == 0:
            breakevens.append(a)
        if fa * fb < 0:
            t = fa / (fa - fb)
            breakevens.append(a + t * (b - a))
    last_knot = knots[-1]
    if position_pnl_at_expiration(position, last_knot) == 0:
        breakevens.append(last_knot)

    sample_xs = [*knots, *breakevens]
    values = [position_pnl_at_expiration(position, x) for x in sample_xs]
    max_profit: Optional[float] = max(values)
    max_loss: Optional[float] = min(values)

    def slope_at(x: float) -> float:
        h = max(1.0, x * 0.01)
        return (
            position_pnl_at_expiration(position, x + h)
            - position_pnl_at_expiration(position, x)
        ) / h

    up_slope = slope_at(last_knot + 1000)
    if up_slope > 1e-9:
        max_profit = None
    if up_slope < -1e-9:
        max_loss = None

    uniq = sorted({round(b, 4) for b in breakevens})
    return PositionSummary(
        net_premium=net_premium(position),
        breakevens=uniq,
        max_profit=max_profit,
        max_loss=max_loss,
    )


# ---------------------------------------------------------------------------
# Income-strategy return metrics (covered call & cash-secured put)
# ---------------------------------------------------------------------------


def _annualize(rate: float, days: float) -> float:
    return rate * (DAYS_PER_YEAR / days) if days > 0 else float("nan")


def covered_call(
    *,
    shares: float,
    current_price: float,
    strike: float,
    premium: float,
    days_to_expiration: float,
    cost_basis: Optional[float] = None,
    multiplier: int = SHARES_PER_CONTRACT,
) -> dict:
    """Covered-call economics, centered on the premium and the capital at work.

    Returns are measured against the *current* share price -- the money actually
    tied up in the trade today -- not your historical cost basis. Cost basis is
    optional accounting detail: pass it and you also get your net cost basis and
    the total gain/return including the share appreciation since you bought.
    """
    contracts = shares / multiplier
    premium_collected = premium * shares
    capital_at_risk = current_price * shares

    # Everything the decision actually hinges on is relative to today's price.
    static_return = premium / current_price if current_price else float("nan")
    gain_if_called = (strike - current_price + premium) * shares
    return_if_called = (
        (strike - current_price + premium) / current_price
        if current_price
        else float("nan")
    )

    result = {
        "contracts": contracts,
        "premium_collected": premium_collected,
        "capital_at_risk": capital_at_risk,
        "breakeven": current_price - premium,
        "max_profit_if_unchanged": premium_collected,
        "max_profit_if_called": gain_if_called,
        "static_return": static_return,
        "return_if_called": return_if_called,
        "static_return_annualized": _annualize(static_return, days_to_expiration),
        "return_if_called_annualized": _annualize(return_if_called, days_to_expiration),
        "downside_protection": premium / current_price if current_price else float("nan"),
    }

    # Cost basis is optional: it only changes your *accounting* gain (vs. what you
    # actually paid), not the merits of selling the call today.
    if cost_basis is not None and cost_basis > 0:
        total_return_if_called = (strike - cost_basis + premium) / cost_basis
        result["net_cost_basis"] = cost_basis - premium
        result["total_gain_if_called"] = (strike - cost_basis + premium) * shares
        result["total_return_if_called"] = total_return_if_called
        result["total_return_if_called_annualized"] = _annualize(
            total_return_if_called, days_to_expiration
        )

    return result


def cash_secured_put(
    *,
    strike: float,
    premium: float,
    contracts: float,
    days_to_expiration: float,
    multiplier: int = SHARES_PER_CONTRACT,
) -> dict:
    shares = contracts * multiplier
    premium_collected = premium * shares
    return_on_cash = premium / strike if strike else float("nan")
    return {
        "premium_collected": premium_collected,
        "cash_secured": strike * shares,
        "breakeven": strike - premium,
        "effective_buy_price": strike - premium,
        "max_profit": premium_collected,
        "return_on_cash": return_on_cash,
        "return_on_cash_annualized": _annualize(return_on_cash, days_to_expiration),
    }


# ---------------------------------------------------------------------------
# Black-Scholes theoretical pricing (estimate the premium)
# ---------------------------------------------------------------------------


def norm_cdf(x: float) -> float:
    """Standard normal cumulative distribution function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return 0.3989422804014327 * math.exp(-x * x / 2.0)


def black_scholes(
    *,
    type: OptionType,
    spot: float,
    strike: float,
    days_to_expiration: float,
    volatility: float,  # annualized implied vol, decimal (0.30 = 30%)
    risk_free_rate: float = 0.04,
    dividend_yield: float = 0.0,
) -> dict:
    r = risk_free_rate
    q = dividend_yield
    S = spot
    K = strike
    T = days_to_expiration / DAYS_PER_YEAR
    sigma = volatility

    # Degenerate cases: no time, no vol, or non-positive spot/strike -> intrinsic.
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

    sqrt_t = math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + sigma * sigma / 2.0) * T) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    disc_r = math.exp(-r * T)
    disc_q = math.exp(-q * T)

    if type == "call":
        price = S * disc_q * norm_cdf(d1) - K * disc_r * norm_cdf(d2)
        delta = disc_q * norm_cdf(d1)
        rho = K * T * disc_r * norm_cdf(d2) / 100.0
        theta = (
            -(S * disc_q * _norm_pdf(d1) * sigma) / (2 * sqrt_t)
            - r * K * disc_r * norm_cdf(d2)
            + q * S * disc_q * norm_cdf(d1)
        ) / DAYS_PER_YEAR
    else:
        price = K * disc_r * norm_cdf(-d2) - S * disc_q * norm_cdf(-d1)
        delta = disc_q * (norm_cdf(d1) - 1.0)
        rho = -K * T * disc_r * norm_cdf(-d2) / 100.0
        theta = (
            -(S * disc_q * _norm_pdf(d1) * sigma) / (2 * sqrt_t)
            + r * K * disc_r * norm_cdf(-d2)
            - q * S * disc_q * norm_cdf(-d1)
        ) / DAYS_PER_YEAR

    gamma = disc_q * _norm_pdf(d1) / (S * sigma * sqrt_t)
    vega = S * disc_q * _norm_pdf(d1) * sqrt_t / 100.0

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
