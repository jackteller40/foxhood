"""API clients for the two market-data providers (both on free tiers):
- Tiingo:  end-of-day price history with split and dividend data
- Finnhub: live quotes, company profiles and metrics, earnings calendar, news
Keys come from apps/api/.env. Free plans are licensed for personal use; see docs/data-sources.md."""
from __future__ import annotations

import finnhub
import requests

from core.config import settings

TIINGO_URL = "https://api.tiingo.com"
TIMEOUT_SECONDS = 15

_finnhub: finnhub.Client | None = None
_session = requests.Session()


class DataProviderError(RuntimeError):
    """A provider refused or failed a request (rate limit, bad key, outage). Message is user-safe."""


def finnhub_client() -> finnhub.Client:
    global _finnhub
    if not settings.finnhub_api_key:
        raise DataProviderError("FINNHUB_API_KEY is missing from apps/api/.env")
    if _finnhub is None:
        _finnhub = finnhub.Client(api_key=settings.finnhub_api_key)
    return _finnhub


def tiingo_get(path: str, params: dict | None = None) -> list | dict | None:
    """GET a Tiingo endpoint. Returns None for an unknown ticker (404) instead of raising."""
    if not settings.tiingo_api_key:
        raise DataProviderError("TIINGO_API_KEY is missing from apps/api/.env")
    resp = _session.get(f"{TIINGO_URL}{path}", params=params, timeout=TIMEOUT_SECONDS,
                        headers={"Authorization": f"Token {settings.tiingo_api_key}",
                                 "Content-Type": "application/json"})
    if resp.status_code == 404:
        return None
    if resp.status_code == 429:
        raise DataProviderError("Price data is temporarily rate-limited (Tiingo free tier). Try again shortly.")
    if resp.status_code in (401, 403):
        raise DataProviderError("Tiingo rejected the API key. Check TIINGO_API_KEY.")
    resp.raise_for_status()
    return resp.json()