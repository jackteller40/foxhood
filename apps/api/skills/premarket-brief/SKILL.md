---
name: premarket-brief
description: Write the user's pre-market brief for the current trading day - recent news on holdings and watchlist, today's scheduled economic catalysts, active risk-rule breaches, and what to watch.
---

# Pre-market brief

Use before or during the trading day, when the user asks for their morning or pre-market brief.

## Gather (call independent tools in parallel)
1. `recall_memory` with words like "risk limits preferences goals interests".
2. `get_positions` for weights and the latest moves.
3. `get_watchlist_snapshot`.
4. `get_upcoming_releases` with days=2.
5. ONE `delegate_news_analysis` call with the 3-5 largest holdings plus up to 2 watchlist names,
   focus "recent news that could move the stock today".
6. `get_macro_snapshot`.

## Timing
Check the current time in your instructions. Before 9:30 am ET, day-change numbers in tool results
reflect the previous session, so label them "yesterday". After 9:30 am ET the market is open: say so
and label moves "so far today".

## Write (markdown, 250-350 words, these sections in order)
### Today at a glance
Two sentences: the setup for today and the one thing that matters most for this user.
### Today's catalysts
Economic releases today or tomorrow with times when known (FOMC decisions are 2:00 pm ET).
### News on your holdings
Company-specific items only (relevance 1-3). If there's none, say so in one line.
### Watchlist
Only names with real news or a move above 2%.
### Risk reminders
Saved rules that are currently breached, with numbers.

## Rules
- Every number must come from a tool result in this run.
- No buy/sell instructions. End with "Not financial advice."