"""Run the main agent for one turn, or resume a run paused for approval.

Every run: profile from the encrypted DB + tools + policy-gated graph + encrypted Postgres
checkpointer + tracing. A paused run returns status="paused" with pending approval requests;
resume it with arun_agent(..., resume={...}, thread_id=<same thread>, parent_run_id=<paused run id>).

When the run ends (ok, paused, or error), its trace events and token usage are saved in one go.

Pass on_event to receive live events while it runs (chunk D streams these to the browser):
  {"type": "token", "text"}                       main-agent answer text as it's generated
  {"type": "tool_start" | "tool_end", "id", "name", ...}
  {"type": "denied", "name", "reason"}            the policy blocked a tool call
  {"type": "approval_required", "requests"}       the run paused; resume with the decisions
  {"type": "done", "status", "run_id", "thread_id", "answer"}  or  {"type": "error", "message"}"""
from __future__ import annotations

import contextlib
import logging
import time
import uuid
from dataclasses import dataclass, field

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_mcp_adapters.tools import load_mcp_tools
from langgraph.types import Command

from agent.checkpoint import delete_thread_checkpoints, open_checkpointer
from agent.graph import build_graph, final_text
from agent.mcp_client import get_mcp_client
from agent.models import make_model
from agent.permissions import Policy
from agent.prompts import build_system_prompt
from agent.skills import catalog_text, discover_skills, make_skill_tool
from agent.subagents.news_analyst import make_news_subagent_tool
from agent.tools import make_local_tools, user_repo
from agent.tracing import EventSink, TraceHandler, activate
from agent.write_tools import make_write_tools
from db.models import utcnow
from db.repo import NotFound

log = logging.getLogger(__name__)


@dataclass
class AgentResult:
    run_id: str
    thread_id: str
    answer: str
    status: str                     # "ok" | "paused" | "error"
    duration_s: float
    pending: list = field(default_factory=list)   # approval requests when paused
    messages: list = field(default_factory=list)


def _root_cause(e: BaseException) -> BaseException:
    """anyio/MCP wrap errors in ExceptionGroups; dig out the real one."""
    while isinstance(e, BaseExceptionGroup) and e.exceptions:
        e = e.exceptions[0]
    return e


def new_thread_id(user_id: uuid.UUID, task: str) -> str:
    return f"{user_id}:{task}:{uuid.uuid4().hex[:12]}"


def check_thread(user_id: uuid.UUID, thread_id: str) -> None:
    """Thread ids start with their owner's id; anyone else's thread looks like it doesn't exist."""
    if not thread_id.startswith(f"{user_id}:"):
        raise NotFound("threads")


async def _save_run(user_id: uuid.UUID, tracer: TraceHandler, run_event: dict) -> None:
    """Persist the run's trace and usage. Never raises: a lost trace must not lose the answer."""
    try:
        async with user_repo(user_id) as repo:
            await repo.add_trace_events([run_event, *tracer.events])
            for model_name, (tokens_in, tokens_out) in tracer.usage.items():
                await repo.add_usage(run_event["run_id"], model_name, tokens_in, tokens_out)  # cost: chunk D
    except Exception:
        log.exception("Failed to save trace/usage for run %s", run_event["run_id"])


