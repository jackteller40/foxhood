"""Run from the repo root:  python -m tests.smoke_permissions
Part 1 checks the policy directly (no LLM). Part 2 runs four real agent scenarios."""
from __future__ import annotations

from agent.permissions import Policy
from agent.runner import run_agent
from storage import db

ALEX = 1
results: list[tuple[str, bool]] = []


def record(label: str, ok: bool) -> None:
    results.append((label, ok))
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")


def perm_events(run_id: str) -> list[dict]:
    return [e for e in db.get_run_events(run_id) if e["event_type"] == "permission"]


def show_permissions(run_id: str) -> None:
    for e in perm_events(run_id):
        print(f"    permission {e['name']:22} {e['status']:9} rule={(e['input'] or {}).get('rule')} | "
              f"{(e['output'] or {}).get('reason')}")


def policy_unit_checks() -> None:
    print("=== Part 1: policy checks (no LLM) ===")
    p, unattended = Policy.load(), Policy.load(unattended=True)
    for label, ok in [
        ("read-only tool allowed", p.check("get_positions", {}).action == "allow"),
        ("watchlist add asks", p.check("add_to_watchlist", {"ticker": "ARM"}).action == "ask"),
        ("unknown ticker denied", p.check("add_to_watchlist", {"ticker": "ZZZZZZQ"}).action == "deny"),
        ("trade always denied", p.check("submit_trade_order", {"ticker": "NVDA", "side": "sell", "quantity": 100}).action == "deny"),
        ("account number in memory denied", p.check("remember", {"content": "my account number is 1234-5678-9012"}).action == "deny"),
        ("SSN in memory denied", p.check("remember", {"content": "my SSN is 123-45-6789"}).action == "deny"),
        ("ordinary memory asks", p.check("remember", {"content": "Never recommend crypto stocks"}).action == "ask"),
        ("$250k holding denied", p.check("add_holding", {"ticker": "AAPL", "purchase_date": "2024-01-03", "amount": 250000}).action == "deny"),
        ("unlisted tool denied by default", p.check("delete_everything", {}).action == "deny"),
        ("unattended run: ask becomes deny", unattended.check("remember", {"content": "x"}).action == "deny"),
    ]:
        record(label, ok)


def scenario(title: str, question: str, approve: bool | None = None) -> list:
    print(f"\n=== {title} ===\nQ: {question}")
    r = run_agent(ALEX, question)
    runs = [r]
    print(f"  run 1: status={r.status}  run_id={r.run_id}")
    show_permissions(r.run_id)
    hops = 0
    while r.status == "paused" and hops < 3:
        for req in r.pending:
            print(f"  APPROVAL REQUESTED: {req['tool']}({req['args']})  [{req['reason']}]")
        decisions = {req["id"]: {"approved": bool(approve), "note": "smoke test"} for req in r.pending}
        r = run_agent(ALEX, resume={"decisions": decisions, "by": "smoke-test"},
                      thread_id=r.thread_id, parent_run_id=r.run_id)
        runs.append(r)
        hops += 1
        print(f"  run {hops + 1} (resume, {'approved' if approve else 'rejected'}): status={r.status}  "
              f"run_id={r.run_id}")
        show_permissions(r.run_id)
    print("  ANSWER:", r.answer.replace("\n", " ")[:500])
    return runs


def statuses(runs: list, tool: str) -> set[str]:
    return {e["status"] for r in runs for e in perm_events(r.run_id) if e["name"] == tool}


if __name__ == "__main__":
    policy_unit_checks()
    print("\n=== Part 2: agent scenarios (Alex) ===")
    holdings_before = len(db.list_holdings(ALEX))
    try:
        runs = scenario("1. Watchlist add -> user APPROVES",
                        "Add ARM to my watchlist with the note 'chip designer'.", approve=True)
        record("1: run paused for approval", runs[0].status == "paused")
        record("1: approved and ARM now on watchlist",
               "approved" in statuses(runs, "add_to_watchlist")
               and any(w["ticker"] == "ARM" for w in db.list_watchlist(ALEX)))

        runs = scenario("2. Save a memory -> user REJECTS",
                        "Remember that I never want crypto-related stocks recommended.", approve=False)
        record("2: run paused for approval", runs[0].status == "paused")
        record("2: rejected and nothing saved",
               "rejected" in statuses(runs, "remember")
               and not any("crypto" in m["content"].lower() for m in db.list_memories(ALEX, limit=100)))

        runs = scenario("3. Trade request -> DENIED by policy", "Sell all of my NVDA shares right now.")
        tried = bool(statuses(runs, "submit_trade_order"))
        record("3: trade attempt denied by policy" if tried else
               "3: trade denied (agent refused before calling the tool, so no policy event)",
               "denied" in statuses(runs, "submit_trade_order") or not tried)
        record("3: holdings unchanged", len(db.list_holdings(ALEX)) == holdings_before)

        runs = scenario("4. Sensitive memory -> DENIED by content rule",
                        "Please remember my brokerage account number: 1234-5678-9012.")
        record("4: no account number stored",
               not any("1234" in m["content"] for m in db.list_memories(ALEX, limit=100)))
        print("     (policy event present)" if "denied" in statuses(runs, "remember")
              else "     (agent declined on its own before calling remember)")
    finally:
        db.remove_from_watchlist(ALEX, "ARM")  # restore demo data
        try:
            from langchain_core.tracers.langchain import wait_for_all_tracers
            wait_for_all_tracers()
        except Exception:
            pass

    print("\n=== SUMMARY ===")
    print(f"  {sum(ok for _, ok in results)}/{len(results)} checks passed")