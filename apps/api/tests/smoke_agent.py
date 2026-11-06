"""Run from the repo root:
    python -m tests.smoke_agent                         # two demo questions (Alex, Dan)
    python -m tests.smoke_agent --user 2 "your question"
"""
from __future__ import annotations

import argparse
from datetime import datetime

from agent.runner import run_agent
from storage import db

DEMO = [
    (1, "How did my portfolio do today, and is there anything I should be worried about?"),
    (3, "Any oil stocks I should look at?"),
]


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s)


def show(user_id: int, question: str) -> None:
    user = db.get_user(user_id)
    print("=" * 100)
    print(f"USER {user_id}: {user['name']} ({user['persona']})\nQ: {question}\n")

    r = run_agent(user_id, question)
    print("--- ANSWER ---")
    print(r.answer)

    events = db.get_run_events(r.run_id)
    root = next(e for e in events if e["event_type"] == "run")
    t_root = _ts(root["started_at"])

    print("\n--- TOOL CALLS THE LLM CHOSE ---")
    for e in events:
        if e["event_type"] == "llm":
            for tc in (e["output"] or {}).get("tool_calls", []):
                print(f"  {tc['name']}({tc['args']})")

    print("\n--- TOOL RESULTS (preview) ---")
    for e in events:
        if e["event_type"] in {"tool", "mcp", "memory"}:
            out = str(e["output"])[:160].replace("\n", " ")
            print(f"  [{e['event_type']}] {e['name']} {e['input']} -> {out}")

    print("\n--- TRACE TIMELINE ---")
    depth: dict[str, int] = {}
    for e in events:
        depth[e["run_id"]] = 0 if e["event_type"] == "run" else depth.get(e["parent_run_id"], 0) + 1
        offset = (_ts(e["started_at"]) - t_root).total_seconds() * 1000
        dur = f"{e['duration_ms']:.0f}ms" if e["duration_ms"] is not None else "-"
        print(f"  +{offset:7.0f}ms {'  ' * depth[e['run_id']]}{e['event_type']:9} "
              f"{e['name']:26} {e['status']:6} {dur}")

    llm = [e for e in events if e["event_type"] == "llm"]
    tokens = sum((((e["output"] or {}).get("usage") or {}).get("total_tokens") or 0) for e in llm)
    print(f"\n  {len(llm)} LLM calls | {tokens:,} tokens | {r.duration_s}s | run_id {r.run_id}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", type=int)
    parser.add_argument("question", nargs="?")
    args = parser.parse_args()

    try:
        if args.question:
            show(args.user or 1, args.question)
        else:
            for uid, q in DEMO:
                show(uid, q)
    finally:
        try:
            from langchain_core.tracers.langchain import wait_for_all_tracers
            wait_for_all_tracers()  # flush LangSmith uploads before the script exits
        except Exception:
            pass
    print("\nLangSmith: open project 'investment-research-agent'; the run ids above match the root runs there.")