async def arun_agent(user_id: uuid.UUID, question: str | None = None, task: str = "chat",
                     thread_id: str | None = None, resume: dict | None = None,
                     parent_run_id: str | None = None, *, model: BaseChatModel | None = None,
                     use_mcp: bool = True, on_event: EventSink | None = None) -> AgentResult:
    """`model` and `use_mcp` exist for tests: a scripted fake model, and no MCP subprocess."""
    if (question is None) == (resume is None):
        raise ValueError("Pass a question for a new turn, or resume=... to continue a paused run.")
    if resume is not None and not thread_id:
        raise ValueError("Resuming needs the paused run's thread_id.")
    if thread_id:
        check_thread(user_id, thread_id)
    thread_id = thread_id or new_thread_id(user_id, task)

    async with user_repo(user_id) as repo:
        profile = await repo.get_profile()                  # NotFound if the user doesn't exist
        await repo.touch_thread(thread_id, task, question)  # NotFound if it's someone else's thread

    run_uuid = uuid.uuid4()
    run_id = str(run_uuid)
    run_name = f"agent:{task}" + (":resume" if resume is not None else "")
    started_at, t0 = utcnow(), time.perf_counter()
    status, answer, error, messages, pending = "ok", "", None, [], []
    tracer = TraceHandler(run_id, emit=on_event)

    try:
        async with contextlib.AsyncExitStack() as stack:
            checkpointer = await stack.enter_async_context(open_checkpointer())
            mcp_tools = []
            if use_mcp:
                session = await stack.enter_async_context(get_mcp_client().session("macro"))
                mcp_tools = await load_mcp_tools(session)   # one MCP server process for the whole run
            tracer.mcp_tools = {t.name for t in mcp_tools}
            skills = discover_skills()
            tools = [
                *make_local_tools(user_id),
                *make_write_tools(user_id),
                *mcp_tools,
                make_skill_tool(skills),
                make_news_subagent_tool(),
            ]
            policy = Policy.load(unattended=task.startswith("brief"))
            graph = build_graph(model or make_model(), tools, build_system_prompt(profile, catalog_text(skills)),
                                policy=policy, checkpointer=checkpointer)
            if resume is not None:
                graph_input = Command(resume=resume)
            else:
                # If the thread ended on tool calls that never ran (approval abandoned, budget hit),
                # close them out first; the API requires a result for every tool call.
                snap = await graph.aget_state({"configurable": {"thread_id": thread_id}})
                prior = (snap.values or {}).get("messages", []) if snap else []
                fillers = []
                if prior and isinstance(prior[-1], AIMessage) and prior[-1].tool_calls:
                    fillers = [ToolMessage(content="NOT RUN: the user moved on before this action was approved.",
                                           tool_call_id=tc["id"], name=tc["name"], status="error")
                               for tc in prior[-1].tool_calls]
                graph_input = {"messages": [*fillers, HumanMessage(question)], "tool_rounds": 0,
                               "tool_calls_used": 0, "gate": [], "approvals": {}}
            config = {
                "run_id": run_uuid,                    # same id in LangSmith and trace_events
                "run_name": run_name,
                "callbacks": [tracer],
                "configurable": {"thread_id": thread_id},
                # No user content here: checkpoint metadata is stored unencrypted.
                "metadata": {"user_id": str(user_id), "task": task, "app_run_id": run_id,
                             "thread_id": thread_id, "resumes_run_id": parent_run_id},
                "tags": [task],
                "recursion_limit": 50,
            }
            with activate(tracer):
                # Streaming mode makes the model stream its output; the tracer forwards main-agent tokens.
                async for _ in graph.astream(graph_input, config=config, stream_mode="messages"):
                    pass
            final = await graph.aget_state({"configurable": {"thread_id": thread_id}})

        interrupts = [i for task_ in final.tasks for i in task_.interrupts]
        if interrupts:
            status = "paused"
            pending = list((interrupts[0].value or {}).get("requests", []))
            tracer.emit({"type": "approval_required", "run_id": run_id, "thread_id": thread_id,
                         "requests": pending})
        else:
            messages = final.values.get("messages", [])
            answer = final_text(messages)
        tracer.emit({"type": "done", "status": status, "run_id": run_id, "thread_id": thread_id,
                     "answer": answer})
    except Exception as e:
        cause = _root_cause(e)
        status, error = "error", f"{type(cause).__name__}: {cause}"
        tracer.emit({"type": "error", "run_id": run_id, "message": error})
        raise cause from None
    finally:
        await _save_run(user_id, tracer, {
            "run_id": run_id, "root_run_id": run_id, "parent_run_id": parent_run_id,
            "event_type": "run", "name": run_name, "status": status, "error": error,
            "input": {"question": question, "task": task, "thread_id": thread_id, "resume": resume},
            "output": ({"answer": answer[:2000]} if answer else {"pending_approval": pending} if pending else None),
            "started_at": started_at, "ended_at": utcnow(),
            "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
        })

    return AgentResult(run_id, thread_id, answer, status, round(time.perf_counter() - t0, 1), pending, messages)


async def delete_thread(user_id: uuid.UUID, thread_id: str) -> None:
    """Delete a conversation for real: its saved messages (checkpoints) and its thread row."""
    check_thread(user_id, thread_id)
    async with user_repo(user_id) as repo:
        await repo.get_thread(thread_id)          # NotFound unless it's this user's thread
    await delete_thread_checkpoints(thread_id)
    async with user_repo(user_id) as repo:
        await repo.delete_thread(thread_id)


async def get_thread_state(user_id: uuid.UUID, thread_id: str) -> dict:
    """Saved messages for one of this user's threads, plus any approval it's paused on."""
    check_thread(user_id, thread_id)
    async with open_checkpointer() as saver:
        tup = await saver.aget_tuple({"configurable": {"thread_id": thread_id}})
    if not tup:
        return {"messages": [], "pending": []}
    values = tup.checkpoint.get("channel_values", {}) or {}
    messages = values.get("messages", []) or []
    pending = []
    if messages and isinstance(messages[-1], AIMessage) and messages[-1].tool_calls:
        pending = [{"id": g["id"], "tool": g["name"], "args": g["args"], "reason": g["reason"]}
                   for g in values.get("gate") or [] if g["action"] == "ask"]
    return {"messages": messages, "pending": pending}