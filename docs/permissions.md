# Permission policy

All tool calls from the main agent pass through a policy check **before** the tool runs
(`gate` node in `agent/graph.py`). The policy lives in `config/permissions.yaml`, so it can be
changed without touching code.

## Decisions
| Decision | Effect | Tools |
|---|---|---|
| **allow** | Runs immediately | Read-only tools: portfolio, positions, watchlist snapshot, price performance, company profile, recall_memory, load_skill, news subagent, MCP macro tools |
| **ask** | Run pauses; the user must approve or reject | add_to_watchlist, remove_from_watchlist, add_holding, remember |
| **deny** | Never runs; the agent is told why | submit_trade_order (research-only app), plus any tool not listed (default: deny) |

## Evaluation order
1. **Deny list**: `submit_trade_order` is always denied.
2. **Argument and content rules**
   - `remember`: denied if the content looks like an SSN or an account/card number.
   - `add_holding`: denied if the position would be worth more than $100,000 (likely a typo).
   - `add_to_watchlist`, `add_holding`: denied if the ticker has no recent price data.
3. **Unattended mode**: in scheduled runs (daily briefs) nobody is present to approve, so every
   "ask" becomes "deny".
4. **Ask list**, then **allow list**, then the **default** (deny).

A per-run budget of 40 main-agent tool calls is also enforced; calls over budget are denied.

## How approval works
The `approval` node calls LangGraph's `interrupt()`. The run's state is saved to
`checkpoints.db` (SQLite checkpointer) and the run returns `status="paused"` with the pending
requests. The app shows Approve / Reject; the run then resumes from the same point via
`Command(resume=...)` in a new linked run (its `parent_run_id` is the paused run).
Approved calls execute; rejected ones return "NOT APPROVED" to the model, which must tell the user.

## Audit trail
Every non-trivial decision is written to `trace_events` as a `permission` event:
`pending` (approval requested), `approved`, `rejected`, or `denied`. Each records the tool,
its arguments, the rule that matched, the reason, and who approved.