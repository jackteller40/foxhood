"""Tools that change user data. Every one is gated by config/permissions.yaml
(ask or deny); none of them can run without passing the policy check first."""
from __future__ import annotations

from datetime import date

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from agent.tools import _dump
from portfolio.positions import Lot, resolve_lot
from storage import db


def make_write_tools(user_id: int) -> list:

    @tool
    def add_to_watchlist(ticker: str, note: str | None = None) -> str:
        """Add a ticker to the user's watchlist with an optional short note."""
        t = ticker.strip().upper()
        if any(w["ticker"] == t for w in db.list_watchlist(user_id)):
            return _dump({"ok": True, "ticker": t, "note": "Already on the watchlist; left unchanged."})
        db.add_to_watchlist(user_id, t, note)
        return _dump({"ok": True, "ticker": t, "added": True, "note": note})

    @tool
    def remove_from_watchlist(ticker: str) -> str:
        """Remove a ticker from the user's watchlist."""
        t = ticker.strip().upper()
        removed = db.remove_from_watchlist(user_id, t)
        return _dump({"ok": removed, "ticker": t, "note": None if removed else "Ticker was not on the watchlist."})

    @tool
    def add_holding(ticker: str, purchase_date: str, shares: float | None = None,
                    amount: float | None = None) -> str:
        """Record a past purchase in the user's portfolio. purchase_date is YYYY-MM-DD. Give exactly
        one of `shares` (count bought that day) or `amount` (dollars invested)."""
        d = date.fromisoformat(purchase_date)
        r = resolve_lot(Lot(ticker, d, shares=shares, amount=amount))  # validates and prices it first
        hid = db.add_holding(user_id, r.ticker, d, shares=shares, amount=amount)
        return _dump({"ok": True, "holding_id": hid, "ticker": r.ticker, "trade_date": r.trade_date,
                      "price_paid": r.price_paid, "shares_now": r.shares_now,
                      "cost_basis": r.cost_basis, "note": r.note})

    @tool
    def remember(content: str, config: RunnableConfig, kind: str = "preference",
                 tags: list[str] | None = None) -> str:
        """Save a lasting fact or preference about the user for future conversations.
        kind is 'preference', 'fact', or 'brief_takeaway'. Only save what the user asked you to
        remember or clearly stated as a lasting preference."""
        run_id = ((config or {}).get("metadata") or {}).get("app_run_id")
        mid = db.add_memory(user_id, kind, content, tags=tags or [], source_run_id=run_id)
        return _dump({"ok": True, "memory_id": mid, "kind": kind, "content": content})

    @tool
    def submit_trade_order(ticker: str, side: str, quantity: float) -> str:
        """Submit a buy or sell order for a ticker to the brokerage."""
        raise RuntimeError("Trading is not supported.")  # unreachable: the policy denies it first

    return [add_to_watchlist, remove_from_watchlist, add_holding, remember, submit_trade_order]