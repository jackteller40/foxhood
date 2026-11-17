"""Prices, splits, quotes, company info and the earnings calendar.

Sources: Tiingo (end-of-day history) and Finnhub (quotes, profiles, metrics, earnings), both through
their official APIs and cached in the shared Postgres market cache. The functions keep the shapes the
rest of the app was written against:

get_price_history -> DataFrame indexed by plain dates with columns
    Open, High, Low, Close   split-adjusted, NOT dividend-adjusted (what you'd see on a chart today)
    Adj Close                split- AND dividend-adjusted (for total return)
    Volume, Dividends        dividends as cash per share on the ex-date
    Stock Splits             split ratio on its effective date, 0.0 on other days (10.0 = 10-for-1)"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from datasources.cache import cached
from datasources.clients import DataProviderError, finnhub_client, tiingo_get

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

HISTORY_COLUMNS = ["Open", "High", "Low", "Close", "Adj Close", "Volume", "Dividends", "Stock Splits"]
HISTORY_FLOOR = date(2005, 1, 1)   # one cached download per ticker covers any purchase since 2005


def _tiingo_symbol(ticker: str) -> str:
    return ticker.strip().upper().replace(".", "-")   # BRK.B -> BRK-B


def _as_date(value: date | str) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


@cached(ttl_seconds=3 * 3600)
def _daily_history(ticker: str, since: str) -> pd.DataFrame:
    """Full daily history from `since` to today, adjusted into our column layout (one Tiingo call)."""
    rows = tiingo_get(f"/tiingo/daily/{_tiingo_symbol(ticker)}/prices",
                      {"startDate": since, "resampleFreq": "daily", "format": "json"})
    if not rows:
        return pd.DataFrame(columns=HISTORY_COLUMNS)
    raw = pd.DataFrame(rows)
    raw.index = pd.to_datetime(raw["date"].str[:10])
    raw = raw.sort_index()

    split = raw["splitFactor"].astype(float).replace(0, 1.0)
    # Product of every split strictly AFTER each day: divide raw prices by it to put them in today's shares.
    later_splits = split[::-1].cumprod()[::-1].shift(-1, fill_value=1.0)
    df = pd.DataFrame({
        "Open": raw["open"] / later_splits,
        "High": raw["high"] / later_splits,
        "Low": raw["low"] / later_splits,
        "Close": raw["close"] / later_splits,
        "Adj Close": raw["adjClose"].astype(float),
        "Volume": raw["volume"].astype(float) * later_splits,
        "Dividends": raw["divCash"].astype(float),
        "Stock Splits": split.where(split != 1.0, 0.0),
    }, index=raw.index)
    df.index.name = None
    return df.dropna(subset=["Close"])


def get_price_history(ticker: str, start: date | str, end: date | str | None = None) -> pd.DataFrame:
    """Daily bars from start (inclusive) to end (exclusive). Empty for an unknown ticker."""
    start_d = _as_date(start)
    since = min(start_d, HISTORY_FLOOR)
    df = _daily_history(ticker.strip().upper(), since.isoformat())
    if df.empty:
        return df
    df = df.astype(float)   # JSON in the cache turns 115.0 into 115; keep every column float
    df = df[df.index >= pd.Timestamp(start_d)]
    if end is not None:
        df = df[df.index < pd.Timestamp(_as_date(end))]
    return df


def get_splits(ticker: str) -> pd.Series:
    """Split history: index = effective date, value = ratio (10.0 means 10-for-1)."""
    df = _daily_history(ticker.strip().upper(), HISTORY_FLOOR.isoformat())
    if df.empty:
        return pd.Series(dtype=float)
    s = df["Stock Splits"].astype(float)
    return s[s > 0]


@cached(ttl_seconds=60)
def _finnhub_quote(ticker: str) -> dict:
    return finnhub_client().quote(ticker)


def get_quote(ticker: str) -> dict:
    """Latest price vs. the last completed daily close before today (ET). The reference close comes from
    our own history, so day P&L lines up with the value-history chart."""
    t = ticker.strip().upper()
    q = _finnhub_quote(t)
    last = float(q.get("c") or 0)
    if last <= 0:
        raise ValueError(f"No live quote for {t}. Check the ticker.")

    today_et = datetime.now(ET).date()
    bars = get_price_history(t, start=today_et - timedelta(days=10))
    prior = bars[bars.index < pd.Timestamp(today_et)]["Close"] if not bars.empty else pd.Series(dtype=float)
    prev = float(prior.iloc[-1]) if not prior.empty else float(q.get("pc") or last)
    return {
        "ticker": t,
        "price": last,
        "previous_close": prev,
        "change": last - prev,
        "change_pct": (last / prev - 1) * 100 if prev else None,
        "currency": "USD",
    }


@cached(ttl_seconds=30 * 24 * 3600)
def _security_type(ticker: str) -> str:
    """'EQUITY', 'ETF' or 'OTHER', from Finnhub's symbol search (ETFs are listed as 'ETP')."""
    try:
        hits = finnhub_client().symbol_lookup(ticker).get("result", [])
    except Exception:
        return "OTHER"
    match = next((h for h in hits if (h.get("symbol") or "").upper() == ticker), None)
    kind = ((match or {}).get("type") or "").upper()
    if kind == "ETP" or "ETF" in kind:
        return "ETF"
    return "EQUITY" if "STOCK" in kind or kind in {"COMMON STOCK", "ADR", "REIT"} else "OTHER"


