"""One real Claude conversation through the agent, to check what the fake-model tests can't:
live token streaming, real token costs, and the shared news cache. Costs about 1-2 cents.

    uv run python -m tests.smoke_live

Run 1 should research the news (from_cache: []); run 2 asks again in a new thread and should get
the same analysis instantly from the shared cache (from_cache: ['AAPL'])."""
from __future__ import annotations

import asyncio
import json
import sys

from langchain_core.messages import ToolMessage

from agent.runner import arun_agent
from core.config import settings as core_settings
from db.repo import AdminRepo, UserRepo
from db.session import SessionLocal

QUESTION = "Any notable news on AAPL today? Keep it to two sentences."
SMOKE_EMAIL = "smoke-test@foxhood.local"
streamed: list[str] = []


def show(ev: dict) -> None:
    kind = ev["type"]
    if kind == "token":
        streamed.append(ev["text"])
        print(ev["text"], end="", flush=True)
    elif kind == "tool_start":
        print(f"\n  [tool] {ev['name']} ...", flush=True)
    elif kind == "tool_end":
        print(f"  [tool] {ev['name']} -> {ev['status']}", flush=True)
    elif kind in ("denied", "approval_required", "error"):
        print(f"\n  [{kind}] {ev}", flush=True)


def news_cache_hits(result) -> list | None:
    for m in result.messages:
        if isinstance(m, ToolMessage) and m.name == "delegate_news_analysis":
            try:
                return json.loads(m.content).get("from_cache", [])
            except (ValueError, AttributeError):
                return None
    return None


async def main() -> int:
    missing = core_settings.missing_keys()
    if missing:
        print(f"Missing in apps/api/.env: {', '.join(missing)}")
        return 1
    async with SessionLocal() as s:
        user = await AdminRepo(s).get_or_create_user(SMOKE_EMAIL)

    for attempt in (1, 2):
        streamed.clear()
        print(f"\n=== Run {attempt}: {QUESTION}")
        r = await arun_agent(user.id, QUESTION, on_event=show)
        hits = news_cache_hits(r)
        note = "news subagent not called" if hits is None else f"news from cache: {hits}"
        print(f"\n--> status={r.status}, {r.duration_s}s, {note}")
        joined = "".join(streamed)
        print(f"--> streamed text identical to saved answer: {joined == r.answer}")
        if joined != r.answer:
            i = next((k for k, (a, b) in enumerate(zip(joined, r.answer, strict=False)) if a != b), min(len(joined), len(r.answer)))
            print(f"    first difference at char {i}: streamed {joined[i-15:i+15]!r} vs saved {r.answer[i-15:i+15]!r}")
            near = [t for t in streamed if t.strip() in ("%", "to", "weight", "'s")][:8]
            print(f"    chunks around it: {near!r}")

    async with SessionLocal() as s:
        spent = await UserRepo(s, user.id).spent_today()
    print(f"\nSpent today by {SMOKE_EMAIL}: ${spent:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))