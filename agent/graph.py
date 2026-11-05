"""The main agent loop as an explicit LangGraph StateGraph.

With a policy (main agent):
    START -> agent --(tool calls)--> gate --(any "ask")--> approval (interrupt) --> tools -> agent
                                          \\--(none)------------------------------> tools -> agent
          agent --(final answer)--> END
Without a policy (subagents): agent -> tools -> agent ... -> END

The LLM decides every step; the policy decides whether each requested tool may run."""
from __future__ import annotations

import asyncio
import uuid
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import interrupt

from agent.permissions import Decision, Policy
from agent.prompts import BUDGET_NOTE
from agent.tracing import content_to_text
from storage import db

MAX_TOOL_ROUNDS = 10


class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    tool_rounds: int
    tool_calls_used: int
    gate: list[dict]      # policy decision for each pending tool call
    approvals: dict       # tool_call_id -> {"approved": bool, "by": str, "note": str}


def final_text(messages: list) -> str:
    """Text of the agent's final answer (last AI message with text)."""
    for m in reversed(messages):
        if isinstance(m, AIMessage):
            text = content_to_text(m.content).strip()
            if text:
                return text
            if m.tool_calls:
                return "I hit my tool budget before finishing. Try a narrower question."
    return "(no answer)"


def _log_permission(config: RunnableConfig, entry: dict, status: str, extra: dict | None = None) -> None:
    md = (config or {}).get("metadata") or {}
    root = md.get("app_run_id")
    if not root:
        return
    db.log_trace_event(
        run_id=str(uuid.uuid4()), parent_run_id=root, root_run_id=root, user_id=md.get("user_id"),
        event_type="permission", name=entry["name"],
        input={"args": entry["args"], "rule": entry["rule"]},
        output={"reason": entry["reason"], **(extra or {})}, status=status,
    )


def build_graph(model, tools: list, system_prompt: str, max_tool_rounds: int = MAX_TOOL_ROUNDS,
                policy: Policy | None = None, checkpointer=None):
    model_with_tools = model.bind_tools(tools)
    tools_by_name = {t.name: t for t in tools}

    async def agent_node(state: AgentState, config: RunnableConfig) -> dict:
        over_budget = state.get("tool_rounds", 0) >= max_tool_rounds
        prompt = system_prompt + (BUDGET_NOTE if over_budget else "")
        response = await model_with_tools.ainvoke([SystemMessage(prompt), *state["messages"]], config)
        return {"messages": [response]}

    async def gate_node(state: AgentState, config: RunnableConfig) -> dict:
        used = state.get("tool_calls_used", 0)
        gate = []
        for call in state["messages"][-1].tool_calls:
            if used >= policy.max_tool_calls:
                d = Decision("deny", "budget", f"Tool-call budget of {policy.max_tool_calls} per run reached.")
            else:
                d = await asyncio.to_thread(policy.check, call["name"], call["args"])  # may look up a ticker
            used += 1
            entry = {"id": call["id"], "name": call["name"], "args": call["args"],
                     "action": d.action, "rule": d.rule, "reason": d.reason}
            gate.append(entry)
            if d.action == "deny":
                _log_permission(config, entry, "denied")
            elif d.action == "ask":
                _log_permission(config, entry, "pending")
        return {"gate": gate, "approvals": {}, "tool_calls_used": used}

    async def approval_node(state: AgentState, config: RunnableConfig) -> dict:
        asks = [g for g in state.get("gate") or [] if g["action"] == "ask"]
        # Pauses the run here. On resume, interrupt() returns the payload passed to Command(resume=...).
        response = interrupt({
            "kind": "approval_required",
            "requests": [{"id": g["id"], "tool": g["name"], "args": g["args"], "reason": g["reason"]} for g in asks],
        })
        response = response if isinstance(response, dict) else {}
        decisions, by = response.get("decisions") or {}, response.get("by", "user")
        approvals = {}
        for g in asks:
            d = decisions.get(g["id"]) or {}
            ok = bool(d.get("approved"))
            approvals[g["id"]] = {"approved": ok, "by": by, "note": d.get("note")}
            _log_permission(config, g, "approved" if ok else "rejected", {"by": by, "note": d.get("note")})
        return {"approvals": approvals}

    async def tools_node(state: AgentState, config: RunnableConfig) -> dict:
        last = state["messages"][-1]
        cfg = {k: v for k, v in config.items() if k != "run_id"}  # each tool gets its own run id
        gate = {g["id"]: g for g in state.get("gate") or []} if policy else {}
        approvals = state.get("approvals") or {}

        async def run_one(call: dict) -> ToolMessage:
            g = gate.get(call["id"])
            if g and g["action"] == "deny":
                return ToolMessage(content=f"DENIED by policy ({g['rule']}): {g['reason']} "
                                           "Do not retry or work around this; tell the user.",
                                   tool_call_id=call["id"], name=call["name"], status="error")
            if g and g["action"] == "ask" and not (approvals.get(call["id"]) or {}).get("approved"):
                return ToolMessage(content="NOT APPROVED: the user declined this action, so it was not "
                                           "performed. Do not retry; tell the user it wasn't done.",
                                   tool_call_id=call["id"], name=call["name"], status="error")
            tool = tools_by_name.get(call["name"])
            if tool is None:
                return ToolMessage(content=f"Error: unknown tool '{call['name']}'.",
                                   tool_call_id=call["id"], name=call["name"], status="error")
            try:
                result = await tool.ainvoke(call["args"], config=cfg)
                return ToolMessage(content=content_to_text(result) or "(empty result)",
                                   tool_call_id=call["id"], name=call["name"])
            except Exception as e:  # send the error back to the model instead of crashing the run
                return ToolMessage(content=f"Error: {type(e).__name__}: {e}",
                                   tool_call_id=call["id"], name=call["name"], status="error")

        results = await asyncio.gather(*(run_one(c) for c in last.tool_calls))
        return {"messages": list(results), "tool_rounds": state.get("tool_rounds", 0) + 1}

    def route(state: AgentState) -> str:
        last = state["messages"][-1]
        if getattr(last, "tool_calls", None) and state.get("tool_rounds", 0) < max_tool_rounds:
            return "next"
        return END

    def route_after_gate(state: AgentState) -> str:
        return "approval" if any(g["action"] == "ask" for g in state.get("gate") or []) else "tools"

    g = StateGraph(AgentState)
    g.add_node("agent", agent_node)
    g.add_node("tools", tools_node)
    g.add_edge(START, "agent")
    if policy is not None:
        g.add_node("gate", gate_node)
        g.add_node("approval", approval_node)
        g.add_conditional_edges("agent", route, {"next": "gate", END: END})
        g.add_conditional_edges("gate", route_after_gate, {"approval": "approval", "tools": "tools"})
        g.add_edge("approval", "tools")
    else:
        g.add_conditional_edges("agent", route, {"next": "tools", END: END})
    g.add_edge("tools", "agent")
    return g.compile(checkpointer=checkpointer)