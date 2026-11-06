"""Run from the repo root:  python -m tests.smoke_portfolio"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from portfolio import metrics
from portfolio.positions import Lot, resolve_lot

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 20)
pd.options.display.float_format = "{:,.2f}".format

DEMO_LOTS = [
    Lot("NVDA", date(2024, 6, 3), shares=10),     # pre-split: expect ~$1,150 paid, x10, 100 shares now
    Lot("AAPL", date(2025, 1, 4), amount=5000),   # Saturday: expect shift to Mon 2025-01-06
    Lot("MSFT", date(2023, 3, 15), shares=5),
    Lot("QQQ", date(2022, 10, 12), amount=3000),  # ETF
    Lot("AAPL", date(2023, 8, 1), shares=8),      # second AAPL lot: tests aggregation
]

BAD_LOTS = [
    ("future date", Lot("AAPL", date.today() + timedelta(days=5), shares=1)),
    ("bad ticker", Lot("ZZZZZZQ", date(2024, 1, 3), shares=1)),
    ("both shares and amount", Lot("AAPL", date(2024, 1, 3), shares=1, amount=100)),
    ("neither", Lot("AAPL", date(2024, 1, 3))),
]

print("=== resolved lots ===")
resolved = []
for lot in DEMO_LOTS:
    r = resolve_lot(lot)
    resolved.append(r)
    print(
        f"{r.ticker:5} req {r.requested_date} -> traded {r.trade_date} | paid ${r.price_paid:,.2f} "
        f"| split x{r.split_factor:g} | bought {r.shares_bought:,.4f} -> now {r.shares_now:,.4f} "
        f"| cost ${r.cost_basis:,.2f}" + (f"\n      NOTE: {r.note}" if r.note else "")
    )

print("\n=== error handling (each should print a clear message) ===")
for label, lot in BAD_LOTS:
    try:
        resolve_lot(lot)
        print(f"{label}: NO ERROR RAISED (bug)")
    except Exception as e:
        print(f"{label}: [{type(e).__name__}] {e}")

positions = metrics.positions_table(resolved)
print("\n=== positions ===")
print(positions.drop(columns=["name"]).to_string(index=False))

print("\n=== sector exposure (%) ===")
print(metrics.sector_exposure(positions).to_string())

print("\n=== summary ===")
for k, v in metrics.portfolio_summary(resolved, positions).items():
    print(f"{k:22} {v:,.2f}" if isinstance(v, float) else f"{k:22} {v}")

print("\n=== value history (last 5 days) ===")
print(metrics.value_history(resolved).tail())