"""Run one real question and print its complete trace: the request, every LLM decision, each tool's
input and result (skills, MCP and the subagent included), permission checks, and the final answer.
Costs about 1-2 cents.

    uv run python -m app.cli seed-demo smoke-test@foxhood.local --persona aggressive --replace   # once
    uv run python -m tests.show_trace
    uv run python -m tests.show_trace "your own question"
"""
from __future__ import annotations

import asyncio
import json
import sys

from sqlalchemy import func, select

from agent.runner import arun_agent
from db.models import Usage
from db.repo import AdminRepo, UserRepo
from db.session import SessionLocal

EMAIL = "smoke-test@foxhood.local"
DEFAULT_QUESTION = "Should I be worried about my NVDA position, given the latest news and where interest rates are?"
LABELS = {"llm": "LLM", "tool": "TOOL", "mcp": "MCP TOOL", "skill": "SKILL", "subagent": "SUBAGENT",
          "memory": "MEMORY", "permission": "PERMISSION", "error": "ERROR"}


def short(value, limit: int = 700) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + " ...[cut]"


async def main() -> int:
    question = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_QUESTION
    async with SessionLocal() as s:
        user = await AdminRepo(s).get_or_create_user(EMAIL)
    result = await arun_agent(user.id, question)
    async with SessionLocal() as s:
        events = await UserRepo(s, user.id).get_run_events(result.run_id)
        cost = (await s.execute(select(func.coalesce(func.sum(Usage.cost_usd), 0))
                                .where(Usage.run_id == result.run_id))).scalar_one()

    print(f"USER REQUEST: {question}\n")
    depth = {result.run_id: 0}
    step = 0
    for e in events:
        if e["event_type"] == "run":
            continue
        d = depth.get(e["parent_run_id"], 0) + 1
        depth[e["run_id"]] = d
        pad = "    " * (d - 1)
        label = LABELS.get(e["event_type"], e["event_type"].upper())
        if e["event_type"] == "llm":
            step += 1
            out = e["output"] or {}
            calls = out.get("tool_calls") or []
            usage = out.get("usage") or {}
            print(f"{pad}[{step}] {label} ({e['name']}, {usage.get('input_tokens')} in / "
                  f"{usage.get('output_tokens')} out tokens, {e['duration_ms']:.0f} ms)")
            for c in calls:
                print(f"{pad}    decided to call: {c['name']}({short(c['args'], 300)})")
            if not calls and out.get("text"):
                print(f"{pad}    wrote: {short(out['text'], 300)}")
        elif e["event_type"] == "permission":
            print(f"{pad}  [{label}] {e['name']} -> {e['status'].upper()}: {short((e['output'] or {}).get('reason'))}")
        else:
            print(f"{pad}  [{label}] {e['name']}  ({e['status']}, {e['duration_ms']:.0f} ms)")
            print(f"{pad}      input:  {short(e['input'], 300)}")
            print(f"{pad}      result: {short(e['output'] if e['output'] is not None else e['error'])}")
    print(f"\nFINAL RESPONSE:\n{result.answer}\n")
    print(f"status={result.status} | {result.duration_s}s | {step} LLM calls | cost ${cost:.4f} | run_id={result.run_id}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))