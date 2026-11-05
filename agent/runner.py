"""Run the main agent for one turn, or resume a run paused for approval.

Every run: MCP session + tools + policy-gated graph + SQLite checkpointer + tracing.
A paused run returns status="paused" with pending approval requests; resume it with
run_agent(..., resume={...}, thread_id=<same thread>, parent_run_id=<paused run id>)."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from langchain_core.messages import HumanMessage
from langchain_mcp_adapters.tools import load_mcp_tools
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from agent.graph import build_graph, final_text
from agent.mcp_client import get_mcp_client
from agent.models import make_model
from agent.permissions import Policy
from agent.prompts import build_system_prompt
from agent.skills import catalog_text, discover_skills, make_skill_tool
from agent.subagents.news_analyst import make_news_subagent_tool
from agent.tools import make_local_tools
from agent.tracing import TraceHandler, now_iso
from agent.write_tools import make_write_tools
from core.async_utils import run_sync
from core.config import settings
from storage import db

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


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


async def arun_agent(user_id: int, question: str | None = None, task: str = "chat",
                     thread_id: str | None = None, resume: dict | None = None,
                     parent_run_id: str | None = None) -> AgentResult:
    if (question is None) == (resume is None):
        raise ValueError("Pass a question for a new turn, or resume=... to continue a paused run.")
    if resume is not None and not thread_id:
        raise ValueError("Resuming needs the paused run's thread_id.")
    user = db.get_user(user_id)
    if not user:
        raise ValueError(f"No user with id {user_id}")

    thread_id = thread_id or f"{task}-u{user_id}-{uuid.uuid4().hex[:8]}"
    run_uuid = uuid.uuid4()
    run_id = str(run_uuid)
    started_at, t0 = now_iso(), time.perf_counter()
    status, answer, error, messages, pending = "ok", "", None, [], []

    try:
        async with AsyncSqliteSaver.from_conn_string(str(settings.checkpoint_path)) as checkpointer:
            client = get_mcp_client()
            async with client.session("macro") as session:  # one MCP server process for the whole run
                mcp_tools = await load_mcp_tools(session)
                skills = discover_skills()
                tools = [
                    *make_local_tools(user_id),
                    *make_write_tools(user_id),
                    *mcp_tools,
                    make_skill_tool(skills),
                    make_news_subagent_tool(),
                ]
                policy = Policy.load(unattended=task.startswith("brief"))
                graph = build_graph(make_model(), tools, build_system_prompt(user, catalog_text(skills)),
                                    policy=policy, checkpointer=checkpointer)
                tracer = TraceHandler(run_id, user_id, {t.name for t in mcp_tools})
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
                result = await graph.ainvoke(graph_input, config={
                    "run_id": run_uuid,                    # same id in LangSmith and trace_events
                    "run_name": f"agent:{task}" + (":resume" if resume is not None else ""),
                    "callbacks": [tracer],
                    "configurable": {"thread_id": thread_id},
                    "metadata": {"user_id": user_id, "task": task, "app_run_id": run_id,
                                 "thread_id": thread_id, "resumes_run_id": parent_run_id},
                    "tags": [task, f"user:{user_id}"],
                    "recursion_limit": 50,
                })

        interrupts = result.get("__interrupt__") or []
        if interrupts:
            status = "paused"
            pending = list((interrupts[0].value or {}).get("requests", []))
        else:
            messages = result["messages"]
            answer = final_text(messages)
    except Exception as e:
        cause = _root_cause(e)
        status, error = "error", f"{type(cause).__name__}: {cause}"
        raise cause from None
    finally:
        db.log_trace_event(
            run_id=run_id, root_run_id=run_id, parent_run_id=parent_run_id, event_type="run",
            name=f"agent:{task}" + (":resume" if resume is not None else ""), user_id=user_id,
            input={"question": question, "task": task, "thread_id": thread_id, "resume": resume},
            output=({"answer": answer[:2000]} if answer else {"pending_approval": pending} if pending else None),
            status=status, error=error, started_at=started_at, ended_at=now_iso(),
            duration_ms=round((time.perf_counter() - t0) * 1000, 1),
        )

    return AgentResult(run_id, thread_id, answer, status, round(time.perf_counter() - t0, 1), pending, messages)


def run_agent(user_id: int, question: str | None = None, task: str = "chat", thread_id: str | None = None,
              resume: dict | None = None, parent_run_id: str | None = None) -> AgentResult:
    """Sync wrapper for Streamlit and scripts."""
    return run_sync(arun_agent(user_id, question, task, thread_id, resume, parent_run_id))

async def aget_thread_state(thread_id: str) -> dict:
    """Saved messages for a chat thread, plus any approval it's paused on (survives restarts)."""
    async with AsyncSqliteSaver.from_conn_string(str(settings.checkpoint_path)) as saver:
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


def get_thread_state(thread_id: str) -> dict:
    return run_sync(aget_thread_state(thread_id))