"""Thin client for the Massive market-data API (option contract reference data).

Stdlib-only -- no new dependency, in keeping with options.py. Reads the API key
from the MASSIVE_API_KEY environment variable; never accept it as a request
parameter so it can't leak into client-side code or logs.

This only covers the reference/contracts endpoint (real listed strikes and
expirations for an underlying ticker) -- there's no live premium, IV, or
bid/ask here yet. Black-Scholes still prices the contracts; this just swaps
the made-up strike/expiration grid for the ones that actually trade.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "https://api.massive.com"


class MarketDataError(Exception):
    """Raised for anything that should make a caller fall back to synthetic data."""


def _api_key() -> str:
    key = os.environ.get("MASSIVE_API_KEY", "").strip()
    if not key:
        raise MarketDataError("MASSIVE_API_KEY is not set")
    return key


def get_option_contracts(
    underlying_ticker: str,
    *,
    contract_type: str | None = None,
    expired: bool = False,
    limit: int = 250,
    timeout: float = 10.0,
) -> list[dict]:
    """Fetch listed option contracts for a ticker (strike, expiration, type).

    Paginates via `next_url` until `limit` results are collected or the API
    runs out of pages. Raises MarketDataError on any failure -- missing key,
    network error, bad ticker, rate limit -- so callers can degrade to the
    existing Black-Scholes-only flow instead of crashing.
    """
    ticker = underlying_ticker.strip().upper()
    if not ticker:
        raise MarketDataError("underlying_ticker is required")

    key = _api_key()
    params = {
        "underlying_ticker": ticker,
        "expired": "true" if expired else "false",
        "limit": str(min(limit, 1000)),
        "order": "asc",
        "sort": "strike_price",
        "apiKey": key,
    }
    if contract_type:
        params["contract_type"] = contract_type

    url = f"{BASE_URL}/v3/reference/options/contracts?{urllib.parse.urlencode(params)}"
    results: list[dict] = []

    while url and len(results) < limit:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise MarketDataError(f"Massive API error {e.code}: {e.reason}") from e
        except urllib.error.URLError as e:
            raise MarketDataError(f"Could not reach Massive API: {e.reason}") from e
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise MarketDataError(f"Massive API returned an unreadable response: {e}") from e

        if payload.get("status") not in ("OK", None):
            raise MarketDataError(f"Massive API status: {payload.get('status')}")

        results.extend(payload.get("results", []))
        next_url = payload.get("next_url")
        url = f"{next_url}&apiKey={key}" if next_url else None

    return results[:limit]
