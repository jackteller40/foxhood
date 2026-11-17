# Market data sources

| Data | Provider | Plan | Limits we design around |
|---|---|---|---|
| Daily price history (split + dividend adjusted) | Tiingo | Free | 50 requests/hour, 1,000/day, 500 unique symbols/month |
| Live quotes, company profiles and metrics, earnings calendar, news | Finnhub | Free | 60 requests/minute |
| Economic data (rates, CPI, unemployment) | FRED (via our MCP server) | Free | Generous |

Every call goes through the shared Postgres cache (`datasources/cache.py`), so each ticker's history is
downloaded about once every few hours for all users together, not once per user.

## Licensing
Both free plans are licensed for personal use. Foxhood is a small, invite-only app for a handful of
friends with no ads or payments. Before inviting anyone, email the providers (Tiingo: sales@tiingo.com)
describing exactly that, and keep their reply here. If either says the use needs a commercial plan,
either upgrade or limit Foxhood to personal use.

Answers name their sources ("Prices: Tiingo · Quotes & earnings: Finnhub").