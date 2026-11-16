"""Briefs, traces and usage: encrypted at rest, private to their owner, summarized correctly."""
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from db.models import utcnow
from db.repo import AdminRepo, NotFound


def _event(root: str, event_type: str, name: str, *, parent: str | None = None, status: str = "ok",
           input=None, output=None, run_id: str | None = None) -> dict:
    start = utcnow()
    return {"run_id": run_id or str(uuid.uuid4()), "parent_run_id": parent, "root_run_id": root,
            "event_type": event_type, "name": name, "status": status, "input": input, "output": output,
            "error": None, "started_at": start, "ended_at": start + timedelta(milliseconds=50), "duration_ms": 50.0}


async def test_briefs_replace_and_stay_private(make_user, session):
    alice, bob = await make_user(), await make_user()
    day = date(2026, 11, 13)
    await alice.save_brief(day, "close", "NVDA fell 3% on AI regulation fears", run_id="r1")
    saved = await alice.save_brief(day, "close", "Second version", run_id="r2")  # same day+session: replaces
    assert (await alice.get_brief(day, "close")).content == "Second version" and saved.run_id == "r2"
    assert len(await alice.list_briefs()) == 1
    assert await bob.get_brief(day, "close") is None
    raw = (await session.execute(text("SELECT content_enc FROM briefs WHERE user_id = :u"),
                                 {"u": alice.user_id})).scalar_one()
    assert "Second version" not in raw
    with pytest.raises(ValueError):
        await alice.save_brief(day, "lunch", "x")


async def test_traces_encrypted_private_and_summarized(make_user, session):
    alice, bob = await make_user(), await make_user()
    root = str(uuid.uuid4())
    await alice.add_trace_events([
        _event(root, "run", "agent:chat", run_id=root, input={"question": "How is my NVDA position?"}),
        _event(root, "tool", "get_positions", parent=root, output={"positions": [{"ticker": "NVDA"}]}),
        _event(root, "permission", "submit_trade_order", parent=root, status="denied",
               input={"args": {"ticker": "NVDA", "side": "sell"}}),
    ])

    events = await alice.get_run_events(root)
    assert [e["event_type"] for e in events] == ["run", "tool", "permission"]
    assert events[0]["input"]["question"] == "How is my NVDA position?"   # decrypted for the owner

    runs = await alice.list_runs()
    assert runs[0]["root_run_id"] == root and runs[0]["run_name"] == "agent:chat"
    assert runs[0]["events"] == 3 and runs[0]["denials"] == 1 and runs[0]["errors"] == 0

    with pytest.raises(NotFound):
        await bob.get_run_events(root)          # someone else's run: 404, not a leak
    assert await bob.list_runs() == []

    raw = (await session.execute(text("SELECT string_agg(coalesce(input_enc,'') || coalesce(output_enc,''), ' ') "
                                      "FROM trace_events WHERE root_run_id = :r"), {"r": root})).scalar_one()
    assert "NVDA" not in raw and "How is my" not in raw


async def test_trace_rejects_unknown_event_type(make_user):
    alice = await make_user()
    with pytest.raises(ValueError):
        await alice.add_trace_events([_event("r", "vibes", "x")])


async def test_usage_and_daily_spend(make_user, session):
    alice, bob = await make_user(), await make_user()
    before_global = await AdminRepo(session).global_spent_today()
    await alice.add_usage("run-1", "claude-haiku-5-5", 12_000, 900, Decimal("0.010"))
    await alice.add_usage("run-2", "claude-haiku-5-5", 20_000, 1_500, Decimal("0.020"))
    assert await alice.spent_today() == Decimal("0.030")
    assert await bob.spent_today() == Decimal("0")
    assert await AdminRepo(session).global_spent_today() - before_global == Decimal("0.030")