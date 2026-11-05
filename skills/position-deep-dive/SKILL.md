---
name: position-deep-dive
description: Analyze one stock or fund in depth when the user asks about a specific ticker - performance, valuation, recent news, and how it fits their portfolio, risk tolerance and saved preferences.
---

# Position deep dive

Use when the user asks about one specific ticker ("what do you think of AMD?", "should I worry about NVDA?").

## Gather (call independent tools in parallel)
1. `recall_memory` with the ticker and its sector or theme (e.g. "AMD semiconductors").
2. `get_company_profile` and `get_price_performance` for the ticker.
3. `get_positions` to see whether the user holds it, and at what weight.
4. `delegate_news_analysis` with just this ticker, focus "recent developments and sentiment".
5. Only if the business is rate-sensitive (banks, REITs, utilities, long-duration growth):
   `get_macro_snapshot` and use 1-2 numbers.

## Write (markdown, 250-350 words, these sections in order)
### Snapshot
What it is, price, 1-month / YTD / 1-year returns, distance from the 52-week high.
### Valuation
Trailing and forward P/E, dividend yield, beta. For ETFs, skip P/E.
### In your portfolio
If held: weight, total return, and fit with the user's risk tolerance and saved rules.
If not held: how it would fit, and flag any saved exclusion it conflicts with.
### Recent news
The news analyst's summary and sentiment, with up to 2 headlines and their sources.
### Things to consider
2-3 balanced points. No price targets.

## Rules
- Every number must come from a tool result in this run.
- No buy/sell instructions. End with "Not financial advice."