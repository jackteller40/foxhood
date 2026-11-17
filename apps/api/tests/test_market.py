"""The market-data layer against fake Tiingo and Finnhub responses (no network, no API keys).
The fakes use the providers' documented response shapes."""
import json
from dataclasses import replace
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from datasources import cache, clients, market
from portfolio.positions import Lot, resolve_lot


def bar(day: str, close: float, *, split: float = 1.0, div: float = 0.0, adj: float | None = None) -> dict:
    """One Tiingo daily row (raw prices are NOT split-adjusted; adjClose is split+dividend adjusted)."""
    return {"date": f"{day}T00:00:00.000Z", "open": close, "high": close, "low": close, "close": close,
            "volume": 1000, "adjClose": adj if adj is not None else close, "adjHigh": close, "adjLow": close,
            "adjOpen": close, "adjVolume": 1000, "divCash": div, "splitFactor": split}


# NVDA's real 10-for-1 split took effect on Monday 2024-06-10.
NVDA = [bar("2024-06-03", 1150.0, adj=114.9), bar("2024-06-04", 1160.0, adj=115.9),
        bar("2024-06-07", 1200.0, adj=119.9), bar("2024-06-10", 121.0, split=10.0, adj=120.9),
        bar("2024-06-11", 120.0, div=0.01, adj=120.0)]


class FakeFinnhub:
    def __init__(self):
        self.quotes = {"NVDA": {"c": 130.0, "pc": 128.0}, "SPY": {"c": 101.0, "pc": 100.0}}
        self.profiles = {"AAPL": {"name": "Apple Inc", "finnhubIndustry": "Technology",
                                  "marketCapitalization": 3_500_000.0}}
        self.types = {"AAPL": "Common Stock", "SPY": "ETP", "NVDA": "Common Stock"}
        self.calendar = [
            {"symbol": "NVDA", "date": "2026-11-19", "hour": "amc", "quarter": 3, "year": 2027,
             "epsEstimate": 1.25, "epsActual": None, "revenueEstimate": 5.4e10, "revenueActual": None},
            {"symbol": "AAPL", "date": "2026-11-16", "hour": "bmo", "quarter": 4, "year": 2026,
             "epsEstimate": 1.5, "epsActual": 1.6, "revenueEstimate": 9e10, "revenueActual": 9.2e10},
            {"symbol": "WMT", "date": "2026-11-18", "hour": "bmo", "quarter": 3, "year": 2027,
             "epsEstimate": 0.6, "epsActual": None, "revenueEstimate": 1.7e11, "revenueActual": None},
        ]

    def quote(self, symbol):
        return self.quotes.get(symbol, {"c": 0, "pc": 0})

    def company_profile2(self, symbol):
        return self.profiles.get(symbol, {})

    def company_basic_financials(self, symbol, metric):
        return {"metric": {"peTTM": 35.2, "beta": 1.2, "52WeekHigh": 260.0, "52WeekLow": 160.0,
                           "currentDividendYieldTTM": 0.44}} if symbol == "AAPL" else {"metric": {}}

    def symbol_lookup(self, query):
        return {"result": [{"symbol": query, "type": self.types.get(query, "")}]}

    def earnings_calendar(self, _from, to, symbol, international=False):
        return {"earningsCalendar": [e for e in self.calendar if _from <= e["date"] <= to]}


@pytest.fixture
def fake(monkeypatch):
    cache.clear_cache()   # cached results from another test would hide the fakes
    histories = {"NVDA": NVDA}
    meta = {"SPY": {"name": "SPDR S&P 500 ETF Trust"}}

    def tiingo_get(path, params=None):
        parts = path.strip("/").split("/")          # tiingo/daily/<TICKER>[/prices]
        ticker = parts[2]
        if path.endswith("/prices"):
            return histories.get(ticker)
        return meta.get(ticker)

    fh = FakeFinnhub()
    monkeypatch.setattr(market, "tiingo_get", tiingo_get)
    monkeypatch.setattr(market, "finnhub_client", lambda: fh)
    yield {"histories": histories, "finnhub": fh}
    cache.clear_cache()


def test_history_is_split_adjusted_and_end_exclusive(fake):
    df = market.get_price_history("NVDA", "2024-06-03", "2024-06-10")
    assert list(df.index.strftime("%Y-%m-%d")) == ["2024-06-03", "2024-06-04", "2024-06-07"]
    assert df["Close"].tolist() == pytest.approx([115.0, 116.0, 120.0])   # pre-split prices / 10
    assert df["Adj Close"].iloc[0] == pytest.approx(114.9)
    after = market.get_price_history("NVDA", "2024-06-10")
    assert after["Close"].tolist() == pytest.approx([121.0, 120.0])        # already in today's shares
    assert after["Dividends"].tolist() == [0.0, 0.01]
    splits = market.get_splits("NVDA")
    assert list(splits.index.strftime("%Y-%m-%d")) == ["2024-06-10"] and splits.iloc[0] == 10.0


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