"""Run from the repo root: python -m tests.smoke_date"""
from __future__ import annotations

import time
import traceback
from datetime import date, timedelta

from core.config import settings
from datasources import macro, market, news

results: list[tuple[str, str]] = []


def check(name, fn):
    print(f"\n=== { name} ===")
    try:
        fn()
        results.append((name, "PASS"))
    except Exception:
        traceback.print_exc()
        results.append((name, "FAIL"))
        
def config_check():
    missing = settings.missing_keys()
    print("Model:", settings.claude_model)
    print("Missing keys:", missing or "none")
    if missing:
        raise RuntimeError(f"Missing keys in .env: {missing}")

def price_history():
    df = market.get_price_history("AAPL", start=date.today() - timedelta(days=10))
    print(df[["Close", "Adj Close", "Volume"]].tail())
    assert not df.empty

def splits():
    s = market.get_splits("NVDA")
    print(s.tail(3))
    assert (s.index >= "2024-06-01").any(), "expected NVDA's June 2024 10-for-1 split"

def split_adjusted_closes():
    # NVDA traded ~$1,200 before the June 10, 2024 split and ~$120 after.
    # If both sides show ~$120 here, yfinance's Close is split-adjusted (expected) -> step 3 handles it.
    df = market.get_price_history("NVDA", start="2024-06-03", end="2024-06-13")
    print(df[["Close", "Stock Splits"]])

def quote():
    q = market.get_quote("SPY")
    print(q)
    assert q["price"] > 0

def company_info():
    for t in ("MSFT", "SPY"):
        print(market.get_company_info(t))

def fred_series():
    s = macro.get_series("DGS10")
    print(s.tail())
    assert not s.empty

def macro_snapshot():
    for sid, v in macro.get_macro_snapshot().items():
        print(f"{sid:14} {v}")

def company_news():
    items = news.get_company_news("AAPL", days=3, limit=3)
    for it in items:
        print(it["published"][:16], it["source"], "|", it["headline"])
    assert items, "no AAPL news in the last 3 days"

def market_news():
    for it in news.get_market_news(limit=3):
        print(it["published"][:16], it["source"], "|", it["headline"])

if __name__ == "__main__":
    t0 = time.time()
    for name, fn in [
        ("config", config_check),
        ("price history", price_history),
        ("splits", splits),
        ("split-adjusted closes", split_adjusted_closes),
        ("quote", quote),
        ("company info", company_info),
        ("FRED series", fred_series),
        ("macro snapshot", macro_snapshot),
        ("company news", company_news),
        ("market news", market_news),
    ]:
        check(name, fn)

    print("\n=== SUMMARY ===")
    for name, status in results:
        print(f"{status:5} {name}")
    print(f"Finished in {time.time() - t0:.1f}s")