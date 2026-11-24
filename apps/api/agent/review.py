"""Fact-check a brief against the data the agent actually pulled, and pick out what to follow up next time.

One review call does both jobs. If it finds problems, the brief gets ONE rewrite with the problems listed,
then a second check. Anything still unsupported is named in a short note at the end of the brief, so the
reader knows. If the review itself fails (bad JSON, API error), the brief is saved as written: a missing
check should never cost someone their morning brief."""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, ValidationError

from agent.tracing import content_to_text

log = logging.getLogger("foxhood.review")

EVIDENCE_PER_TOOL = 6_000      # characters
EVIDENCE_TOTAL = 40_000

CHECK_PROMPT = """You check a portfolio brief before it's sent to the user. Compare it against the EVIDENCE:
the exact tool results the writer had. Reply with JSON only, no prose, in this shape:
{"problems": [{"claim": "...", "issue": "...", "correction": "..." or null}],
 "takeaways": [{"ticker": "NVDA" or null, "note": "..."}]}

problems: every specific number, percentage, price, date, time, company name, or event in the brief that
contradicts the evidence or doesn't appear in it at all. Rounding to the shown precision is fine, and so are
simple differences or sums of evidence numbers. General statements with no specifics are not problems.
Quote the brief's words in "claim". Give "correction" when the evidence shows the right value. At most 8.
An empty list means everything checks out.

takeaways: 1 to 3 things from this brief worth following up in the user's NEXT brief: an upcoming event
with its date, a risk near or over the user's limit, a story still unfolding. Under 20 words each, include
the date when there is one. Use only facts that are in the evidence."""

REWRITE_PROMPT = """Correct this portfolio brief. Fix ONLY the listed problems, using the EVIDENCE: use the
correction when one is given, otherwise remove or soften the claim so it says only what the evidence
supports. Keep everything else exactly the same: sections, order, tone and length. Reply with the
corrected brief only, in markdown, nothing before or after it."""


class Problem(BaseModel):
    claim: str
    issue: str
    correction: str | None = None


class Takeaway(BaseModel):
    ticker: str | None = None
    note: str


class Review(BaseModel):
    problems: list[Problem] = []
    takeaways: list[Takeaway] = []


@dataclass
class Outcome:
    content: str
    checked: bool                        # False when the review couldn't run
    fixed: list[Problem] = field(default_factory=list)       # found, then corrected by the rewrite
    unverified: list[Problem] = field(default_factory=list)  # still wrong after the rewrite: noted in the brief
    takeaways: list[Takeaway] = field(default_factory=list)


UsageSink = Callable[[AIMessage], Awaitable[None]]


def evidence_from(messages: list) -> str:
    """The tool results from an agent run, labeled and trimmed, as one block of text."""
    parts, total = [], 0
    for m in messages:
        if not isinstance(m, ToolMessage):
            continue
        text = content_to_text(m.content)[:EVIDENCE_PER_TOOL]
        if total + len(text) > EVIDENCE_TOTAL:
            break
        parts.append(f"[{m.name}]\n{text}")
        total += len(text)
    return "\n\n".join(parts) or "(no tool results)"


def _parse(text: str) -> Review | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)        # tolerate ```json fences or stray words
    if not match:
        return None
    try:
        return Review.model_validate(json.loads(match.group(0)))
    except (json.JSONDecodeError, ValidationError):
        return None


async def _ask(model: BaseChatModel, system: str, user: str, on_usage: UsageSink | None) -> str:
    reply = await model.ainvoke([SystemMessage(system), HumanMessage(user)])
    if on_usage is not None:
        await on_usage(reply)
    return content_to_text(reply.content).strip()


async def _check(model, brief: str, evidence: str, on_usage) -> Review | None:
    text = await _ask(model, CHECK_PROMPT, f"EVIDENCE\n{evidence}\n\nBRIEF\n{brief}", on_usage)
    return _parse(text)


def _with_note(brief: str, problems: list[Problem]) -> str:
    claims = "; ".join(f"“{p.claim}”" for p in problems[:4])
    note = f"_Foxhood couldn't verify: {claims}. Treat {'it' if len(problems) == 1 else 'these'} with care._"
    footer = "Not financial advice."
    body = brief.rstrip()
    if body.endswith(footer):
        return f"{body[: -len(footer)].rstrip()}\n\n{note}\n\n{footer}"
    return f"{body}\n\n{note}"


async def review_brief(brief: str, evidence: str, model: BaseChatModel,
                       on_usage: UsageSink | None = None) -> Outcome:
    try:
        first = await _check(model, brief, evidence, on_usage)
    except Exception:
        log.exception("Brief check failed; saving the brief unchecked")
        return Outcome(brief, checked=False)
    if first is None:
        log.warning("Brief check returned unreadable output; saving the brief unchecked")
        return Outcome(brief, checked=False)
    if not first.problems:
        return Outcome(brief, checked=True, takeaways=first.takeaways)

    try:
        listed = "\n".join(f"- {p.claim}: {p.issue}" + (f" (correct: {p.correction})" if p.correction else "")
                           for p in first.problems)
        rewritten = await _ask(model, REWRITE_PROMPT,
                               f"EVIDENCE\n{evidence}\n\nPROBLEMS\n{listed}\n\nBRIEF\n{brief}", on_usage)
        second = await _check(model, rewritten, evidence, on_usage) if rewritten else None
    except Exception:
        log.exception("Brief rewrite failed; noting the problems instead")
        rewritten, second = "", None

    if not rewritten:                                    # couldn't rewrite: keep the original, say what's off
        return Outcome(_with_note(brief, first.problems), True, unverified=first.problems,
                       takeaways=first.takeaways)
    if second is None:                                   # rewrite done, re-check failed: trust the rewrite
        return Outcome(rewritten, True, fixed=first.problems, takeaways=first.takeaways)
    still = second.problems
    fixed = [p for p in first.problems if p.claim not in {s.claim for s in still}]
    content = _with_note(rewritten, still) if still else rewritten
    return Outcome(content, True, fixed=fixed, unverified=still, takeaways=second.takeaways or first.takeaways)
