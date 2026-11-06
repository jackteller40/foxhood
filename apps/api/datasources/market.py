"Prices, splits, quotes and company info from yfinance."
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from datasources.cache import cached

ET = ZoneInfo("America/New_York")
logging.getLogger("yfinance").setLevel(logging.CRITICAL)  # hides the 404 noise from bad tickers

HISTORY_COLUMNS = ["Open", "High", "Low", "Close", "Adj Close", "Volume", "Dividends", "Stock Splits"]


def _to_naive_dates(index: pd.DatetimeIndex) -> pd.DateTimeIndex:
    """yfinance returns tz-aware timestamps; strip tz and time so we can index by plain dates"""
    if index.tz is not None:
        index = index.tz_localize(None)
    return index.normalize()

@cached(ttl_seconds=15 * 60)
def get_price_history(ticker: str, start: date | str, end: date | str | None = None) -> pd.DateFrame:
    """Daily bars. 'end' is exclusive (yfinance convention).
    'Close' is split adjusted but not dividend-adjusted; Adj Close is both."""
    df = yf.Ticker(ticker.upper()).history(start=start, end=end, interval="1d", auto_adjust=False)
    if df.empty:
        return df
    df.index = _to_naive_dates(df.index)
    df = df.dropna(subset=["Close"])  # drop today's partial bar
    return df [[c for c in HISTORY_COLUMNS if c in df.columns]]

@cached(ttl_seconds=24 * 3600)
def get_splits(ticker: str) -> pd.Series:
    """Split history: index = effective date, value = ratio (10.0 means 10 for 1)."""
    s = yf.Ticker(ticker.upper()).splits
    if s.empty:
        return s
    s.index = _to_naive_dates(s.index)
    return s

@cached(ttl_seconds=60)
def get_quote(ticker: str) -> dict:
    """Last price vs. the last completed daily close before today (ET).
    Uses our own history for the reference price so day P&L matches the value-history chart."""
    t = ticker.upper()
    fi = yf.Ticker(t).fast_info
    last = float(fi.last_price)

    today_et = datetime.now(ET).date()
    bars = get_price_history(t, start=today_et - timedelta(days=10))
    prior = bars[bars.index < pd.Timestamp(today_et)]["Close"] if not bars.empty else pd.Series(dtype=float)
    prev = float(prior.iloc[-1]) if not prior.empty else float(fi.previous_close)

    return {
        "ticker": t,
        "price": last,
        "previous_close": prev,
        "change": last - prev,
        "change_pct": (last / prev - 1) * 100 if prev else None,
        "currency": fi.currency,
    }
    
@cached(ttl_seconds=24 * 3600)
def get_company_info(ticker: str) -> dict:
    """Name, sector and basic valuation fields. ETFs won't have sector/PE; that's expected."""
    info = yf.Ticker(ticker.upper()).info or {}
    fields = {
        "name": "longName",
        "quote_type": "quoteType",          # EQUITY, ETF, ...
        "sector": "sector",
        "industry": "industry",
        "market_cap": "marketCap",
        "trailing_pe": "trailingPE",
        "forward_pe": "forwardPE",
        "beta": "beta",
        "dividend_yield": "dividendYield",  # yfinance returns a percent: 0.75 = 0.75%
        "week52_high": "fiftyTwoWeekHigh",
        "week52_low": "fiftyTwoWeekLow",
    }
    out = {key: info.get(src) for key, src in fields.items()}
    out["ticker"] = ticker.upper()
    return out