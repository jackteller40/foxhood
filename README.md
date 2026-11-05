# Investment Research Agent

A personal investment research assistant for a school project. It gathers market, news and macro
data and writes personalized research based on each user's interests, watchlist and portfolio:
a daily pre-market brief, a post-close recap, and a chat for specific questions.

Built with **LangGraph**, **Claude Haiku** (Anthropic API), an **MCP** server for macro data,
and a **Streamlit** front end. Market data is real (free sources); users and portfolios are fake demo data.

> Research only. Not financial advice. The app never places trades.

## Features
- **Daily briefs**: the pre-market brief or post-close recap is generated automatically when the app opens (chosen by the NYSE calendar, including holidays and half days), then cached for the day.
- **Chat**: ask about your portfolio, a stock, or the market.
- **Backdated portfolio**: enter shares *or* a dollar amount plus a purchase date; the app looks up the actual price paid, handles stock splits, and compares you to SPY on both price return and total return (with dividends).
- **Approvals**: the agent must ask before changing your watchlist, holdings or saved memories.
- **Traces**: every agent run is recorded and viewable in the app and in LangSmith.

## Requirements coverage
| Requirement | Implementation |
|---|---|
| LLM-driven agent loop | `agent/graph.py`: hand-built LangGraph `StateGraph`; the LLM chooses each tool call and when to stop |
| Tool calling | `agent/tools.py`, `agent/write_tools.py`: 12 local tools, plus 3 MCP tools |
| Subagent | `agent/subagents/news_analyst.py`: separately prompted news analyst with its own tools and loop; returns validated structured output |
| Skill | `skills/*/SKILL.md`: three documented procedures loaded on demand via `load_skill` (`agent/skills.py`) |
| MCP integration | `mcp_servers/macro_server.py`: FastMCP server (FRED data) with 3 tools and 2 resources, connected through `langchain-mcp-adapters` |
| Persistent memory / retrieval | `storage/db.py`: memories table with `recall_memory` / `remember`; chat history persisted by LangGraph's SQLite checkpointer |
| Permissions | `config/permissions.yaml` + `agent/permissions.py`: allow / ask / deny, enforced before any tool runs; approvals via LangGraph `interrupt()`. See `docs/permissions.md` |
| Agent tracing | `agent/tracing.py`: linked local trace events (run → LLM / tool / MCP / skill / memory / permission → subagent) plus LangSmith. Failures investigated in `docs/failure_log.md` |
| Simple interface | Streamlit app (`app.py`, `pages/`) with a Trace page |

## Architecture
```
Streamlit UI (brief · portfolio · profile · ask · trace)
        │
Main agent (LangGraph: agent → permission gate → [approval] → tools → agent ...)
   ├── local tools ── portfolio math, yfinance prices, SQLite (users, holdings, memories)
   ├── MCP client ─── macro-data MCP server ── FRED
   ├── load_skill ─── skills/*/SKILL.md
   └── news analyst subagent ── Finnhub news + price performance
        │
Tracing: local trace_events table + LangSmith (same run ids)
```

## Setup
Requires Python 3.11+.

```bash
git clone <your-repo-url>
cd investment-research-agent
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then fill in your keys
```

API keys in `.env` (all have free tiers except Anthropic, which is pay-as-you-go):
| Key | Get it at |
|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com |
| `FRED_API_KEY` | fred.stlouisfed.org (free account → API keys) |
| `FINNHUB_API_KEY` | finnhub.io |
| `LANGSMITH_API_KEY` | smith.langchain.com (optional, for hosted traces) |

Create the demo users (three fake profiles: aggressive tech, balanced ETF, income focused):
```bash
python -m storage.seed_demo --reset
```

## Run
```bash
python -m streamlit run app.py
```
Use `python -m streamlit` (not bare `streamlit`) so the app runs in the project's virtual environment.

## Tests
Run from the repo root with the venv active:
| Command | Checks |
|---|---|
| `python -m tests.smoke_data` | yfinance, FRED and Finnhub connections, caching |
| `python -m tests.smoke_portfolio` | Backdating, splits, P&L, SPY benchmark |
| `python -m tests.smoke_storage` | Database, demo users, memory search, traces (**resets `app.db`**) |
| `python -m tests.smoke_mcp` | MCP server tools and resources |
| `python -m tests.smoke_agent` | Main agent tool selection and tracing |
| `python -m tests.smoke_briefs` | Skills, news subagent, briefs (pre-market or close depending on time) |
| `python -m tests.smoke_permissions` | Policy rules + approve / reject / deny scenarios |

## Project structure
```
app.py                  Home: daily brief
pages/                  Portfolio, Profile, Ask (chat), Trace
ui/common.py            Shared UI: user picker, trace viewer
agent/                  Graph, runner, tools, prompts, skills, permissions, tracing, briefs
agent/subagents/        News analyst subagent
mcp_servers/            Macro-data MCP server
skills/                 SKILL.md procedures
datasources/            yfinance, FRED, Finnhub clients + disk cache
portfolio/              Backdating, splits, returns, benchmark
storage/                SQLite schema, queries, demo seed data
core/                   Config, market clock, async helper
config/permissions.yaml Permission policy
docs/                   Permission policy notes, failure log
tests/                  Smoke tests
```

## Limitations
- yfinance is an unofficial Yahoo client: fine for a proof of concept, not for production or redistribution.
- Finnhub's free tier covers North American company news only.
- Free data sources mean some calls are slow on first use; results are cached on disk (`.cache/`).
- Traces appear in the app after a run finishes, not live.