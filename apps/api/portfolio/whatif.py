"""What-if: how the portfolio would look after hypothetical buys and sells. Read-only; nothing is saved.

Conventions (stated in the tool output so the agent can explain them):
- A sale's proceeds are held as cash (earning nothing). A buy is paid from that cash first, then new money.
- The past-year comparison is buy-and-hold on share counts, from daily closes (dividends not included),
  for today's holdings vs the changed holdings vs the same total dollars in SPY.
- Realized gain on a sale uses average cost (an estimate, not tax advice)."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from datasources import market
from portfolio.metrics import BENCHMARK

TRADING_DAYS = 252
MIN_HISTORY_DAYS = 20


@dataclass(frozen=True)
class Change:
    ticker: str
    action: str                      # "buy" | "sell"
    shares: float | None = None
    amount_usd: float | None = None
    fraction: float | None = None    # sells only: 0.5 = half the position


@dataclass
class _Holding:
    ticker: str
    sector: str
    shares: float
    price: float
    cost_basis: float

    @property
    def value(self) -> float:
        return self.shares * self.price


def _sector_of(ticker: str) -> str:
    info = market.get_company_info(ticker)
    if info.get("sector"):
        return info["sector"]
    return "ETF" if (info.get("quote_type") or "").upper() == "ETF" else "Other"


def _snapshot(holdings: dict[str, _Holding], cash: float) -> dict:
    total = sum(h.value for h in holdings.values()) + cash
    rows = sorted(({"ticker": h.ticker, "shares": h.shares, "value": h.value,
                    "weight_pct": h.value / total * 100 if total else 0.0}
                   for h in holdings.values() if h.shares > 1e-9), key=lambda r: -r["value"])
    sectors: dict[str, float] = {}
    for h in holdings.values():
        if h.shares > 1e-9:
            sectors[h.sector] = sectors.get(h.sector, 0.0) + h.value
    if cash > 0.005:
        sectors["Cash"] = cash
    return {
        "total_value": total,
        "cash": cash,
        "positions": rows,
        "largest_position": rows[0]["ticker"] if rows else None,
        "largest_weight_pct": rows[0]["weight_pct"] if rows else 0.0,
        "sector_mix_pct": {k: v / total * 100 for k, v in sorted(sectors.items(), key=lambda kv: -kv[1])} if total else {},
    }


def _stats(values: pd.Series) -> dict | None:
    values = values.dropna()
    if len(values) < MIN_HISTORY_DAYS or values.iloc[0] <= 0:
        return None
    daily = values.pct_change().dropna()
    peak = values.cummax()
    return {
        "return_pct": (values.iloc[-1] / values.iloc[0] - 1) * 100,
        "volatility_pct": float(daily.std() * math.sqrt(TRADING_DAYS) * 100),
        "max_drawdown_pct": float(((values / peak) - 1).min() * 100),
    }


def _past_year(before: dict[str, float], after: dict[str, float], cash_before: float, cash_after: float,
               today: date) -> dict:
    """Buy-and-hold over the past year for two sets of share counts, plus SPY with the 'after' dollars."""
    start = today - timedelta(days=366)
    tickers = sorted(set(before) | set(after) | {BENCHMARK})
    closes = {t: market.get_price_history(t, start=start)["Close"] for t in tickers}
    spy = closes[BENCHMARK]
    if len(spy) < MIN_HISTORY_DAYS:
        return {"note": "Not enough price history for a past-year comparison."}
    idx = spy.index
    aligned = {t: s.reindex(idx).ffill() for t, s in closes.items()}

    def series(shares: dict[str, float], cash: float) -> pd.Series:
        out = pd.Series(cash, index=idx, dtype=float)
        for t, n in shares.items():
            out = out + aligned[t] * n
        return out

    after_series = series(after, cash_after)
    spy_series = spy / spy.iloc[0] * after_series.iloc[0]
    missing = [t for t in tickers if aligned[t].isna().iloc[0]]
    return {
        "period": f"{idx[0].date()} to {idx[-1].date()}",
        "current_holdings": _stats(series(before, cash_before)),
        "after_change": _stats(after_series),
        "spy": _stats(spy_series),
        "note": (f"{', '.join(missing)} didn't trade for the whole year, so the comparison starts later for them."
                 if missing else None),
    }


def simulate(current: pd.DataFrame, changes: list[Change], today: date) -> dict:
    """`current` is the positions table (metrics.positions_table). Raises ValueError for impossible changes."""
    if not changes:
        raise ValueError("Give at least one change, e.g. sell half of NVDA or buy $5,000 of VOO.")
    holdings = {r["ticker"]: _Holding(r["ticker"], r["sector"], float(r["shares"]), float(r["price"]),
                                      float(r["cost_basis"])) for _, r in current.iterrows()}
    before_shares = {t: h.shares for t, h in holdings.items()}
    before = _snapshot(holdings, 0.0)
    cash, new_money, realized, applied = 0.0, 0.0, 0.0, []

    for c in changes:
        t = c.ticker.strip().upper()
        if c.action not in ("buy", "sell"):
            raise ValueError(f"Action must be buy or sell, not {c.action!r}.")
        given = [v for v in (c.shares, c.amount_usd, c.fraction) if v is not None]
        if len(given) != 1:
            raise ValueError(f"For {t}, give exactly one of shares, amount_usd or fraction.")
        if c.action == "sell":
            h = holdings.get(t)
            if h is None or h.shares <= 1e-9:
                raise ValueError(f"You don't hold {t}, so there's nothing to sell.")
            if c.fraction is not None and not 0 < c.fraction <= 1:
                raise ValueError("fraction must be between 0 and 1 (0.5 = half).")
            n = h.shares * c.fraction if c.fraction is not None else (
                c.shares if c.shares is not None else c.amount_usd / h.price)
            if n <= 0 or n > h.shares * 1.000001:
                raise ValueError(f"You hold {h.shares:g} shares of {t}; can't sell {n:g}.")
            n = min(n, h.shares)
            cost_sold = h.cost_basis * n / h.shares
            proceeds = n * h.price
            realized += proceeds - cost_sold
            h.cost_basis -= cost_sold
            h.shares -= n
            cash += proceeds
            applied.append({"action": "sell", "ticker": t, "shares": n, "proceeds": proceeds,
                            "realized_gain_estimate": proceeds - cost_sold})
        else:
            if c.fraction is not None:
                raise ValueError("fraction only applies to sells; use shares or amount_usd to buy.")
            price = market.get_quote(t)["price"]
            if not price or price <= 0:
                raise ValueError(f"No current price for {t}.")
            n = c.shares if c.shares is not None else c.amount_usd / price
            if n <= 0:
                raise ValueError("Buy amounts must be above zero.")
            cost = n * price
            from_cash = min(cash, cost)
            cash -= from_cash
            new_money += cost - from_cash
            h = holdings.get(t) or _Holding(t, _sector_of(t), 0.0, price, 0.0)
            h.shares += n
            h.cost_basis += cost
            holdings[t] = h
            applied.append({"action": "buy", "ticker": t, "shares": n, "cost": cost, "paid_from_cash": from_cash})

    after = _snapshot(holdings, cash)
    return {
        "changes": applied,
        "before": before,
        "after": after,
        "new_money_added": new_money,
        "realized_gain_estimate": realized,
        "past_year": _past_year(before_shares, {t: h.shares for t, h in holdings.items() if h.shares > 1e-9},
                                0.0, cash, today),
        "assumptions": ("Hypothetical only; nothing was changed. Sale proceeds are held as cash; buys use that cash "
                        "first, then new money. Past-year figures hold today's share counts for the whole year, "
                        "price only (no dividends). Realized gain uses average cost and is an estimate, not tax advice."),
    }
