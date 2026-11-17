"""Live check of the market-data layer against the real Tiingo and Finnhub APIs (about 10 calls).

    uv run python -m tests.smoke_market

Clears the shared market cache first so every number comes fresh from the providers."""
from __future__ import annotations

import sys
import traceback
from datetime import date

from core.config import settings
from datasources import cache, market
from portfolio.positions import Lot, resolve_lot

results: list[tuple[str, bool]] = []


def check(name: str, fn) -> None:
    print(f"\n=== {name} ===")
    try:
        fn()
        results.append((name, True))
    except Exception:
        traceback.print_exc()
        results.append((name, False))


def nvda_split() -> None:
    # 10 NVDA shares bought 2024-06-03 cost ~$1,150 each; the 10-for-1 split on 2024-06-10 makes them 100.
    r = resolve_lot(Lot("NVDA", date(2024, 6, 3), shares=10))
    print(f"price paid ${r.price_paid:,.2f}, split factor {r.split_factor}, shares now {r.shares_now}")
    assert 1000 < r.price_paid < 1300 and r.split_factor == 10.0 and r.shares_now == 100.0


def quotes() -> None:
    for t in ("SPY", "AAPL"):
        q = market.get_quote(t)
        print(f"{t}: ${q['price']:,.2f} ({q['change_pct']:+.2f}% vs previous close ${q['previous_close']:,.2f})")
        assert q["price"] > 0


def profiles() -> None:
    for t in ("AAPL", "SPY"):
        info = market.get_company_info(t)
        print({k: info[k] for k in ("name", "quote_type", "sector", "trailing_pe", "dividend_yield")})
    assert market.get_company_info("SPY")["quote_type"] == "ETF"
    assert market.get_company_info("AAPL")["quote_type"] == "EQUITY"


def total_return() -> None:
    hist = market.get_price_history("SCHD", "2024-01-02")
    growth_price = hist["Close"].iloc[-1] / hist["Close"].iloc[0]
    growth_total = hist["Adj Close"].iloc[-1] / hist["Adj Close"].iloc[0]
    print(f"SCHD since 2024-01-02: price x{growth_price:.3f}, with dividends x{growth_total:.3f}")
    assert growth_total > growth_price   # a dividend fund must do better with dividends reinvested


def earnings() -> None:
    rows = market.get_earnings_calendar(["AAPL", "MSFT", "NVDA", "WMT", "JPM", "HD", "COST", "TGT"], days_ahead=30)
    for r in rows:
        print(f"{r['date']}  {r['ticker']:5} {r['timing']:22} est EPS {r['eps_estimate']}  ({r['status']})")
    print("(none of these report in the next 30 days)" if not rows else "")


if __name__ == "__main__":
    missing = settings.missing_keys()
    if missing:
        sys.exit(f"Missing in apps/api/.env: {', '.join(missing)}")
    cache.clear_cache()
    for name, fn in [("NVDA backdated purchase across the 2024 split", nvda_split), ("Live quotes", quotes),
                     ("Company profiles (stock and ETF)", profiles), ("Total return includes dividends", total_return),
                     ("Earnings calendar", earnings)]:
        check(name, fn)
    print("\n" + "\n".join(f"{'PASS' if ok else 'FAIL'}  {name}" for name, ok in results))
    sys.exit(0 if all(ok for _, ok in results) else 1)