"""News analyst subagent: a separately instructed agent the main agent delegates news work to.

It has its own system prompt and only two tools (news + price performance), runs its own
LangGraph loop, then its findings are converted to a validated Pydantic schema and returned
to the main agent as JSON."""
from __future__ import annotations

import json
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from agent.graph import build_graph, final_text
from agent.models import make_model
from agent.tools import _dump, _performance
from agent.tracing import content_to_text
from datasources import news

MAX_TICKERS = 8
SUBAGENT_TOOL_ROUNDS = 4


# ---------- output schema ----------
class TickerNews(BaseModel):
    ticker: str
    summary: str = Field(description="2-3 sentences on what actually happened at this company, or that nothing company-specific did")
    sentiment: Literal["positive", "negative", "mixed", "neutral"]
    relevance: int = Field(ge=0, le=3, description="0 = no company-specific news, 3 = major company event")
    explains_price_move: bool = Field(description="True only if the news plausibly explains the recent price move")
    key_headlines: list[Headline] = Field(default_factory=list, description="Up to 2, copied exactly from the evidence")


class Headline(BaseModel):
    headline: str
    source: str | None = None
    url: str | None = None


class NewsReport(BaseModel):
    tickers: list[TickerNews]
    notes: str | None = None
    structured: bool = True  # False = structuring failed; findings are in `notes` as plain text


# ---------- prompts ----------

NEWS_ANALYST_PROMPT = """You are a financial news analyst working for a portfolio research assistant.
You receive a list of tickers and a focus. For EACH ticker:
1. Call get_company_news (days=3, or days=7 if nothing recent). If the focus is about a price move,
   also call get_price_performance. Call tools for different tickers in parallel.
2. Separate company-specific news from market roundups, listicles, and articles that only mention the
   ticker in passing. Ignore the latter completely.
3. Decide what actually happened, the sentiment, relevance (0-3), and whether the news plausibly
   explains the recent price move.

Rules:
- Use only facts in tool results. Never invent headlines, numbers, or URLs.
- If there is no company-specific news, say so: relevance 0, sentiment neutral.
- ETFs and funds rarely have company news; that's expected.
When you are done researching, reply with a short plain-text finding for each ticker.
- Forecasts, market-implied odds, and analyst targets are claims, not facts: attribute them to the
  article's source (e.g. "per Reuters, markets price ~80% odds of..."), never state them as established."""

STRUCTURE_PROMPT ="""Convert the news analyst's findings into the required schema.
One entry per requested ticker, in the order given. Be brief: summaries at most 2 sentences,
at most 2 key headlines per ticker, copied verbatim (headline, source, url) from the EVIDENCE section."""


# ---------- the subagent's own tools ----------

@tool
def get_company_news(ticker: str, days: int = 3) -> str:
    """Recent news for one ticker from the last `days` days (1-14), newest first, with source,
    URL, publish time, and a short summary."""
    items = news.get_company_news(ticker.strip().upper(), days=max(1, min(int(days), 14)), limit=8)
    for it in items:
        it["summary"] = (it.get("summary") or "")[:300]
    return _dump({"ticker": ticker.upper(), "articles": items})


@tool
def get_price_performance(ticker: str) -> str:
    """Price, 1-day change, 1-week/1-month/YTD/1-year returns, and distance from the 52-week high."""
    return _dump(_performance(ticker))


SUBAGENT_TOOLS = [get_company_news, get_price_performance]


# ---------- running it ----------

async def run_news_analyst(tickers: list[str], focus: str, config: RunnableConfig | None = None) -> NewsReport:
    base = {k: v for k, v in (config or {}).items() if k not in ("run_id", "configurable")}

    graph = build_graph(make_model(), SUBAGENT_TOOLS, NEWS_ANALYST_PROMPT,
                        max_tool_rounds=SUBAGENT_TOOL_ROUNDS, checkpointer=False)
    result = await graph.ainvoke(
        {"messages": [HumanMessage(f"Tickers: {', '.join(tickers)}\nFocus: {focus}")], "tool_rounds": 0},
        {**base, "run_name": "subagent:news_analyst", "recursion_limit": 2 * SUBAGENT_TOOL_ROUNDS + 5},
    )
    msgs = result["messages"]

    evidence = "\n\n".join(
        f"[{m.name}] {content_to_text(m.content)[:3000]}" for m in msgs if isinstance(m, ToolMessage)
    )
    findings = final_text(msgs)
    structurer = make_model().with_structured_output(NewsReport, include_raw=True)
    out = await structurer.ainvoke(
        [SystemMessage(STRUCTURE_PROMPT),
         HumanMessage(f"Requested tickers: {tickers}\n\nANALYST FINDINGS:\n{findings}"
                      f"\n\nEVIDENCE (tool results):\n{evidence}")],
        {**base, "run_name": "subagent:news_analyst:structure"},
    )
    report = out.get("parsed")
    if report is None:
        # Don't hand the main agent an error it will retry: the research succeeded, so return it as text.
        return NewsReport(tickers=[], structured=False,
                          notes=f"Structured output failed ({out.get('parsing_error')}). "
                                f"Analyst findings: {findings}")
    for t in report.tickers:
        t.key_headlines = t.key_headlines[:2]
    return report


def make_news_subagent_tool():
    @tool
    async def delegate_news_analysis(tickers: list[str], focus: str, config: RunnableConfig) -> str:
        """Delegate news research to the news analyst subagent. It reads recent news for each
        ticker, filters out market roundups and passing mentions, and returns per ticker: summary,
        sentiment, relevance (0-3), whether the news explains the price move, and up to 3 key
        headlines with URLs. Send ALL tickers in ONE call (max 8). `focus` says what to look for,
        e.g. "explain today's price move"."""
        clean = list(dict.fromkeys(t.strip().upper() for t in tickers if t and t.strip()))[:MAX_TICKERS]
        if not clean:
            return json.dumps({"error": "No tickers given."})
        report = await run_news_analyst(clean, focus, config)
        return report.model_dump_json()

    return delegate_news_analysis