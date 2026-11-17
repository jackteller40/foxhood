"""The chat/approval/brief/thread endpoints end to end, with a scripted model (no API key, no cost)."""
import asyncio
import json
import uuid
from dataclasses import replace
from decimal import Decimal

import pytest
from fastapi import HTTPException

from agent.pricing import call_cost
from app.main import app
from app.routes import agent as agent_routes
from app.runs import is_busy, start_run
from db.repo import AdminRepo, UserRepo
from tests.test_agent import ScriptedModel, say


def events(resp) -> list[dict]:
    return [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]


@pytest.fixture
def script():
    """Set what the model will say for the next request(s) in a test: script([...])."""
    holder = {}

    def _set(*messages):
        holder["model"] = ScriptedModel(responses=list(messages))

    app.dependency_overrides[agent_routes.agent_options] = lambda: {"model": holder["model"], "use_mcp": False}
    yield _set
    app.dependency_overrides.pop(agent_routes.agent_options, None)


@pytest.fixture
def signed_in(client, invited_user, session):
    async def _make():
        headers, email, _ = await invited_user()
        assert (await client.get("/me", headers=headers)).status_code == 200
        user = await AdminRepo(session).find_user(email)
        return headers, UserRepo(session, user.id)
    return _make


async def test_chat_streams_and_is_saved(client, signed_in, script):
    headers, _ = await signed_in()
    script(say("Rates matter for your bond ETFs."))
    resp = await client.post("/chat", json={"message": "Do rates matter for me?"}, headers=headers)
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/event-stream")
    evs = events(resp)
    assert "".join(e["text"] for e in evs if e["type"] == "token") == "Rates matter for your bond ETFs."
    done = evs[-1]
    assert done["type"] == "done" and done["status"] == "ok"

    threads = (await client.get("/threads", headers=headers)).json()
    assert [t["title"] for t in threads] == ["Do rates matter for me?"]
    detail = (await client.get(f"/threads/{done['thread_id']}", headers=headers)).json()
    assert [(m["role"], m["text"]) for m in detail["messages"]] == [
        ("user", "Do rates matter for me?"), ("assistant", "Rates matter for your bond ETFs.")]
    assert detail["pending"] == []


async def test_approval_over_the_api(client, signed_in, script):
    headers, _ = await signed_in()
    script(say("", ("remember", {"content": "Prefers ETFs over single stocks"})), say("Saved it."))
    evs = events(await client.post("/chat", json={"message": "Remember I prefer ETFs"}, headers=headers))
    ask = next(e for e in evs if e["type"] == "approval_required")
    thread_id, call_id = ask["thread_id"], ask["requests"][0]["id"]
    assert (await client.get(f"/threads/{thread_id}", headers=headers)).json()["pending"][0]["tool"] == "remember"

    bad = await client.post(f"/threads/{thread_id}/approve", headers=headers,
                            json={"decisions": {"not-a-call": {"approved": True}}})
    assert bad.status_code == 422

    ok = await client.post(f"/threads/{thread_id}/approve", headers=headers,
                           json={"decisions": {call_id: {"approved": True}}, "run_id": ask["run_id"]})
    assert events(ok)[-1]["status"] == "ok"
    memories = (await client.get("/memories", headers=headers)).json()
    assert [m["content"] for m in memories] == ["Prefers ETFs over single stocks"]

    again = await client.post(f"/threads/{thread_id}/approve", headers=headers,
                              json={"decisions": {call_id: {"approved": True}}})
    assert again.status_code == 409   # nothing pending any more


async def test_threads_are_private_over_the_api(client, signed_in, script):
    alice_h, _ = await signed_in()
    bob_h, _ = await signed_in()
    script(say("Hi."))
    tid = events(await client.post("/chat", json={"message": "hello"}, headers=alice_h))[-1]["thread_id"]

    assert (await client.get(f"/threads/{tid}", headers=bob_h)).status_code == 404
    assert (await client.patch(f"/threads/{tid}", json={"title": "x"}, headers=bob_h)).status_code == 404
    assert (await client.delete(f"/threads/{tid}", headers=bob_h)).status_code == 404
    assert (await client.post("/chat", json={"message": "hi", "thread_id": tid}, headers=bob_h)).status_code == 404
    assert (await client.get("/threads", headers=bob_h)).json() == []

    assert (await client.patch(f"/threads/{tid}", json={"title": "Greetings"}, headers=alice_h)).json()["title"] \
        == "Greetings"
    assert (await client.delete(f"/threads/{tid}", headers=alice_h)).status_code == 204
    assert (await client.get(f"/threads/{tid}", headers=alice_h)).status_code == 404


async def test_daily_caps(client, signed_in, script, monkeypatch):
    headers, repo = await signed_in()
    script(say("x"))
    await repo.add_usage("earlier-run", "claude-haiku-5-5", 1000, 100, Decimal("0.02"))
    monkeypatch.setattr(agent_routes, "settings", replace(agent_routes.settings, daily_cap_user_usd=Decimal("0.01")))
    resp = await client.post("/chat", json={"message": "hi"}, headers=headers)
    assert resp.status_code == 429 and "today's AI limit" in resp.json()["detail"]
    usage = (await client.get("/usage/today", headers=headers)).json()
    assert usage["spent_usd"] == 0.02 and usage["remaining_usd"] == 0

    monkeypatch.setattr(agent_routes, "settings", replace(agent_routes.settings, daily_cap_user_usd=Decimal("1"),
                                                          daily_cap_total_usd=Decimal("0")))
    resp = await client.post("/chat", json={"message": "hi"}, headers=headers)
    assert resp.status_code == 429 and "shared daily AI budget" in resp.json()["detail"]


async def test_brief_endpoint_generates_then_serves_saved(client, signed_in, script):
    headers, _ = await signed_in()
    script(say("Today's recap: markets were mixed. Not financial advice."))
    first = events(await client.post("/briefs/today", headers=headers))
    assert first[-1]["type"] == "brief" and first[-1]["cached"] is False
    assert "markets were mixed" in first[-1]["content"]
    second = events(await client.post("/briefs/today", headers=headers))
    assert len(second) == 1 and second[0]["cached"] is True and second[0]["content"] == first[-1]["content"]
    assert len((await client.get("/briefs", headers=headers)).json()) == 1


async def test_one_run_at_a_time_per_user():
    user_id, release = uuid.uuid4(), asyncio.Event()

    async def slow_job(emit):
        await release.wait()

    resp = start_run(user_id, slow_job)
    assert is_busy(user_id)
    with pytest.raises(HTTPException) as exc:
        start_run(user_id, slow_job)
    assert exc.value.status_code == 409
    release.set()
    chunks = [c async for c in resp.body_iterator]   # stream ends once the job finishes
    assert chunks == [] and not is_busy(user_id)


def test_call_cost():
    assert call_cost("claude-haiku-5-5", 10_000, 500) == Decimal("0.001250")
    assert call_cost("claude-haiku-5-5-20261007", 150_000, 1_000) == Decimal("0.077500")   # >100K prompt: 5x
    assert call_cost("claude-haiku-5-5", 10_000, 0, cache_read=8_000) == Decimal("0.000280")
    assert call_cost("some-unknown-model", 10_000, 500) == Decimal(0)