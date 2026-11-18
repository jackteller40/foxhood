"""Write each active user's pre-market brief, one user at a time so the daily AI caps are checked
before every run. A failure for one user is logged and doesn't stop the rest."""
from __future__ import annotations

import logging
import uuid
from collections import Counter
from datetime import datetime

from langchain_core.language_models import BaseChatModel

from agent.briefs import get_or_create_brief
from agent.tools import user_repo
from app.settings import settings
from core.market_clock import BriefSlot, is_trading_day
from datasources.market import ET
from db.repo import AdminRepo
from db.session import SessionLocal
from notify import email

log = logging.getLogger("foxhood.jobs.briefs")


async def run_morning_briefs(now: datetime | None = None, *, model: BaseChatModel | None = None,
                             use_mcp: bool = True, user_ids: list[uuid.UUID] | None = None) -> dict:
    now = (now or datetime.now(ET)).astimezone(ET)
    if not is_trading_day(now.date()):
        return {"ran": False, "reason": "market closed today"}
    slot = BriefSlot("premarket", now.date(), "scheduled pre-market brief")

    if user_ids is None:
        async with SessionLocal() as s:
            user_ids = await AdminRepo(s).active_user_ids()
    outcomes: dict[str, str] = {}
    emailed = 0
    for uid in user_ids:
        async with user_repo(uid) as repo:
            prefs = await repo.get_settings()
            has_holdings = bool(await repo.list_holdings())
            if await repo.get_brief(slot.brief_date, slot.session):
                outcomes[str(uid)] = "already written"
                continue
            over_user_cap = await repo.spent_today() >= settings.daily_cap_user_usd
        async with SessionLocal() as s:
            over_total_cap = await AdminRepo(s).global_spent_today() >= settings.daily_cap_total_usd

        if not prefs["scheduled_briefs"]:
            outcomes[str(uid)] = "turned off"
        elif not has_holdings:
            outcomes[str(uid)] = "no holdings"
        elif over_total_cap or over_user_cap:
            outcomes[str(uid)] = "over budget"
        else:
            try:
                brief = await get_or_create_brief(uid, slot, model=model, use_mcp=use_mcp)
                outcomes[str(uid)] = "written"
                if prefs["email_briefs"]:
                    async with user_repo(uid) as repo:
                        to = (await repo.get_profile())["email"]
                    emailed += await email.send(to, *email.brief_email(brief["content"], slot.brief_date))
            except Exception:
                log.exception("Morning brief failed for user %s", uid)
                outcomes[str(uid)] = "failed"
    return {"ran": True, "brief_date": slot.brief_date.isoformat(), "users": len(user_ids),
            "outcomes": dict(Counter(outcomes.values())), "emailed": emailed}
