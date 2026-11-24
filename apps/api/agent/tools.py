"""Local tools for the main agent. Built per run with the user's id baked in,
so the LLM never chooses (or sees) whose data it's reading.

Tools are async and each opens its own DB session: the model often calls several tools at once,
and one AsyncSession can't be shared between tasks running in parallel. Market-data calls are
blocking  http calls, so they run in worker threads."""
from __future__ import annotations

import asyncio
import json
import math
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta

import pandas as pd
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from datasources import market
from datasources.market import ET
from db.repo import UserRepo
from db.session import SessionLocal
from portfolio import metrics, whatif
from portfolio.positions import Lot, resolve_lot


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


@asynccontextmanager
async def user_repo(user_id: uuid.UUID) -> AsyncIterator[UserRepo]:
    """A short-lived session + repo for one user. Use one per tool call, never shared."""
    async with SessionLocal() as session:
        yield UserRepo(session, user_id)


def _resolve_portfolio(lots: list[Lot]) -> tuple[list, list[str], pd.DataFrame]:
    """Price every lot and build the positions table (blocking: fetches market data)."""
    resolved, errors = [], []
    for lot in lots:
        try:
            resolved.append(resolve_lot(lot))
        except Exception as e:
            errors.append(f"{lot.ticker} bought {lot.purchase_date}: {e}")
    positions = metrics.positions_table(resolved) if resolved else pd.DataFrame()
    return resolved, errors, positions


def _summary(resolved: list, positions: pd.DataFrame) -> dict:
    summary = metrics.portfolio_summary(resolved, positions)
    summary["sector_exposure_pct"] = metrics.sector_exposure(positions).to_dict()
    return summary


class PortfolioChange(BaseModel):
    """One hypothetical trade. Give exactly one of shares, amount_usd or fraction."""
    ticker: str
    action: str = Field(description="'buy' or 'sell'")
    shares: float | None = None
    amount_usd: float | None = Field(None, description="Dollar amount to buy or sell")
    fraction: float | None = Field(None, description="Sells only: share of the position, 0.5 = half")


