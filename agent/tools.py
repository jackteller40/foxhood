"""Local tools for the main agent. Built per run with the user's id baked in,
so the LLM never chooses (or sees) whose data it's reading."""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta

import pandas as pd
from langchain_core.tools import tool
import threading

from datasources import market, news
from datasources.market import ET
from portfolio import metrics
from portfolio.positions import resolve_lot
from storage import db


def _clean(obj):
    """Round floats and drop NaN/inf so tool output is short and valid JSON."""
    if isinstance(obj, float):
        return None if math.isnan(obj) or math.isinf(obj) else round(obj, 2)
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    return obj


def _dump(obj) -> str:
    return json.dumps(_clean(obj), default=str)


def _performance(ticker: str) -> dict:
    t = ticker.strip().upper()
    today = datetime.now(ET).date()
    bars = market.get_price_history(t, start=today - timedelta(days=400))
    if bars.empty:
        raise ValueError(f"No price data for {t}. Check the ticker.")
    close = bars["Close"]
    q = market.get_quote(t)
    live = q["price"]

    def ret_since(days: int):
        ref = close[close.index <= pd.Timestamp(today - timedelta(days=days))]
        return None if ref.empty else (live / ref.iloc[-1] - 1) * 100

    ytd_ref = close[close.index < pd.Timestamp(date(today.year, 1, 1))]
    last_year = close[close.index >= pd.Timestamp(today - timedelta(days=365))]
    hi = max(float(last_year.max()), live)
    lo = min(float(last_year.min()), live)
    return {
        "ticker": t,
        "price": live,
        "change_1d_pct": q["change_pct"],
        "return_1w_pct": ret_since(7),
        "return_1m_pct": ret_since(30),
        "return_3m_pct": ret_since(91),
        "return_ytd_pct": None if ytd_ref.empty else (live / ytd_ref.iloc[-1] - 1) * 100,
        "return_1y_pct": ret_since(365),
        "high_52w": hi,
        "low_52w": lo,
        "pct_from_52w_high": (live / hi - 1) * 100,
    }


def make_local_tools(user_id: int) -> list:
    cache: dict = {}
    lock = threading.Lock()  # parallel tool calls share one portfolio computation

    def _portfolio():
        with lock:
            if "positions" not in cache:
                resolved, errors = [], []
                for lot in db.holdings_as_lots(user_id):
                    try:
                        resolved.append(resolve_lot(lot))
                    except Exception as e:
                        errors.append(f"{lot.ticker} bought {lot.purchase_date}: {e}")
                positions = metrics.positions_table(resolved) if resolved else pd.DataFrame()
                cache.update(resolved=resolved, errors=errors, positions=positions)
        return cache["resolved"], cache["errors"], cache["positions"]

    @tool
    def get_portfolio_summary() -> str:
        """Overall portfolio for the current user: total value, cost, P&L as price return AND
        total return (dividends reinvested), today's P&L, both compared to SPY, number of
        positions, the largest position and its weight, and sector exposure (%).
        Start here for any question about how the portfolio is doing."""
        resolved, errors, positions = _portfolio()
        if not resolved:
            return _dump({"error": "User has no holdings.", "lot_errors": errors})
        summary = metrics.portfolio_summary(resolved, positions)
        summary["sector_exposure_pct"] = metrics.sector_exposure(positions).to_dict()
        if errors:
            summary["lot_errors"] = errors
        return _dump(summary)

    @tool
    def get_positions() -> str:
        """Per-position detail for the current user's holdings: shares, average cost, price,
        market value, portfolio weight %, price return %, total return %, and today's move.
        Use for questions about specific holdings, movers, or concentration."""
        resolved, errors, positions = _portfolio()
        if positions.empty:
            return _dump({"positions": [], "lot_errors": errors})
        cols = ["ticker", "name", "sector", "lots", "shares", "avg_cost", "price", "market_value",
                "weight_pct", "pnl_pct", "total_return_pct", "day_change_pct", "day_pnl"]
        return _dump({"positions": positions[cols].to_dict(orient="records"), "lot_errors": errors})

    @tool
    def get_watchlist_snapshot() -> str:
        """Current user's watchlist with price, today's move, 1-week/1-month/YTD returns, and
        distance from the 52-week high for each ticker, plus the user's note on it."""
        items = db.list_watchlist(user_id)
        if not items:
            return _dump({"watchlist": [], "note": "Watchlist is empty."})
        rows = []
        for w in items:
            try:
                p = _performance(w["ticker"])
                p["user_note"] = w["note"]
                rows.append(p)
            except Exception as e:
                rows.append({"ticker": w["ticker"], "error": str(e)})
        return _dump({"watchlist": rows})

    @tool
    def get_price_performance(ticker: str) -> str:
        """Price performance for any ticker: price, 1-day change, 1-week, 1-month, 3-month, YTD
        and 1-year returns (%), 52-week high/low, and % below the 52-week high."""
        return _dump(_performance(ticker))

    @tool
    def get_company_profile(ticker: str) -> str:
        """Company or fund profile: name, type (EQUITY/ETF), sector, industry, market cap,
        trailing and forward P/E, beta, dividend yield (already a percent: 0.75 means 0.75%),
        and 52-week range. ETFs won't have sector or P/E."""
        return _dump(market.get_company_info(ticker))

    @tool
    def get_company_news(ticker: str, days: int = 3) -> str:
        """Recent news headlines for one ticker from the last `days` days (1-14), newest first,
        with source, URL, and a short summary. Results may include market roundups that only
        mention the ticker; judge relevance before using them."""
        items = news.get_company_news(ticker.strip().upper(), days=max(1, min(int(days), 14)), limit=6)
        for it in items:
            it["summary"] = (it.get("summary") or "")[:300]
        return _dump({"ticker": ticker.upper(), "articles": items})

    @tool
    def recall_memory(query: str) -> str:
        """Search this user's saved memories (preferences, facts, past brief takeaways) by
        keywords. Call before giving recommendations or ideas, and whenever the user's past
        preferences might change your answer. Example queries: 'oil stocks', 'concentration'."""
        hits = db.search_memories(user_id, query, limit=5)
        if not hits:
            return _dump({"query": query, "memories": [],
                          "note": "No saved memories match. Try broader words, or proceed without."})
        return _dump({"query": query, "memories": [
            {"kind": h["kind"], "content": h["content"], "tags": h["tags"], "saved": h["created_at"][:10]}
            for h in hits
        ]})

    return [get_portfolio_summary, get_positions, get_watchlist_snapshot, get_price_performance,
            get_company_profile, get_company_news, recall_memory]