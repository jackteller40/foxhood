"""Tools that change user data. Every one is gated by config/permissions.yaml
(ask or deny); none of them can run without passing the policy check first."""
from __future__ import annotations

import asyncio
import uuid
from datetime import date

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from agent.tools import _dump, user_repo
from db.repo import normalize_ticker
from portfolio.positions import Lot, resolve_lot


def make_write_tools(user_id: uuid.UUID) -> list:

    @tool
    async def add_to_watchlist(ticker: str, note: str | None = None) -> str:
        """Add a ticker to the user's watchlist with an optional short note."""
        async with user_repo(user_id) as repo:
            item, created = await repo.add_to_watchlist(ticker, note)
        if not created:
            return _dump({"ok": True, "ticker": item.ticker, "note": "Already on the watchlist; left unchanged."})
        return _dump({"ok": True, "ticker": item.ticker, "added": True, "note": item.note})

    @tool
    async def remove_from_watchlist(ticker: str) -> str:
        """Remove a ticker from the user's watchlist."""
        t = normalize_ticker(ticker)
        async with user_repo(user_id) as repo:
            removed = await repo.remove_from_watchlist(t)
        return _dump({"ok": removed, "ticker": t, "note": None if removed else "Ticker was not on the watchlist."})

    @tool
    async def add_holding(ticker: str, purchase_date: str, shares: float | None = None,
                          amount: float | None = None) -> str:
        """Record a past purchase in the user's portfolio. purchase_date is YYYY-MM-DD. Give exactly
        one of `shares` (count bought that day) or `amount` (dollars invested)."""
        d = date.fromisoformat(purchase_date)
        # Validate and price it first (blocking market data), so a bad ticker or date never gets saved.
        r = await asyncio.to_thread(resolve_lot, Lot(ticker, d, shares=shares, amount=amount))
        async with user_repo(user_id) as repo:
            rec = await repo.add_holding(r.ticker, d, shares=shares, amount=amount, source="agent")
        return _dump({"ok": True, "holding_id": str(rec.id), "ticker": r.ticker, "trade_date": r.trade_date,
                      "price_paid": r.price_paid, "shares_now": r.shares_now,
                      "cost_basis": r.cost_basis, "note": r.note})

    @tool
    async def remember(content: str, config: RunnableConfig, kind: str = "preference",
                       tags: list[str] | None = None) -> str:
        """Save a lasting fact or preference about the user for future conversations.
        kind is 'preference', 'fact', or 'brief_takeaway'. Only save what the user asked you to
        remember or clearly stated as a lasting preference."""
        run_id = ((config or {}).get("metadata") or {}).get("app_run_id")
        async with user_repo(user_id) as repo:
            m = await repo.add_memory(kind, content, tags=tags or [], source_run_id=run_id)
        return _dump({"ok": True, "memory_id": str(m.id), "kind": m.kind, "content": m.content})

    @tool
    def submit_trade_order(ticker: str, side: str, quantity: float) -> str:
        """Trading is NOT available in Foxhood: the permission policy always refuses this tool.
        Never offer to place or submit an order; tell the user to use their own broker."""
        raise RuntimeError("Trading is not supported.")  # unreachable: the policy denies it first

    return [add_to_watchlist, remove_from_watchlist, add_holding, remember, submit_trade_order]