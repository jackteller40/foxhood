"""Turn user-entered purchases into split-aware positions with a real cost basis."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from datasources import market

LOOKAHEAD_DAYS = 10  # enough to skip weekends + holiday stretches


@dataclass(frozen=True)
class Lot:
    """One purchase as the user enters it. Give exactly one of shares or amount.
    `shares` is the count bought on that date (pre-split if a split happened later)."""
    ticker: str
    purchase_date: date
    shares: float | None = None
    amount: float | None = None


@dataclass(frozen=True)
class ResolvedLot:
    ticker: str
    requested_date: date
    trade_date: date          # actual trading day used
    price_paid: float         # price as it actually traded that day
    adj_price: float          # same price in today's split-adjusted terms
    split_factor: float       # cumulative splits since purchase (10.0 = one 10-for-1)
    shares_bought: float      # share count on the purchase date
    shares_now: float         # share count today, after splits
    cost_basis: float
    note: str | None = None


def _split_factor_after(ticker: str, trade_date: date) -> float:
    """Product of all splits strictly after the trade date. A split dated the same day
    as the trade is already reflected in that day's price."""
    splits = market.get_splits(ticker)
    if splits.empty:
        return 1.0
    later = splits[(splits.index > pd.Timestamp(trade_date)) & (splits > 0)]
    return float(later.prod()) if not later.empty else 1.0


def resolve_lot(lot: Lot) -> ResolvedLot:
    ticker = lot.ticker.strip().upper()

    if (lot.shares is None) == (lot.amount is None):
        raise ValueError("Enter either a share count or a dollar amount (exactly one).")
    qty = lot.shares if lot.shares is not None else lot.amount
    if qty <= 0:
        raise ValueError("Shares or amount must be greater than zero.")
    if lot.purchase_date > date.today():
        raise ValueError("Purchase date can't be in the future.")

    bars = market.get_price_history(
        ticker,
        start=lot.purchase_date,
        end=lot.purchase_date + timedelta(days=LOOKAHEAD_DAYS),
    )
    if bars.empty:
        raise ValueError(
            f"No closing price for {ticker} on or after {lot.purchase_date}. "
            "Check the ticker; the date may be before it listed, or today's close isn't in yet."
        )

    trade_date = bars.index[0].date()
    adj_price = float(bars["Close"].iloc[0])
    factor = _split_factor_after(ticker, trade_date)
    price_paid = adj_price * factor

    if lot.shares is not None:
        shares_bought = float(lot.shares)
        cost_basis = shares_bought * price_paid
    else:
        cost_basis = float(lot.amount)
        shares_bought = cost_basis / price_paid

    note = None
    if trade_date != lot.purchase_date:
        note = f"Market closed on {lot.purchase_date}; used next trading day {trade_date}."

    return ResolvedLot(
        ticker=ticker,
        requested_date=lot.purchase_date,
        trade_date=trade_date,
        price_paid=price_paid,
        adj_price=adj_price,
        split_factor=factor,
        shares_bought=shares_bought,
        shares_now=shares_bought * factor,
        cost_basis=cost_basis,
        note=note,
    )