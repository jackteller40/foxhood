"""Fake Tiingo and Finnhub for tests, using the providers' documented response shapes.
conftest.py installs them for EVERY test, so no test can reach a real provider or need an API key."""

from datasources import cache, market


def bar(day: str, close: float, *, split: float = 1.0, div: float = 0.0, adj: float | None = None) -> dict:
    """One Tiingo daily row (raw prices are NOT split-adjusted; adjClose is split+dividend adjusted)."""
    return {"date": f"{day}T00:00:00.000Z", "open": close, "high": close, "low": close, "close": close,
            "volume": 1000, "adjClose": adj if adj is not None else close, "adjHigh": close, "adjLow": close,
            "adjOpen": close, "adjVolume": 1000, "divCash": div, "splitFactor": split}


# NVDA's real 10-for-1 split took effect on Monday 2024-06-10.
NVDA = [bar("2024-06-03", 1150.0, adj=114.9), bar("2024-06-04", 1160.0, adj=115.9),
        bar("2024-06-07", 1200.0, adj=119.9), bar("2024-06-10", 121.0, split=10.0, adj=120.9),
        bar("2024-06-11", 120.0, div=0.01, adj=120.0)]


# SPY over the same days (the benchmark every portfolio is compared against), no splits.
SPY = [bar("2024-06-03", 527.0), bar("2024-06-04", 528.0), bar("2024-06-07", 534.0),
       bar("2024-06-10", 535.0), bar("2024-06-11", 536.0)]


class FakeFinnhub:
    def __init__(self):
        self.quotes = {"NVDA": {"c": 130.0, "pc": 128.0}, "SPY": {"c": 600.0, "pc": 590.0}}
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


def install(monkeypatch) -> dict:
    cache.clear_cache()   # cached results from another test would hide the fakes
    histories = {"NVDA": NVDA, "SPY": SPY}
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
    return {"histories": histories, "finnhub": fh}