"""The main agent loop as an explicit LangGraph StateGraph.

    START -> agent --(tool calls & under budget)--> tools -> agent ... --(final answer)--> END

The LLM decides every step: which tools to call (if any), and when it's done."""
from __future__ import annotations

import asyncio
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from agent.prompts import BUDGET_NOTE
from agent.tracing import content_to_text

MAX_TOOL_ROUNDS = 10


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    tool_rounds: int


def build_graph(model, tools: list, system_prompt: str, max_tool_rounds: int = MAX_TOOL_ROUNDS):
    model_with_tools = model.bind_tools(tools)
    tools_by_name = {t.name: t for t in tools}

    async def agent_node(state: AgentState, config: RunnableConfig) -> dict:
        over_budget = state["tool_rounds"] >= max_tool_rounds
        prompt = system_prompt + (BUDGET_NOTE if over_budget else "")
        response = await model_with_tools.ainvoke([SystemMessage(prompt), *state["messages"]], config)
        return {"messages": [response]}

    async def tools_node(state: AgentState, config: RunnableConfig) -> dict:
        last = state["messages"][-1]
        cfg = {k: v for k, v in config.items() if k != "run_id"}  # each tool gets its own run id

        async def run_one(call: dict) -> ToolMessage:
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
        return {"messages": list(results), "tool_rounds": state["tool_rounds"] + 1}

    def route(state: AgentState) -> str:
        last = state["messages"][-1]
        if getattr(last, "tool_calls", None) and state["tool_rounds"] < max_tool_rounds:
            return "tools"
        return END

    g = StateGraph(AgentState)
    g.add_node("agent", agent_node)
    g.add_node("tools", tools_node)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", route, {"tools": "tools", END: END})
    g.add_edge("tools", "agent")
    return g.compile()