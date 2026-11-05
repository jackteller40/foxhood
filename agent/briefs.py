"""Daily briefs: one per user per trading day per session, cached in the briefs table."""
from __future__ import annotations

from agent.runner import arun_agent
from core.async_utils import run_sync
from core.market_clock import BriefSlot, current_brief_slot
from storage import db

LABELS = {"premarket": "pre-market brief", "close": "post-close recap"}


async def aget_or_create_brief(user_id: int, slot: BriefSlot | None = None, force: bool = False) -> dict:
    slot = slot or current_brief_slot()
    if not force:
        cached = db.get_brief(user_id, slot.brief_date, slot.session)
        if cached:
            return {**cached, "cached": True, "slot_reason": slot.reason}

    # Deliberately doesn't name a skill: the agent has to pick the right one from its catalog.
    question = f"Write my {LABELS[slot.session]} for {slot.brief_date:%A, %B %d, %Y}."
    result = await arun_agent(user_id, question, task=f"brief:{slot.session}")
    db.save_brief(user_id, slot.brief_date, slot.session, result.answer, run_id=result.run_id)
    return {**db.get_brief(user_id, slot.brief_date, slot.session), "cached": False, "slot_reason": slot.reason}


def get_or_create_brief(user_id: int, slot: BriefSlot | None = None, force: bool = False) -> dict:
    return run_sync(aget_or_create_brief(user_id, slot, force))