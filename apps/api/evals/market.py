"""A small, fixed market for evals: a year of prices, live quotes, company data, earnings and news.
Same response shapes as Tiingo and Finnhub, so all of Foxhood's real data code runs unchanged."""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta

from datasources import cache, market, news
from datasources.market import ET

TODAY = datetime.now(ET).date()

# ticker: (price a year ago, last close, today's move %, name, Finnhub industry or None for ETFs)
SPECS = {
    "NVDA": (90.0, 140.0, -2.4, "NVIDIA Corp", "Semiconductors"),
    "AAPL": (180.0, 228.0, 0.6, "Apple Inc", "Technology"),
    "MSFT": (400.0, 430.0, 0.3, "Microsoft Corp", "Technology"),
    "AMD": (140.0, 162.0, 1.9, "Advanced Micro Devices Inc", "Semiconductors"),
    "VOO": (470.0, 540.0, -0.2, "Vanguard S&P 500 ETF", None),
    "SPY": (515.0, 590.0, -0.2, "SPDR S&P 500 ETF Trust", None),
}
PE = {"AAPL": 35.2, "MSFT": 33.8, "NVDA": 48.5, "AMD": 41.0}


def trading_days(start: date, end: date) -> list[date]:
    from core.market_clock import is_trading_day
    d, out = start, []
    while d < end:
        if is_trading_day(d):
            out.append(d)
        d += timedelta(days=1)
    return out


def next_trading_day(after: date, n: int = 1) -> date:
    from core.market_clock import next_trading_day as nxt
    d = after
    for _ in range(n):
        d = nxt(d)
    return d


DAYS = trading_days(TODAY - timedelta(days=380), TODAY)


def _bars(first: float, last: float) -> list[dict]:
    n = len(DAYS)
    rows = []
    for i, d in enumerate(DAYS):
        trend = first + (last - first) * i / (n - 1)
        close = round(trend * (1 + 0.03 * math.sin(i / 9)) if i < n - 1 else last, 2)
        rows.append({"date": f"{d.isoformat()}T00:00:00.000Z", "open": close, "high": close, "low": close,
                     "close": close, "volume": 1_000_000, "adjClose": close, "adjHigh": close, "adjLow": close,
                     "adjOpen": close, "adjVolume": 1_000_000, "divCash": 0.0, "splitFactor": 1.0})
    return rows


HISTORIES = {t: _bars(a, b) for t, (a, b, *_rest) in SPECS.items()}
EARNINGS_DAY = next_trading_day(TODAY, 2)      # NVDA reports two trading days from now


class FakeFinnhub:
    def quote(self, symbol):
        if symbol not in SPECS:
            return {"c": 0, "pc": 0}
        _a, last, move, *_ = SPECS[symbol]
        return {"c": round(last * (1 + move / 100), 2), "pc": last}

    def company_profile2(self, symbol):
        if symbol not in SPECS or SPECS[symbol][4] is None:
            return {}
        _a, last, _m, name, industry = SPECS[symbol]
        return {"name": name, "finnhubIndustry": industry, "marketCapitalization": last * 20_000}

    def company_basic_financials(self, symbol, metric):
        if symbol not in PE:
            return {"metric": {}}
        last = SPECS[symbol][1]
        return {"metric": {"peTTM": PE[symbol], "beta": 1.3, "52WeekHigh": round(last * 1.08, 2),
                           "52WeekLow": round(SPECS[symbol][0] * 0.95, 2)}}

    def symbol_lookup(self, query):
        kind = "ETP" if query in SPECS and SPECS[query][4] is None else "Common Stock"
        return {"result": [{"symbol": query, "type": kind}]} if query in SPECS else {"result": []}

    def earnings_calendar(self, _from, to, symbol, international=False):
        rows = [{"symbol": "NVDA", "date": EARNINGS_DAY.isoformat(), "hour": "amc", "quarter": 4, "year": 2027,
                 "epsEstimate": 1.31, "epsActual": None, "revenueEstimate": 6.1e10, "revenueActual": None}]
        return {"earningsCalendar": [r for r in rows if _from <= r["date"] <= to]}

    def company_news(self, ticker, _from, to):
        stamp = int(datetime.now().timestamp()) - 3600
        stories = {
            "NVDA": [("Nvidia shares slip as investors book profits before earnings",
                      "Shares fell about 2% ahead of the company's report later this week.")],
            "AAPL": [("Apple expands services bundle in Europe", "The bundle launches next month in 12 countries.")],
        }
        return [{"headline": h, "summary": s, "source": "Eval Wire", "url": "https://example.com", "datetime": stamp}
                for h, s in stories.get(ticker, [])]

    def general_news(self, category, min_id=0):
        return [{"headline": "Stocks drift lower as traders await inflation data", "summary": "Major indexes slipped.",
                 "source": "Eval Wire", "url": "https://example.com", "datetime": int(datetime.now().timestamp())}]


def install() -> None:
    def tiingo_get(path, params=None):
        ticker = path.strip("/").split("/")[2]
        if path.endswith("/prices"):
            return HISTORIES.get(ticker)
        return {"name": SPECS[ticker][3]} if ticker in SPECS else None

    fake = FakeFinnhub()
    market.tiingo_get = tiingo_get
    market.finnhub_client = lambda: fake
    news._get_client = lambda: fake
    cache.clear_cache()
