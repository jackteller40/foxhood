"""Brief fact-check (agent/review.py) and brief continuity (agent/briefs.py)."""
import json
from datetime import date

from langchain_core.messages import ToolMessage

from agent.briefs import get_or_create_brief
from agent.review import evidence_from, review_brief
from core.market_clock import BriefSlot
from tests.test_agent import ScriptedModel, say


class RecordingModel(ScriptedModel):
    """A scripted model that also keeps every prompt it was sent."""
    seen: list = []

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(messages)
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

EVIDENCE = '[get_positions]\n{"positions": [{"ticker": "NVDA", "weight_pct": 51.0, "day_change_pct": -1.8}]}'
BRIEF = "NVDA fell 3.5% yesterday and is 51% of your portfolio.\n\nNot financial advice."
FIXED = "NVDA fell 1.8% yesterday and is 51% of your portfolio.\n\nNot financial advice."
WRONG = {"claim": "fell 3.5%", "issue": "evidence says -1.8%", "correction": "fell 1.8%"}
TAKE = {"ticker": "NVDA", "note": "NVDA reports Wednesday after the close"}


def review_json(problems=(), takeaways=(TAKE,)) -> str:
    return "```json\n" + json.dumps({"problems": list(problems), "takeaways": list(takeaways)}) + "\n```"


async def test_clean_brief_passes_through():
    model = ScriptedModel(responses=[say(review_json())])
    out = await review_brief(BRIEF, EVIDENCE, model)
    assert out.checked and out.content == BRIEF and not out.fixed and out.takeaways[0].ticker == "NVDA"


async def test_wrong_number_is_rewritten():
    model = ScriptedModel(responses=[say(review_json([WRONG])), say(FIXED), say(review_json())])
    used = []

    async def usage(reply):
        used.append(reply.usage_metadata["output_tokens"])

    out = await review_brief(BRIEF, EVIDENCE, model, on_usage=usage)
    assert out.content == FIXED and [p.claim for p in out.fixed] == ["fell 3.5%"] and not out.unverified
    assert len(used) == 3                                          # check, rewrite, re-check all counted


async def test_still_wrong_after_rewrite_is_noted_before_the_footer():
    model = ScriptedModel(responses=[say(review_json([WRONG])), say(BRIEF), say(review_json([WRONG]))])
    out = await review_brief(BRIEF, EVIDENCE, model)
    assert out.unverified and "couldn't verify: “fell 3.5%”" in out.content
    assert out.content.rstrip().endswith("Not financial advice.")


async def test_unreadable_review_saves_the_brief_unchecked():
    out = await review_brief(BRIEF, EVIDENCE, ScriptedModel(responses=[say("Looks fine to me!")]))
    assert not out.checked and out.content == BRIEF


def test_evidence_is_labeled_and_trimmed():
    msgs = [ToolMessage(content="x" * 10_000, name="get_positions", tool_call_id="1"),
            ToolMessage(content="macro data", name="get_macro_snapshot", tool_call_id="2")]
    ev = evidence_from(msgs)
    assert ev.startswith("[get_positions]\n") and len(ev) < 6_100 + 40 and "[get_macro_snapshot]\nmacro data" in ev


async def test_briefs_follow_up_on_earlier_takeaways(make_user):
    alice = await make_user()
    monday, tuesday = BriefSlot("premarket", date(2026, 11, 16), "t"), BriefSlot("premarket", date(2026, 11, 17), "t")

    model = ScriptedModel(responses=[say("Monday brief. Not financial advice."), say(review_json())])
    first = await get_or_create_brief(alice.user_id, monday, model=model, use_mcp=False)
    assert first["checked"] is True
    [saved] = await alice.list_memories(kind="brief_takeaway")
    assert saved.content == "Nov 16: NVDA reports Wednesday after the close" and "NVDA" in saved.tags

    model = RecordingModel(responses=[say("Tuesday brief. Not financial advice."), say(review_json(takeaways=()))],
                           seen=[])
    await get_or_create_brief(alice.user_id, tuesday, model=model, use_mcp=False)
    asked = next(m.content for m in model.seen[0] if m.type == "human")
    assert "earlier briefs flagged" in asked and "- Nov 16: NVDA reports Wednesday after the close" in asked


async def test_only_the_newest_takeaways_are_kept(make_user):
    alice = await make_user()
    for day in range(2, 11):
        model = ScriptedModel(responses=[say("Brief. Not financial advice."),
                                         say(review_json(takeaways=[{"ticker": None, "note": f"note {day}"}]))])
        await get_or_create_brief(alice.user_id, BriefSlot("close", date(2026, 11, day), "t"), model=model, use_mcp=False)
    kept = [m.content for m in await alice.list_memories(kind="brief_takeaway")]
    assert len(kept) == 6 and kept[0].endswith("note 10") and not any(k.endswith("note 4") for k in kept)
