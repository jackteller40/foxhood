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

## 3. News subagent output truncated; main agent retried 3x (2026-11-05)
- **Run:** 05105ea3-5d6e-4906-9c4d-898bb5314b33
- **Symptom:** pre-market brief said "news analyst failed on every attempt". 65s, 110k tokens.
- **Trace:** three `subagent` events, all status=error. Under each: the subagent's LLM + 10 tool
  calls succeeded, its findings LLM call succeeded, then the structuring LLM call ended with
  stop_reason=max_tokens. Parsed args were `{}`, so Pydantic raised "tickers: Field required".
  The main agent then repeated the identical call twice.
- **Cause:** 1,500 max_tokens was too small for 5 tickers x (summary + 3 headlines with URLs);
  the prompt didn't discourage identical retries.
- **Fix:** 4,000 max_tokens and a terser schema (2 headlines, 2-sentence summaries);
  `include_raw=True` with a plain-text fallback (`structured: false`) instead of raising;
  prompt rule: never repeat an identical failing call.
- **Verified:** <re-run id>

## 4. Wrong weekday and "no CPI YoY" in the pre-market brief (2026-11-05)
- **Run:** 9a3dff85-176c-413a-8574-106b45d84112
- **Symptom:** brief said the jobs report was "Thursday, Nov 6" (it's Friday) and that no CPI YoY
  figure was available.
- **Trace:** get_upcoming_releases output had only `"date": "2026-11-06"`, so the weekday was
  computed by the LLM. get_macro_snapshot output had CPI `value: 336.298` (index level) with
  `yoy_pct: 3.72` as a secondary field the model overlooked.
- **Cause:** tool outputs left date math and field interpretation to the model.
- **Fix:** releases include `weekday`; the CPI entry's primary `value` is now YoY inflation %.
- **Lesson:** make tool outputs say what they mean; don't make a small model derive facts.

## 5. Macro snapshot silently empty; trace said "ok" (2026-11-05)
- **Runs:** 438fc54c-0221-4a70-934f-d4452bbd3d70, 13082e4d-4ee4-46c3-97c1-56c73b6ea343, 77c9aaac-1446-4583-a62d-a1e1131ad718
- **Symptom:** all three briefs said "macro snapshot returned no data"; all checks still passed.
- **Trace:** every `mcp get_macro_snapshot` event had status=ok. Reading its stored output showed `{}`.
  Calling `datasources.macro.get_macro_snapshot()` directly also returned `{}`, so the bug was in
  the data code, not MCP transport.
- **Cause:** editing the CPI block dropped `snapshot[sid] = entry`, so the loop stored nothing.
  An empty dict isn't an exception, so nothing flagged it.
- **Fix:** restored the function; the MCP server now returns an error instead of an empty snapshot;
  the tracer treats empty results as errors.
- **Lesson:** "no exception" isn't "success". Validate outputs at the boundary.

## 6. Memory recall missed saved preferences (2026-11-05)
- **Runs:** 13082e4d-... (Priya), 77c9aaac-... (Dan)
- **Symptom:** briefs said no saved preferences were found; Dan's income focus and Priya's
  index-fund preference were never mentioned. The "recalled memory" check passed anyway.
- **Trace:** the memory event input was "risk limits preferences goals interests"; its output was
  `"memories": []`.
- **Cause:** keyword search covered content + tags only. The word "preference" existed only as
  the memory's kind.
- **Fix:** search also matches the memory kind; the smoke check now requires recall to return
  at least one memory, not just to be called.