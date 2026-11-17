"""The full agent loop with a scripted fake model: no API key, no network, no MCP subprocess.

Each test scripts exactly what "Claude" says (including tool calls), then checks what the app did:
which tools ran, what the policy decided, what was saved, and that it was all encrypted."""
import json
from datetime import date

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langchain_core.outputs import ChatGenerationChunk
from sqlalchemy import text

from agent.briefs import get_or_create_brief
from agent.runner import arun_agent, get_thread_state
from core.market_clock import BriefSlot
from db.repo import NotFound


class ScriptedModel(FakeMessagesListChatModel):
    """Replies with the scripted messages in order. bind_tools is a no-op: the script decides.

    Streams like Claude with tools bound: text arrives word by word as content blocks, tool calls and
    usage in the last chunk, and each chunk is reported to callbacks twice (as langchain-anthropic does)."""

    def bind_tools(self, tools, **kwargs):
        return self

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        msg = self._generate(messages, stop=stop).generations[0].message
        words = msg.content.split(" ") if msg.content else []
        for i, word in enumerate(words):
            text = word if i == len(words) - 1 else word + " "
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=[{"type": "text", "text": text, "index": 0}]))
            if run_manager:
                run_manager.on_llm_new_token(text, chunk=chunk)
            yield chunk
        yield ChatGenerationChunk(message=AIMessageChunk(
            content=[], usage_metadata=msg.usage_metadata, response_metadata=msg.response_metadata,
            tool_call_chunks=[{"name": tc["name"], "args": json.dumps(tc["args"]), "id": tc["id"], "index": i + 1,
                               "type": "tool_call_chunk"} for i, tc in enumerate(msg.tool_calls)]))


def say(text: str = "", *calls: tuple[str, dict]) -> AIMessage:
    tool_calls = [{"name": name, "args": args, "id": f"call_{i}_{name}", "type": "tool_call"}
                  for i, (name, args) in enumerate(calls)]
    return AIMessage(content=text, tool_calls=tool_calls,
                     usage_metadata={"input_tokens": 1000, "output_tokens": 50, "total_tokens": 1050},
                     response_metadata={"model_name": "fake-haiku", "stop_reason": "end_turn"})


async def run(repo, question=None, script=None, **kw):
    model = kw.pop("model", None) or ScriptedModel(responses=script)
    return await arun_agent(repo.user_id, question, model=model, use_mcp=False, **kw), model


def tool_results(result) -> dict[str, str]:
    return {m.name: m.content for m in result.messages if isinstance(m, ToolMessage)}


async def test_recall_memory_answer_trace_and_usage(make_user, session):
    alice = await make_user()
    await alice.add_memory("preference", "Never let one position exceed 10% of the portfolio",
                           tags=["concentration"])
    r, _ = await run(alice, "Am I too concentrated?", [
        say("", ("recall_memory", {"query": "concentration"})),
        say("Your rule is 10% max per position. Not financial advice."),
    ])
    assert r.status == "ok" and "10% max" in r.answer
    assert "exceed 10%" in tool_results(r)["recall_memory"]   # the tool read Alice's encrypted memory

    events = await alice.get_run_events(r.run_id)
    assert {"run", "llm", "memory"} <= {e["event_type"] for e in events}
    assert events[0]["input"]["question"] == "Am I too concentrated?"
    usage = (await session.execute(text("SELECT model, input_tokens, output_tokens FROM usage WHERE run_id = :r"),
                                   {"r": r.run_id})).all()
    assert [tuple(u) for u in usage] == [("fake-haiku", 2000, 100)]


async def test_checkpoints_are_encrypted(make_user, session):
    alice = await make_user()
    r, _ = await run(alice, "Is TSLA overweight in my portfolio xyzzy?", [say("No idea xyzzy.")])
    raw = (await session.execute(text(
        "SELECT coalesce(string_agg(encode(blob, 'escape'), ''), '') FROM checkpoint_blobs WHERE thread_id = :t "
        "UNION ALL SELECT coalesce(string_agg(encode(blob, 'escape'), ''), '') FROM checkpoint_writes "
        "WHERE thread_id = :t UNION ALL SELECT coalesce(string_agg(checkpoint::text || metadata::text, ''), '') "
        "FROM checkpoints WHERE thread_id = :t"), {"t": r.thread_id})).scalars().all()
    assert any(raw), "expected checkpoint rows for this thread"
    assert not any("xyzzy" in chunk for chunk in raw)

    state = await get_thread_state(alice.user_id, r.thread_id)   # ...but the owner reads it back fine
    assert "xyzzy" in state["messages"][0].content and state["pending"] == []


