"""Run the main agent for one request: open MCP session, build tools + graph, trace everything."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from langchain_core.messages import HumanMessage
from langchain_mcp_adapters.tools import load_mcp_tools

from agent.graph import build_graph, final_text
from agent.mcp_client import get_mcp_client
from agent.models import make_model
from agent.prompts import build_system_prompt
from agent.skills import catalog_text, discover_skills, make_skill_tool
from agent.subagents.news_analyst import make_news_subagent_tool
from agent.tools import make_local_tools
from agent.tracing import TraceHandler, now_iso
from core.async_utils import run_sync
from storage import db


@dataclass
class AgentResult:
    run_id: str
    answer: str
    status: str
    duration_s: float
    messages: list = field(default_factory=list)


def _root_cause(e: BaseException) -> BaseException:
    """anyio/MCP wrap errors in ExceptionGroups; dig out the real one."""
    while isinstance(e, BaseExceptionGroup) and e.exceptions:
        e = e.exceptions[0]
    return e


async def arun_agent(user_id: int, question: str, task: str = "chat") -> AgentResult:
    user = db.get_user(user_id)
    if not user:
        raise ValueError(f"No user with id {user_id}")

    run_uuid = uuid.uuid4()
    run_id = str(run_uuid)
    started_at, t0 = now_iso(), time.perf_counter()
    status, answer, error, messages = "ok", "", None, []

    try:
        client = get_mcp_client()
        async with client.session("macro") as session:  # one MCP server process for the whole run
            mcp_tools = await load_mcp_tools(session)
            skills = discover_skills()
            tools = [
                *make_local_tools(user_id),
                *mcp_tools,
                make_skill_tool(skills),
                make_news_subagent_tool(),
            ]
            graph = build_graph(make_model(), tools, build_system_prompt(user, catalog_text(skills)))
            tracer = TraceHandler(run_id, user_id, {t.name for t in mcp_tools})
            result = await graph.ainvoke(
                {"messages": [HumanMessage(question)], "tool_rounds": 0},
                config={
                    "run_id": run_uuid,                    # same id in LangSmith and trace_events
                    "run_name": f"agent:{task}",
                    "callbacks": [tracer],
                    "metadata": {"user_id": user_id, "task": task, "app_run_id": run_id},
                    "tags": [task, f"user:{user_id}"],
                    "recursion_limit": 50,
                },
            )
        messages = result["messages"]
        answer = final_text(messages)
    except Exception as e:
        cause = _root_cause(e)
        status, error = "error", f"{type(cause).__name__}: {cause}"
        raise cause from None
    finally:
        db.log_trace_event(
            run_id=run_id, root_run_id=run_id, event_type="run", name=f"agent:{task}",
            user_id=user_id, input={"question": question, "task": task},
            output={"answer": answer[:2000]} if answer else None,
            status=status, error=error, started_at=started_at, ended_at=now_iso(),
            duration_ms=round((time.perf_counter() - t0) * 1000, 1),
        )

    return AgentResult(run_id, answer, status, round(time.perf_counter() - t0, 1), messages)


def run_agent(user_id: int, question: str, task: str = "chat") -> AgentResult:
    """Sync wrapper for Streamlit and scripts."""
    return run_sync(arun_agent(user_id, question, task))