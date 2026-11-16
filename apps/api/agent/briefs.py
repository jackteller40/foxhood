"""Daily briefs: one per user per trading day per session, stored encrypted in the briefs table."""
from __future__ import annotations

import uuid
from dataclasses import asdict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage

from agent.runner import arun_agent
from agent.tools import user_repo
from core.market_clock import BriefSlot, current_brief_slot

LABELS = {"premarket": "pre-market brief", "close": "post-close recap"}


async def get_or_create_brief(user_id: uuid.UUID, slot: BriefSlot | None = None, force: bool = False, *,
                              model: BaseChatModel | None = None, use_mcp: bool = True) -> dict:
    slot = slot or current_brief_slot()
    if not force:
        async with user_repo(user_id) as repo:
            cached = await repo.get_brief(slot.brief_date, slot.session)
        if cached:
            return {**asdict(cached), "cached": True, "slot_reason": slot.reason}

    # Deliberately doesn't name a skill: the agent has to pick the right one from its catalog.
    question = f"Write my {LABELS[slot.session]} for {slot.brief_date:%A, %B %d, %Y}."
    result = await arun_agent(user_id, question, task=f"brief:{slot.session}", model=model, use_mcp=use_mcp)
    if result.status != "ok":
        raise RuntimeError(f"Brief run {result.run_id} ended with status {result.status}")
    last = next((m for m in reversed(result.messages) if isinstance(m, AIMessage)), None)
    if last is not None and (last.response_metadata or {}).get("stop_reason") == "max_tokens":
        raise RuntimeError(f"Brief run {result.run_id} was truncated (max_tokens); not saving it.")
    async with user_repo(user_id) as repo:
        saved = await repo.save_brief(slot.brief_date, slot.session, result.answer, run_id=result.run_id)
    return {**asdict(saved), "cached": False, "slot_reason": slot.reason}