@cached(ttl_seconds=7 * 24 * 3600)
def get_company_info(ticker: str) -> dict:
    """Name, sector and basic valuation fields. ETFs have no sector or P/E; that's expected.
    'sector' is Finnhub's industry group (e.g. Semiconductors, Banking), a bit finer than GICS sectors."""
    t = ticker.strip().upper()
    client = finnhub_client()
    profile = client.company_profile2(symbol=t) or {}
    metric = (client.company_basic_financials(t, "all") or {}).get("metric") or {}
    quote_type = _security_type(t)
    if not profile:   # ETFs and some smaller names have no Finnhub profile on the free tier
        meta = tiingo_get(f"/tiingo/daily/{_tiingo_symbol(t)}") or {}
        profile = {"name": meta.get("name")}
    cap_millions = profile.get("marketCapitalization")
    return {
        "ticker": t,
        "name": profile.get("name") or t,
        "quote_type": quote_type,
        "sector": profile.get("finnhubIndustry") or None,
        "industry": profile.get("finnhubIndustry") or None,
        "market_cap": cap_millions * 1_000_000 if cap_millions else None,
        "trailing_pe": metric.get("peTTM") or metric.get("peBasicExclExtraTTM"),
        "forward_pe": metric.get("forwardPE"),
        "beta": metric.get("beta"),
        "dividend_yield": metric.get("currentDividendYieldTTM"),   # already a percent: 0.75 = 0.75%
        "week52_high": metric.get("52WeekHigh"),
        "week52_low": metric.get("52WeekLow"),
    }


EARNINGS_TIMING = {"bmo": "before market open", "amc": "after market close", "dmh": "during market hours"}


@cached(ttl_seconds=6 * 3600)
def _earnings_window(start: str, end: str) -> list[dict]:
    """Every company's scheduled or reported earnings in [start, end] (one call, shared by all users)."""
    data = finnhub_client().earnings_calendar(_from=start, to=end, symbol="", international=False) or {}
    return [{
        "ticker": (e.get("symbol") or "").upper(),
        "date": e.get("date"),
        "timing": EARNINGS_TIMING.get((e.get("hour") or "").lower(), "time not announced"),
        "quarter": f"Q{e.get('quarter')} {e.get('year')}" if e.get("quarter") else None,
        "eps_estimate": e.get("epsEstimate"),
        "eps_actual": e.get("epsActual"),
        "revenue_estimate": e.get("revenueEstimate"),
        "revenue_actual": e.get("revenueActual"),
    } for e in data.get("earningsCalendar", []) if e.get("symbol") and e.get("date")]


def get_earnings_calendar(tickers: list[str], days_ahead: int = 14, days_back: int = 3) -> list[dict]:
    """Earnings for these tickers from `days_back` days ago to `days_ahead` days out, soonest first.
    Entries with eps_actual already reported; the rest are upcoming."""
    today = datetime.now(ET).date()
    wanted = {t.strip().upper() for t in tickers}
    rows = _earnings_window((today - timedelta(days=days_back)).isoformat(),
                            (today + timedelta(days=days_ahead)).isoformat())
    hits = [{**r, "status": "reported" if r["eps_actual"] is not None else "upcoming"}
            for r in rows if r["ticker"] in wanted]
    return sorted(hits, key=lambda r: (r["date"], r["ticker"]))


__all__ = ["ET", "DataProviderError", "get_company_info", "get_earnings_calendar", "get_price_history",
           "get_quote", "get_splits"]