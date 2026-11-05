# Failure log

## 1. Model rejected `temperature` (2026-11-04)
- **Run:** 'c023dfe0-0a45-4f47-b0b1-0842b25a556a'
- **Symptom:** first agent run crashed before any tool call.
- **Trace:** run status=error; the first `llm` event errored with
  `400 invalid_request_error: temperature: Extra inputs are not permitted`. No tool events,
  so the failure happened on the first model call, not in tools or MCP.
- **Cause:** ChatAnthropic was configured with `temperature=0.2`; this model doesn't accept it.
- **Fix:** removed `temperature` from `make_model()`. Also unwrapped anyio ExceptionGroups so the
  trace records the root cause instead of "unhandled errors in a TaskGroup".
- **Verified:** re-ran `tests.smoke_agent`; run status=ok.

## 2. Agent ignored a saved risk rule (2026-11-04)
- **Run:** df4e5fcc-d028-40c1-a4e3-f2a64d09310e
- **Symptom:** asked "anything I should be worried about?", the agent flagged NVDA at 49% but never
  mentioned Alex's saved rule (alert above 30% per position).
- **Trace:** tool calls were get_portfolio_summary, get_positions, get_macro_snapshot.
  No `memory` event in the run, so the rule was never retrieved.
- **Cause:** system prompt only required recall_memory "before recommendations"; a risk question
  didn't qualify.
- **Fix:** prompt now requires recall_memory for any question about the user's portfolio, risks,
  goals or ideas.
- **Also found:** parallel tools both computed the portfolio (7.3s + 4.6s); added a lock.
  Added SPY's day change to the summary after the agent said it couldn't compare today's move.
- **Verified:** 9bbddc73-069f-4b0a-b565-673df40f0a49, recall_memory called first, 30% rule cited, tools 1.8s/0.95s