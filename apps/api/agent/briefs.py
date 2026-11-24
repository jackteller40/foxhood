"""Daily briefs: one per user per trading day per session, stored encrypted in the briefs table.

Each new brief:
1. starts from the takeaways the previous briefs saved ("NVDA reports Wednesday"), so it can follow up;
2. is fact-checked against the data the agent pulled during the run (agent/review.py), with one
   automatic rewrite if something doesn't match;
3. saves its own 1-3 takeaways for the next brief (kept as brief_takeaway memories, newest few only)."""
from __future__ import annotations

import logging
import uuid
from dataclasses import asdict
from datetime import date

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage

from agent.models import make_model
from agent.pricing import call_cost
from agent.review import Takeaway, evidence_from, review_brief
from agent.runner import arun_agent
from agent.tools import user_repo
from agent.tracing import EventSink
from core.config import settings
from core.market_clock import BriefSlot, current_brief_slot

log = logging.getLogger("foxhood.briefs")
LABELS = {"premarket": "pre-market brief", "close": "post-close recap"}
KEEP_TAKEAWAYS = 6


async def _previous_takeaways(user_id: uuid.UUID) -> list[str]:
    async with user_repo(user_id) as repo:
        saved = await repo.list_memories(kind="brief_takeaway", limit=KEEP_TAKEAWAYS)
    return [m.content for m in reversed(saved)]           # oldest first reads naturally


async def _save_takeaways(user_id: uuid.UUID, takeaways: list[Takeaway], brief_date: date, run_id: str) -> None:
    async with user_repo(user_id) as repo:
        for t in takeaways[:3]:
            tags = ["brief", brief_date.isoformat()] + ([t.ticker.upper()] if t.ticker else [])
            await repo.add_memory("brief_takeaway", f"{brief_date:%b} {brief_date.day}: {t.note}", tags,
                                  source_run_id=run_id)
        for old in (await repo.list_memories(kind="brief_takeaway", limit=100))[KEEP_TAKEAWAYS:]:
            await repo.delete_memory(old.id)


def _question(slot: BriefSlot, earlier: list[str]) -> str:
    # Deliberately doesn't name a skill: the agent has to pick the right one from its catalog.
    q = f"Write my {LABELS[slot.session]} for {slot.brief_date:%A, %B %d, %Y}."
    if earlier:
        flagged = "\n".join(f"- {e}" for e in earlier)
        q += ("\n\nMy earlier briefs flagged these to follow up. Where one matters today, say in a line what "
              f"happened (with numbers from your tools); skip the rest:\n{flagged}")
    return q


async def get_or_create_brief(user_id: uuid.UUID, slot: BriefSlot | None = None, force: bool = False, *,
                              model: BaseChatModel | None = None, use_mcp: bool = True,
                              on_event: EventSink | None = None) -> dict:
    slot = slot or current_brief_slot()
    if not force:
        async with user_repo(user_id) as repo:
            cached = await repo.get_brief(slot.brief_date, slot.session)
        if cached:
            return {**asdict(cached), "cached": True, "slot_reason": slot.reason}

    question = _question(slot, await _previous_takeaways(user_id))
    result = await arun_agent(user_id, question, task=f"brief:{slot.session}", model=model, use_mcp=use_mcp,
                              on_event=on_event)
    if result.status != "ok":
        raise RuntimeError(f"Brief run {result.run_id} ended with status {result.status}")
    last = next((m for m in reversed(result.messages) if isinstance(m, AIMessage)), None)
    if last is not None and (last.response_metadata or {}).get("stop_reason") == "max_tokens":
        raise RuntimeError(f"Brief run {result.run_id} was truncated (max_tokens); not saving it.")

    async def record_usage(reply: AIMessage) -> None:   # review calls count toward the same daily caps
        u = reply.usage_metadata or {}
        name = (reply.response_metadata or {}).get("model_name") or settings.claude_model
        async with user_repo(user_id) as repo:
            await repo.add_usage(result.run_id, name, u.get("input_tokens", 0), u.get("output_tokens", 0),
                                 call_cost(name, u.get("input_tokens", 0), u.get("output_tokens", 0)))

    outcome = await review_brief(result.answer, evidence_from(result.messages),
                                 model or make_model(max_tokens=3000), on_usage=record_usage)
    log.info("Brief %s checked=%s fixed=%d unverified=%d takeaways=%d", result.run_id, outcome.checked,
             len(outcome.fixed), len(outcome.unverified), len(outcome.takeaways))

    async with user_repo(user_id) as repo:
        saved = await repo.save_brief(slot.brief_date, slot.session, outcome.content, run_id=result.run_id)
    if outcome.takeaways:
        await _save_takeaways(user_id, outcome.takeaways, slot.brief_date, result.run_id)
    return {**asdict(saved), "cached": False, "slot_reason": slot.reason,
            "checked": outcome.checked, "fixed": len(outcome.fixed), "unverified": len(outcome.unverified)}
