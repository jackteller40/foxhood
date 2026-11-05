---
name: post-close-recap
description: Write the user's end-of-day recap after the US market close - today's portfolio and watchlist moves, why they moved, risk-rule checks, macro context, and what to watch next session.
---

# Post-close recap

Use after the market closes, when the user asks for their daily recap or how today went.

## Gather (call independent tools in parallel)
1. `recall_memory` with words like "risk limits preferences goals". Saved rules shape everything below.
2. `get_portfolio_summary` and `get_positions`.
3. `get_watchlist_snapshot`.
4. Pick the 2-4 biggest movers by absolute day move across holdings and watchlist (always include
   anything that moved more than 3%). Send them in ONE `delegate_news_analysis` call with
   focus "explain today's price move".
5. `get_macro_snapshot`, and `get_upcoming_releases` with days=3 for upcoming catalysts.

## Write (markdown, 300-400 words, these sections in order)
### Today in one line
Portfolio day change ($ and %) vs SPY's day change. Say plainly whether the user beat or lagged the market.
### What moved and why
Biggest movers with their day %. Use the news analyst's findings. If relevance is 0 or
explains_price_move is false, write "no company-specific news" instead of guessing.
### Watchlist
1-2 lines on notable moves only. Skip the section if nothing moved more than 2%.
### Risk check
Apply the user's saved rules (e.g. position limits) and say whether any are breached, with numbers.
Note sector concentration if one sector is above 50%.
### Macro
2-3 numbers that matter for THIS portfolio (rates for growth- or bond-heavy books, credit spreads
for income books), each with its 1-month change.
### Next session
Scheduled releases in the next trading day or two, and what they could mean for these holdings.

## Rules
- Every number must come from a tool result in this run.
- For income-focused users, report total return alongside price return.
- No buy/sell instructions; frame as things to consider. End with "Not financial advice."