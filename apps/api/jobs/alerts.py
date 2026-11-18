"""Rule checks, no AI: a holding moved 5% or more today, reports earnings on the next trading day, or is
over the user's saved position limit. Each kind fires at most once per ticker per day (UserRepo.add_alerts)."""
from __future__ import annotations

import asyncio
import logging
import uuid
from collections import Counter
from datetime import datetime

from agent.tools import user_repo
from core.market_clock import is_trading_day, next_trading_day
from datasources import market
from datasources.market import ET
from db.repo import AdminRepo
from db.session import SessionLocal
from notify import email
from portfolio.service import portfolio_view

log = logging.getLogger("foxhood.jobs.alerts")
BIG_MOVE_PCT = 5.0


async def check_user(uid: uuid.UUID, now: datetime) -> int:
    """Raise any new alerts for one user; returns how many were added."""
    async with user_repo(uid) as repo:
        holdings = await repo.list_holdings()
        prefs = await repo.get_settings()
    if not holdings:
        return 0
    view = await portfolio_view(uid, holdings)
    found: list[tuple[str, str, dict]] = []

    limit = prefs["max_position_pct"]
    for p in view["positions"]:
        move = p.get("day_change_pct")
        if move is not None and abs(move) >= BIG_MOVE_PCT:
            found.append(("big_move", p["ticker"], {"pct": round(move, 2), "day_pnl": round(p["day_pnl"], 2)}))
        if limit is not None and p["weight_pct"] > limit:
            found.append(("position_limit", p["ticker"], {"weight_pct": round(p["weight_pct"], 1), "limit_pct": limit}))

    nxt = next_trading_day(now.date())
    tickers = sorted({h.ticker for h in holdings})
    for e in await asyncio.to_thread(market.get_earnings_calendar, tickers, (nxt - now.date()).days, 0):
        if e["date"] == nxt.isoformat() and e["status"] == "upcoming":
            found.append(("earnings_tomorrow", e["ticker"], {"date": e["date"], "timing": e["timing"],
                                                             "eps_estimate": e["eps_estimate"]}))
    async with user_repo(uid) as repo:
        added = await repo.add_alerts(now.date(), found)
        if added and prefs["email_alerts"]:
            to = (await repo.get_profile())["email"]
            if await email.send(to, *email.alerts_email([alert_message(a.kind, a.ticker, a.data, now) for a in added])):
                await repo.mark_alerts_emailed([a.id for a in added])
    return len(added)


async def run_alerts(now: datetime | None = None, user_ids: list[uuid.UUID] | None = None) -> dict:
    now = (now or datetime.now(ET)).astimezone(ET)
    if not is_trading_day(now.date()):
        return {"ran": False, "reason": "market closed today"}
    if user_ids is None:
        async with SessionLocal() as s:
            user_ids = await AdminRepo(s).active_user_ids()
    added, outcomes = 0, Counter()
    for uid in user_ids:
        try:
            n = await check_user(uid, now)
            added += n
            outcomes["checked"] += 1
        except Exception:
            log.exception("Alert check failed for user %s", uid)
            outcomes["failed"] += 1
    return {"ran": True, "users": len(user_ids), "alerts_added": added, "outcomes": dict(outcomes)}


TIMING = {"before market open": "before the open", "after market close": "after the close",
          "during market hours": "during the trading day"}


def alert_message(kind: str, ticker: str, data: dict, today: datetime | None = None) -> str:
    """One plain sentence per alert, for Today and for email."""
    if kind == "big_move":
        pct = data["pct"]
        return f"{ticker} is {'up' if pct > 0 else 'down'} {abs(pct):.1f}% today."
    if kind == "position_limit":
        return (f"{ticker} is {data['weight_pct']:.0f}% of your portfolio, over the "
                f"{data['limit_pct']:g}% limit you set.")
    if kind == "earnings_tomorrow":
        when = TIMING.get(data.get("timing", ""), "")
        d = datetime.fromisoformat(data["date"]).date()
        base = (today or datetime.now(ET)).astimezone(ET).date()
        day = "tomorrow" if (d - base).days == 1 else f"on {d:%A}"
        est = f" Analysts expect ${data['eps_estimate']:.2f} a share." if data.get("eps_estimate") is not None else ""
        return f"{ticker} reports earnings {day}{' ' + when if when else ''}.{est}"
    return f"{ticker}: {kind}"
