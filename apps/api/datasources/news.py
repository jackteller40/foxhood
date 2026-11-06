"""Company and market news from Finnhub(free tier: ~60 calls/min, North American companies)"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import finnhub

from core.config import settings
from datasources.cache import cached

_client: finnhub.Client | None = None

def _get_client() -> finnhub.Client:
    global _client
    if not settings.finnhub_api_key:
        raise RuntimeError("FINNHUB_API_KEY missing from .env")
    if _client is None:
        _client = finnhub.Client(api_key=settings.finnhub_api_key)
    return _client

def _normalize(items: list[dict], ticker: str | None, limit: int) -> list[dict]:
    """Newest first, dedupe repeated wire headlines, keep only the fields the agent needs"""
    seen: set[str] = set()
    out: list[dict] = []
    for it in sorted(items, key=lambda x: x.get("datetime", 0), reverse=True):
        headline = (it.get("headline") or "").strip()
        key = headline.lower()
        if not headline or key in seen:
            continue
        seen.add(key)
        out.append({
            "ticker": ticker,
            "headline": headline,
            "summary": (it.get("summary") or "")[:500],
            "source": it.get("source"),
            "url": it.get("url"),
            "published": datetime.fromtimestamp(it.get("datetime", 0), tz=UTC).isoformat(),
        })
        if len(out) >= limit:
            break
    return out

@cached(ttl_seconds=30 * 60)
def get_company_news(ticker: str, days: int = 3, limit: int = 10) -> list[dict]:
    to_date = date.today()
    from_date = to_date - timedelta(days=days)
    raw = _get_client().company_news(ticker.upper(), _from=from_date.isoformat(), to=to_date.isoformat())
    return _normalize(raw, ticker.upper(), limit)

@cached(ttl_seconds=30 * 60)
def get_market_news(limit: int = 15) -> list[dict]:
    raw = _get_client().general_news("general", min_id=0)
    return _normalize(raw, None, limit)