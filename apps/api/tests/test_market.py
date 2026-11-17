"""The market-data layer against the fake Tiingo and Finnhub in tests/fakes.py (no network, no API keys)."""
import json
from dataclasses import replace
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from datasources import clients, market
from portfolio.positions import Lot, resolve_lot
from tests.fakes import bar


@pytest.fixture
def fake(fake_market):
    return fake_market


def test_cached_history_round_trips(fake):
    first = market.get_price_history("NVDA", "2024-06-03")
    fake["histories"]["NVDA"] = None      # provider gone: the second call must come from the cache
    second = market.get_price_history("NVDA", "2024-06-03")
    pd.testing.assert_frame_equal(first, second, check_freq=False)


def test_backdated_purchase_before_a_split(fake):
    r = resolve_lot(Lot("nvda", date(2024, 6, 1), shares=10))   # a Saturday
    assert r.trade_date == date(2024, 6, 3)
    assert r.price_paid == pytest.approx(1150.0)                 # what it actually cost that day
    assert r.shares_now == pytest.approx(100.0)                  # 10 shares became 100 after the split
    assert r.cost_basis == pytest.approx(11_500.0)
    assert "next trading day" in r.note
    by_amount = resolve_lot(Lot("NVDA", date(2024, 6, 3), amount=2300))
    assert by_amount.shares_bought == pytest.approx(2.0) and by_amount.shares_now == pytest.approx(20.0)


def test_unknown_ticker(fake):
    assert market.get_price_history("ZZZZQ", "2024-01-02").empty
    with pytest.raises(ValueError, match="No closing price"):
        resolve_lot(Lot("ZZZZQ", date(2024, 1, 2), shares=1))
    with pytest.raises(ValueError, match="No live quote"):
        market.get_quote("ZZZZQ")


def test_quote_uses_last_completed_close(fake):
    today = datetime.now(market.ET).date()
    fake["histories"]["SPY"] = [bar((today - timedelta(days=d)).isoformat(), 100.0 - d) for d in (3, 2, 1)]
    fake["finnhub"].quotes["SPY"] = {"c": 101.0, "pc": 100.0}
    q = market.get_quote("SPY")
    assert q["price"] == 101.0 and q["previous_close"] == 99.0      # yesterday's close from our history
    assert q["change"] == pytest.approx(2.0) and q["change_pct"] == pytest.approx(2.0 / 99.0 * 100)


def test_company_info_for_a_stock_and_an_etf(fake):
    aapl = market.get_company_info("aapl")
    assert aapl["name"] == "Apple Inc" and aapl["quote_type"] == "EQUITY" and aapl["sector"] == "Technology"
    assert aapl["market_cap"] == 3.5e12 and aapl["trailing_pe"] == 35.2 and aapl["dividend_yield"] == 0.44
    spy = market.get_company_info("SPY")
    assert spy["quote_type"] == "ETF" and spy["name"] == "SPDR S&P 500 ETF Trust" and spy["sector"] is None


def test_earnings_calendar_filters_and_labels(fake, monkeypatch):
    monkeypatch.setattr(market, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: datetime(2026, 11, 17, 9, tzinfo=tz))}))
    rows = market.get_earnings_calendar(["nvda", "aapl", "msft"], days_ahead=14)
    assert [(r["ticker"], r["status"]) for r in rows] == [("AAPL", "reported"), ("NVDA", "upcoming")]
    assert rows[1]["timing"] == "after market close" and rows[1]["quarter"] == "Q3 2027"
    assert rows[0]["eps_actual"] == 1.6


async def test_earnings_tool_uses_holdings_and_watchlist(fake, make_user, monkeypatch):
    from agent.tools import make_local_tools

    monkeypatch.setattr(market, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: datetime(2026, 11, 17, 9, tzinfo=tz))}))
    alice = await make_user()
    await alice.add_holding("NVDA", date(2024, 6, 3), shares=1)
    await alice.add_to_watchlist("AAPL")
    tool = next(t for t in make_local_tools(alice.user_id) if t.name == "get_earnings_calendar")
    out = json.loads(await tool.ainvoke({}))
    assert out["checked"] == ["AAPL", "NVDA"]
    assert [e["ticker"] for e in out["earnings"]] == ["AAPL", "NVDA"] and out["source"] == "Finnhub earnings calendar"


def test_tiingo_errors_are_readable(monkeypatch):
    class Resp:
        def __init__(self, code):
            self.status_code = code

    monkeypatch.setattr(clients, "settings", replace(clients.settings, tiingo_api_key="k"))
    monkeypatch.setattr(clients._session, "get", lambda *a, **k: Resp(429))
    with pytest.raises(clients.DataProviderError, match="rate-limited"):
        clients.tiingo_get("/tiingo/daily/NVDA/prices")
    monkeypatch.setattr(clients._session, "get", lambda *a, **k: Resp(404))
    assert clients.tiingo_get("/tiingo/daily/ZZZZ/prices") is None
    monkeypatch.setattr(clients, "settings", replace(clients.settings, tiingo_api_key=""))
    with pytest.raises(clients.DataProviderError, match="TIINGO_API_KEY"):
        clients.tiingo_get("/tiingo/daily/NVDA/prices")