async def test_trade_is_denied_and_logged(make_user):
    alice = await make_user()
    r, _ = await run(alice, "Sell all my NVDA", [
        say("", ("submit_trade_order", {"ticker": "NVDA", "side": "sell", "quantity": 10})),
        say("I can't place trades; this app is research-only."),
    ])
    assert r.status == "ok"
    assert tool_results(r)["submit_trade_order"].startswith("DENIED")
    run_summary = (await alice.list_runs())[0]
    assert run_summary["root_run_id"] == r.run_id and run_summary["denials"] == 1


@pytest.mark.parametrize("approve", [True, False])
async def test_remember_pauses_then_resumes(make_user, approve):
    alice = await make_user()
    r1, model = await run(alice, "Remember that I prefer dividend stocks", [
        say("", ("remember", {"content": "Prefers dividend stocks", "kind": "preference"})),
        say("Saved." if approve else "OK, I won't save it."),
    ])
    assert r1.status == "paused" and [p["tool"] for p in r1.pending] == ["remember"]
    assert await alice.list_memories() == []                       # nothing saved while waiting
    assert (await get_thread_state(alice.user_id, r1.thread_id))["pending"][0]["tool"] == "remember"

    call_id = r1.pending[0]["id"]
    r2, _ = await run(alice, resume={"decisions": {call_id: {"approved": approve}}, "by": "test"},
                      thread_id=r1.thread_id, parent_run_id=r1.run_id, model=model)
    assert r2.status == "ok"
    memories = await alice.list_memories()
    if approve:
        assert [m.content for m in memories] == ["Prefers dividend stocks"]
        assert memories[0].source_run_id == r2.run_id
    else:
        assert memories == []
        assert tool_results(r2)["remember"].startswith("NOT APPROVED")
    statuses = [e["status"] for e in await alice.get_run_events(r2.run_id) if e["event_type"] == "permission"]
    assert statuses == ["approved" if approve else "rejected"]


async def test_cannot_use_someone_elses_thread(make_user):
    alice, bob = await make_user(), await make_user()
    r, _ = await run(alice, "hello", [say("Hi Alice.")])
    with pytest.raises(NotFound):
        await run(bob, "what did alice ask?", [say("x")], thread_id=r.thread_id)
    with pytest.raises(NotFound):
        await get_thread_state(bob.user_id, r.thread_id)


async def test_brief_is_saved_then_served_from_db(make_user):
    alice = await make_user()
    slot = BriefSlot("close", date(2026, 11, 13), "test")
    model = ScriptedModel(responses=[say("Markets fell; your NVDA dropped 3%. Not financial advice.")])
    first = await get_or_create_brief(alice.user_id, slot, model=model, use_mcp=False)
    assert first["cached"] is False and "NVDA dropped" in first["content"]
    again = await get_or_create_brief(alice.user_id, slot, model=model, use_mcp=False)  # no model call
    assert again["cached"] is True and again["content"] == first["content"]
    


async def test_live_events_for_a_normal_turn(make_user):
    alice = await make_user()
    events: list[dict] = []
    r, _ = await run(alice, "Any saved rules?", [
        say("", ("recall_memory", {"query": "rules"})),
        say("You have no saved rules yet."),
    ], on_event=events.append)
    types = [e["type"] for e in events]
    assert types[:2] == ["tool_start", "tool_end"] and types[-1] == "done"
    assert events[0]["name"] == "recall_memory" and events[0]["kind"] == "memory"
    tokens = [e["text"] for e in events if e["type"] == "token"]
    assert "".join(tokens) == "You have no saved rules yet." == r.answer   # streamed once each, in order
    assert events[-1] == {"type": "done", "status": "ok", "run_id": r.run_id, "thread_id": r.thread_id,
                          "answer": r.answer}


async def test_live_events_for_denial_and_pause(make_user):
    alice = await make_user()
    events: list[dict] = []
    r, _ = await run(alice, "Sell NVDA and remember I like dividends", [
        say("", ("submit_trade_order", {"ticker": "NVDA", "side": "sell", "quantity": 1}),
            ("remember", {"content": "Likes dividend stocks"})),
    ], on_event=events.append)
    assert r.status == "paused"
    assert [e["type"] for e in events] == ["denied", "approval_required", "done"]
    assert events[0]["name"] == "submit_trade_order" and "research-only" in events[0]["reason"]
    assert [q["tool"] for q in events[1]["requests"]] == ["remember"]
    assert events[2]["status"] == "paused"