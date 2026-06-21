"""Tests for the Massive API client -- mocked at the HTTP layer.

No live network calls: marketdata.get_option_contracts is exercised entirely
against a fake urlopen so these run offline and don't depend on a real key.
"""

import json
import urllib.error

import pytest

import marketdata as md


class FakeResponse:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    with pytest.raises(md.MarketDataError, match="MASSIVE_API_KEY"):
        md.get_option_contracts("AAPL")


def test_fetches_and_normalizes_results(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", "test-key")
    page = {
        "status": "OK",
        "results": [
            {"ticker": "O:AAPL250117C00100000", "strike_price": 100,
             "expiration_date": "2025-01-17", "contract_type": "call"},
            {"ticker": "O:AAPL250117C00110000", "strike_price": 110,
             "expiration_date": "2025-01-17", "contract_type": "call"},
        ],
    }
    monkeypatch.setattr(md.urllib.request, "urlopen", lambda url, timeout: FakeResponse(page))

    results = md.get_option_contracts("aapl")  # lowercase -> uppercased internally
    assert len(results) == 2
    assert results[0]["strike_price"] == 100


def test_paginates_via_next_url(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", "test-key")
    page1 = {
        "status": "OK",
        "results": [{"ticker": "A", "strike_price": 100, "expiration_date": "2025-01-17"}],
        "next_url": "https://api.massive.com/v3/reference/options/contracts?cursor=abc",
    }
    page2 = {
        "status": "OK",
        "results": [{"ticker": "B", "strike_price": 110, "expiration_date": "2025-01-17"}],
    }
    calls = iter([page1, page2])
    monkeypatch.setattr(
        md.urllib.request, "urlopen", lambda url, timeout: FakeResponse(next(calls))
    )

    results = md.get_option_contracts("AAPL", limit=10)
    assert [r["ticker"] for r in results] == ["A", "B"]


def test_raises_on_http_error(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", "test-key")

    def boom(url, timeout):
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)

    monkeypatch.setattr(md.urllib.request, "urlopen", boom)
    with pytest.raises(md.MarketDataError, match="403"):
        md.get_option_contracts("AAPL")


def test_raises_on_empty_ticker(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", "test-key")
    with pytest.raises(md.MarketDataError, match="required"):
        md.get_option_contracts("   ")