def make_local_tools(user_id: uuid.UUID) -> list:
    cache: dict = {}
    lock = asyncio.Lock()  # parallel tool calls share one portfolio computation

    async def _portfolio():
        async with lock:
            if "positions" not in cache:
                async with user_repo(user_id) as repo:
                    lots = [h.to_lot() for h in await repo.list_holdings()]
                resolved, errors, positions = await asyncio.to_thread(_resolve_portfolio, lots)
                cache.update(resolved=resolved, errors=errors, positions=positions)
        return cache["resolved"], cache["errors"], cache["positions"]

    @tool
    async def get_portfolio_summary() -> str:
        """Overall portfolio for the current user: total value, cost, P&L as price return AND
        total return (dividends reinvested), today's P&L, both compared to SPY, number of
        positions, the largest position and its weight, and sector exposure (%).
        Start here for any question about how the portfolio is doing."""
        resolved, errors, positions = await _portfolio()
        if not resolved:
            return _dump({"error": "User has no holdings.", "lot_errors": errors})
        summary = await asyncio.to_thread(_summary, resolved, positions)
        if errors:
            summary["lot_errors"] = errors
        return _dump(summary)

    @tool
    async def get_positions() -> str:
        """Per-position detail for the current user's holdings: shares, average cost, price,
        market value, portfolio weight %, price return %, total return %, and today's move.
        Use for questions about specific holdings, movers, or concentration."""
        _resolved, errors, positions = await _portfolio()
        if positions.empty:
            return _dump({"positions": [], "lot_errors": errors})
        cols = ["ticker", "name", "sector", "lots", "shares", "avg_cost", "price", "market_value",
                "weight_pct", "pnl_pct", "total_return_pct", "day_change_pct", "day_pnl"]
        return _dump({"positions": positions[cols].to_dict(orient="records"), "lot_errors": errors})

    @tool
    async def get_watchlist_snapshot() -> str:
        """Current user's watchlist with price, today's move, 1-week/1-month/YTD returns, and
        distance from the 52-week high for each ticker, plus the user's note on it."""
        async with user_repo(user_id) as repo:
            items = await repo.list_watchlist()
        if not items:
            return _dump({"watchlist": [], "note": "Watchlist is empty."})

        async def one(w) -> dict:
            try:
                p = await asyncio.to_thread(_performance, w.ticker)
                p["user_note"] = w.note
                return p
            except Exception as e:
                return {"ticker": w.ticker, "error": str(e)}

        return _dump({"watchlist": list(await asyncio.gather(*(one(w) for w in items)))})

    @tool
    async def get_price_performance(ticker: str) -> str:
        """Price performance for any ticker: price, 1-day change, 1-week, 1-month, 3-month, YTD
        and 1-year returns (%), 52-week high/low, and % below the 52-week high."""
        return _dump(await asyncio.to_thread(_performance, ticker))

    @tool
    async def get_company_profile(ticker: str) -> str:
        """Company or fund profile: name, type (EQUITY/ETF), sector, industry, market cap,
        trailing and forward P/E, beta, dividend yield (already a percent: 0.75 means 0.75%),
        and 52-week range. ETFs won't have sector or P/E."""
        return _dump(await asyncio.to_thread(market.get_company_info, ticker))

    @tool
    async def recall_memory(query: str) -> str:
        """Search this user's saved memories (preferences, facts, past brief takeaways) by
        keywords. Call before giving recommendations or ideas, and whenever the user's past
        preferences might change your answer. Example queries: 'oil stocks', 'concentration'."""
        async with user_repo(user_id) as repo:
            hits = await repo.search_memories(query, limit=5)
        if not hits:
            return _dump({"query": query, "memories": [],
                          "note": "No saved memories match. Try broader words, or proceed without."})
        return _dump({"query": query, "memories": [
            {"kind": m.kind, "content": m.content, "tags": m.tags, "saved": m.created_at.date().isoformat()}
            for _score, m in hits
        ]})
        
    @tool
    async def get_earnings_calendar(tickers: list[str] | None = None, days_ahead: int = 14) -> str:
        """Earnings dates for the user's holdings and watchlist (or the tickers you pass), from 3 days
        ago to `days_ahead` days out (max 30): date, before/after market, quarter, EPS estimate, and the
        actual EPS for ones already reported. Use for "what reports this week?", and in briefs."""
        if tickers:
            wanted = [t.strip().upper() for t in tickers if t and t.strip()][:30]
        else:
            async with user_repo(user_id) as repo:
                wanted = sorted({h.ticker for h in await repo.list_holdings()}
                                | {w.ticker for w in await repo.list_watchlist()})
        if not wanted:
            return _dump({"earnings": [], "note": "No holdings or watchlist tickers to check."})
        days = max(1, min(int(days_ahead), 30))
        rows = await asyncio.to_thread(market.get_earnings_calendar, wanted, days)
        return _dump({"checked": wanted, "window_days_ahead": days, "earnings": rows,
                      "note": None if rows else "None of these report in this window.",
                      "source": "Finnhub earnings calendar"})

    @tool
    async def simulate_portfolio_change(changes: list[PortfolioChange]) -> str:
        """What-if for the current user's portfolio: apply hypothetical buys and sells (nothing is saved or
        traded) and compare before vs after: total value, weights, largest position, sector mix, estimated
        realized gain on sales, and the past year's return, volatility and worst drop for today's holdings,
        the changed holdings, and SPY. Use for "what if I sold half my NVDA?", "what if I put $5k into VOO?",
        or "what if I trimmed NVDA to 25%?" (work out the sale size from get_positions first)."""
        _resolved, _errors, positions = await _portfolio()
        if positions.empty:
            return _dump({"error": "User has no holdings to simulate against."})
        parsed = [whatif.Change(c.ticker, c.action.strip().lower(), c.shares, c.amount_usd, c.fraction) for c in changes]
        try:
            result = await asyncio.to_thread(whatif.simulate, positions, parsed, datetime.now(ET).date())
        except ValueError as e:
            return _dump({"error": str(e)})
        return _dump(result)

    return [get_portfolio_summary, get_positions, get_watchlist_snapshot, get_price_performance,
            get_company_profile, recall_memory, get_earnings_calendar, simulate_portfolio_change]