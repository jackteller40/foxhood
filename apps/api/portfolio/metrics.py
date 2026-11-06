"""Portfolio math: positions, P&L, weights, sector mix, value history, SPY benchmark.

Two return measures, both computed for the portfolio AND the benchmark:
- price return  (pnl, pnl_pct, total_pnl_pct): price change only
- total return  (total_return_*): dividends reinvested, from yfinance 'Adj Close'
Income-heavy portfolios look much worse on price return alone, so the agent reports both.
value_history() is price-based (it's for the chart)."""
from __future__ import annotations

from datetime import date

import pandas as pd

from datasources import market
from portfolio.positions import Lot, ResolvedLot, resolve_lot

BENCHMARK = "SPY"


def benchmark_lot(r: ResolvedLot) -> ResolvedLot:
    """Same dollars, same day, into the benchmark."""
    return resolve_lot(Lot(BENCHMARK, r.trade_date, amount=r.cost_basis))


def total_return_factor(ticker: str, trade_date: date) -> float:
    """Growth of $1 from the trade-date close to now, dividends reinvested.
    The Adj Close ratio covers dividends + splits up to the last completed bar;
    then scale by today's move (live price vs. last completed close)."""
    bars = market.get_price_history(ticker, start=trade_date)
    if bars.empty:
        raise ValueError(f"No history for {ticker} since {trade_date}")
    first, last = bars.iloc[0], bars.iloc[-1]
    live = market.get_quote(ticker)["price"]
    return float(last["Adj Close"] / first["Adj Close"] * live / last["Close"])


def _sector(info: dict) -> str:
    if info.get("sector"):
        return info["sector"]
    return "ETF" if (info.get("quote_type") or "").upper() == "ETF" else "Other"


def positions_table(resolved: list[ResolvedLot]) -> pd.DataFrame:
    """One row per ticker (lots aggregated)."""
    rows = []
    for t in sorted({r.ticker for r in resolved}):
        lots = [r for r in resolved if r.ticker == t]
        q = market.get_quote(t)
        info = market.get_company_info(t)
        shares = sum(r.shares_now for r in lots)
        cost = sum(r.cost_basis for r in lots)
        value = shares * q["price"]
        pnl_pct = (value / cost - 1) * 100
        tr_value = sum(r.cost_basis * total_return_factor(r.ticker, r.trade_date) for r in lots)
        tr_pct = (tr_value / cost - 1) * 100
        rows.append({
            "ticker": t,
            "name": info.get("name") or t,
            "sector": _sector(info),
            "lots": len(lots),
            "shares": shares,
            "avg_cost": cost / shares,
            "price": q["price"],
            "market_value": value,
            "cost_basis": cost,
            "pnl": value - cost,
            "pnl_pct": pnl_pct,
            "total_return_value": tr_value,
            "total_return_pct": tr_pct,
            "dividend_boost_pct": tr_pct - pnl_pct,
            "day_change_pct": q["change_pct"],
            "day_pnl": shares * q["change"],
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df["weight_pct"] = df["market_value"] / df["market_value"].sum() * 100
        df = df.sort_values("market_value", ascending=False).reset_index(drop=True)
    return df


def sector_exposure(positions: pd.DataFrame) -> pd.Series:
    return positions.groupby("sector")["weight_pct"].sum().sort_values(ascending=False).round(2)


def portfolio_summary(resolved: list[ResolvedLot], positions: pd.DataFrame | None = None) -> dict:
    if positions is None:
        positions = positions_table(resolved)
    cost = float(positions["cost_basis"].sum())
    value = float(positions["market_value"].sum())
    pnl_pct = (value / cost - 1) * 100

    spy_q = market.get_quote(BENCHMARK)
    spy_price = spy_q["price"]
    day_pnl = float(positions["day_pnl"].sum())
    spy_value = sum(benchmark_lot(r).shares_now for r in resolved) * spy_price
    spy_pnl_pct = (spy_value / cost - 1) * 100

    tr_value = float(positions["total_return_value"].sum())
    tr_pct = (tr_value / cost - 1) * 100
    spy_tr_value = sum(r.cost_basis * total_return_factor(BENCHMARK, r.trade_date) for r in resolved)
    spy_tr_pct = (spy_tr_value / cost - 1) * 100

    return {
        "total_value": value,
        "total_cost": cost,
        "total_pnl": value - cost,
        "total_pnl_pct": pnl_pct,
        "day_pnl": day_pnl,
        "day_change_pct": day_pnl / (value - day_pnl) * 100 if value != day_pnl else None,
        "benchmark_day_change_pct": spy_q["change_pct"],
        "benchmark": BENCHMARK,
        "benchmark_value": float(spy_value),
        "benchmark_pnl_pct": spy_pnl_pct,
        "excess_return_pct": pnl_pct - spy_pnl_pct,
        "total_return_pct": tr_pct,
        "benchmark_total_return_pct": spy_tr_pct,
        "excess_total_return_pct": tr_pct - spy_tr_pct,
        "num_positions": len(positions),
        "largest_position": positions.iloc[0]["ticker"],
        "largest_weight_pct": float(positions.iloc[0]["weight_pct"]),
    }


def value_history(resolved: list[ResolvedLot]) -> pd.DataFrame:
    """Daily portfolio value vs. benchmark vs. dollars invested (price-based), for the chart."""
    start = min(r.trade_date for r in resolved)
    tickers = sorted({r.ticker for r in resolved} | {BENCHMARK})
    closes = {t: market.get_price_history(t, start=start)["Close"] for t in tickers}
    idx = closes[BENCHMARK].index

    out = pd.DataFrame(0.0, index=idx, columns=["portfolio", "benchmark", "invested"])
    for r in resolved:
        active = idx >= pd.Timestamp(r.trade_date)
        px = closes[r.ticker].reindex(idx).ffill()
        out["portfolio"] += (px * r.shares_now).where(active, 0.0).fillna(0.0)
        b = benchmark_lot(r)
        out["benchmark"] += (closes[BENCHMARK] * b.shares_now).where(active, 0.0)
        out["invested"] += pd.Series(r.cost_basis, index=idx).where(active, 0.0)
    return out