"""Run from the repo root:
    python -m tests.smoke_briefs              # all 3 users, current slot
    python -m tests.smoke_briefs --users 1    # just Alex
"""
from __future__ import annotations

import argparse
from datetime import datetime

from agent.briefs import get_or_create_brief
from agent.skills import discover_skills
from core.market_clock import current_brief_slot
from datasources.market import ET
from storage import db
import json

EXPECTED_SKILL = {"premarket": "premarket-brief", "close": "post-close-recap"}


def clock_checks():
    print("=== market clock ===")
    cases = [
        ("Thu 11/05 11:00 am", datetime(2026, 11, 5, 11, 0, tzinfo=ET)),
        ("Thu 11/05 4:30 pm", datetime(2026, 11, 5, 16, 30, tzinfo=ET)),
        ("Sat 11/07 10:00 am", datetime(2026, 11, 7, 10, 0, tzinfo=ET)),
        ("Thanksgiving 11/26", datetime(2026, 11, 26, 12, 0, tzinfo=ET)),
        ("Black Friday 2:00 pm (1 pm close)", datetime(2026, 11, 27, 14, 0, tzinfo=ET)),
    ]
    for label, t in cases:
        s = current_brief_slot(t)
        print(f"  {label:36} -> {s.session:9} for {s.brief_date}  ({s.reason})")


def print_trace(run_id: str) -> list[dict]:
    events = db.get_run_events(run_id)
    t_root = datetime.fromisoformat(next(e for e in events if e["event_type"] == "run")["started_at"])
    depth: dict[str, int] = {}
    for e in events:
        depth[e["run_id"]] = 0 if e["event_type"] == "run" else depth.get(e["parent_run_id"], 0) + 1
        offset = (datetime.fromisoformat(e["started_at"]) - t_root).total_seconds() * 1000
        dur = f"{e['duration_ms']:.0f}ms" if e["duration_ms"] is not None else "-"
        detail = ""
        if e["event_type"] in {"skill", "subagent", "memory", "mcp"} and isinstance(e["input"], dict):
            detail = " " + str(e["input"])[:70]
        print(f"  +{offset:7.0f}ms {'  ' * depth[e['run_id']]}{e['event_type']:9} {e['name']:26} "
              f"{e['status']:6} {dur:>8}{detail}")
    llm = [e for e in events if e["event_type"] == "llm"]
    tokens = sum((((e["output"] or {}).get("usage") or {}).get("total_tokens") or 0) for e in llm)
    print(f"  {len(llm)} LLM calls | {tokens:,} tokens")
    return events

def _n_memories(e: dict) -> int:
    try:
        return len(json.loads(e["output"]).get("memories", []))
    except (TypeError, ValueError, AttributeError):
        return 0

def checks(events: list[dict], session: str) -> list[tuple[str, bool]]:
    loaded = [(e["input"] or {}).get("name") for e in events
              if e["event_type"] == "skill" and isinstance(e["input"], dict)]
    subs = [e for e in events if e["event_type"] == "subagent"]
    sub_ids = {s["run_id"] for s in subs}
    sub_children = [e for e in events if e["parent_run_id"] in sub_ids]
    return [
        (f"agent chose skill '{EXPECTED_SKILL[session]}'", EXPECTED_SKILL[session] in loaded),
        ("delegated to news subagent", bool(subs)),
        ("subagent ran its own LLM + tool calls (nested)",
         any(c["event_type"] == "llm" for c in sub_children) and any(c["event_type"] == "tool" for c in sub_children)),
        ("recall_memory returned saved memories",
         any(_n_memories(e) > 0 for e in events if e["event_type"] == "memory")),
        ("used MCP macro tools", any(e["event_type"] == "mcp" for e in events)),
        ("no errors in trace", not any(e["status"] == "error" for e in events)),
    ]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--users", type=int, nargs="+", default=[1, 2, 3])
    args = parser.parse_args()

    clock_checks()
    print("\n=== skills discovered ===")
    for s in discover_skills().values():
        print(f"  {s.name}: {s.description[:90]}...")

    slot = current_brief_slot()
    print(f"\n=== current slot: {slot.session} for {slot.brief_date} ({slot.reason}) ===")

    summary = []
    try:
        for uid in args.users:
            user = db.get_user(uid)
            print("\n" + "=" * 100 + f"\n{user['name']} ({user['persona']})\n" + "=" * 100)
            b = get_or_create_brief(uid, slot, force=True)
            print(b["content_md"])
            print("\n--- trace ---")
            events = print_trace(b["run_id"])
            print("\n--- checks ---")
            results = checks(events, slot.session)
            again = get_or_create_brief(uid, slot)
            results.append(("second call served from cache", again["cached"] and again["run_id"] == b["run_id"]))
            for label, ok in results:
                print(f"  {'PASS' if ok else 'FAIL'}  {label}")
            summary.append((user["name"], sum(ok for _, ok in results), len(results), b["run_id"]))
    finally:
        try:
            from langchain_core.tracers.langchain import wait_for_all_tracers
            wait_for_all_tracers()
        except Exception:
            pass

    print("\n=== SUMMARY ===")
    for name, passed, total, rid in summary:
        print(f"  {name:12} {passed}/{total} checks | run {rid}")