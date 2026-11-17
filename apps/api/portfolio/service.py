"""Portfolio views for the API (the agent's tools use the same math).

Building a portfolio prices every lot and fetches quotes, so results are kept per user for a minute.
The cache key includes the user's current holding ids, so adding or deleting a holding shows up at once."""
from __future__ import annotations

import asyncio
import math
import time
import uuid
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from datasources.market import ET
from db.repo import HoldingRecord
from portfolio import metrics
from portfolio.positions import Lot, ResolvedLot, resolve_lot

TTL_SECONDS = 60
HISTORY_RANGES = {"1m": 31, "3m": 92, "6m": 183, "1y": 366, "all": None}
MAX_HISTORY_POINTS = 400

_cache: dict[tuple, tuple[float, Any]] = {}


def clean(obj: Any, digits: int = 4) -> Any:
    """JSON-safe numbers: NaN/inf become null, floats are rounded."""
    if isinstance(obj, float):
        return None if math.isnan(obj) or math.isinf(obj) else round(obj, digits)
    if isinstance(obj, dict):
        return {k: clean(v, digits) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v, digits) for v in obj]
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if hasattr(obj, "item"):          # numpy scalars
        return clean(obj.item(), digits)
    return obj


def _key(user_id: uuid.UUID, kind: str, holdings: list[HoldingRecord], *extra) -> tuple:
    return (user_id, kind, tuple(sorted(str(h.id) for h in holdings)), *extra)


def _get(key: tuple) -> Any:
    hit = _cache.get(key)
    return hit[1] if hit and hit[0] > time.monotonic() else None


def _put(key: tuple, value: Any) -> Any:
    if len(_cache) > 500:           # tiny app: crude size cap is plenty
        _cache.clear()
    _cache[key] = (time.monotonic() + TTL_SECONDS, value)
    return value


def _resolve(holdings: list[HoldingRecord]) -> tuple[list[ResolvedLot], list[dict]]:
    resolved, errors = [], []
    for h in holdings:
        try:
            resolved.append(resolve_lot(h.to_lot()))
        except Exception as e:
            errors.append({"holding_id": str(h.id), "ticker": h.ticker, "error": str(e)})
    return resolved, errors


def _build(holdings: list[HoldingRecord]) -> dict:
    resolved, errors = _resolve(holdings)
    if not resolved:
        return {"summary": None, "positions": [], "sectors": [], "lot_errors": errors}
    positions = metrics.positions_table(resolved)
    summary = metrics.portfolio_summary(resolved, positions)
    sectors = [{"sector": s, "weight_pct": w} for s, w in metrics.sector_exposure(positions).items()]
    return {"summary": summary, "positions": positions.to_dict(orient="records"),
            "sectors": sectors, "lot_errors": errors}


async def portfolio_view(user_id: uuid.UUID, holdings: list[HoldingRecord]) -> dict:
    key = _key(user_id, "view", holdings)
    if (hit := _get(key)) is not None:
        return hit
    data = await asyncio.to_thread(_build, holdings)
    data["as_of"] = datetime.now(ET).isoformat(timespec="seconds")
    return _put(key, clean(data))


def _history(holdings: list[HoldingRecord], days: int | None) -> list[dict]:
    resolved, _ = _resolve(holdings)
    if not resolved:
        return []
    df = metrics.value_history(resolved)
    if days is not None:
        df = df[df.index >= pd.Timestamp(datetime.now(ET).date() - timedelta(days=days))]
    if len(df) > MAX_HISTORY_POINTS:   # long histories: one point per week keeps the chart light
        df = df.resample("W-FRI").last().dropna(how="all")
    return [{"date": d.date().isoformat(), "portfolio": r.portfolio, "benchmark": r.benchmark,
             "invested": r.invested} for d, r in df.iterrows()]


async def history_view(user_id: uuid.UUID, holdings: list[HoldingRecord], range_: str) -> dict:
    if range_ not in HISTORY_RANGES:
        raise ValueError(f"range must be one of {list(HISTORY_RANGES)}")
    key = _key(user_id, "history", holdings, range_)
    if (hit := _get(key)) is not None:
        return hit
    points = await asyncio.to_thread(_history, holdings, HISTORY_RANGES[range_])
    return _put(key, clean({"range": range_, "benchmark": metrics.BENCHMARK, "points": points}, 2))


# ---- CSV import ----
TICKER_HEADERS = {"ticker", "symbol"}
DATE_HEADERS = {"date", "purchase_date", "purchase date", "bought", "trade date", "trade_date"}
SHARES_HEADERS = {"shares", "quantity", "qty"}
AMOUNT_HEADERS = {"amount", "cost", "dollars", "invested", "amount_usd"}
MAX_IMPORT_ROWS = 200


def _parse_date(text: str) -> date:
    text = text.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unreadable date '{text}' (use YYYY-MM-DD or MM/DD/YYYY)")


def _parse_number(text: str) -> float | None:
    text = (text or "").strip().replace(",", "").replace("$", "")
    return float(text) if text else None


def parse_csv(text: str) -> list[dict]:
    """CSV text -> one dict per data row: either parsed fields or an error. Header names are flexible."""
    import csv
    import io

    reader = csv.DictReader(io.StringIO(text.strip()))
    if not reader.fieldnames:
        raise ValueError("The file is empty.")
    columns = {h: (h or "").strip().lower() for h in reader.fieldnames}

    def pick(names: set[str]) -> str | None:
        return next((orig for orig, low in columns.items() if low in names), None)

    c_ticker, c_date = pick(TICKER_HEADERS), pick(DATE_HEADERS)
    c_shares, c_amount = pick(SHARES_HEADERS), pick(AMOUNT_HEADERS)
    if not c_ticker or not c_date or not (c_shares or c_amount):
        raise ValueError("Need columns for ticker, date, and shares or amount "
                         "(e.g. a header row of: ticker,date,shares,amount).")
    rows = []
    for raw in reader:
        if not any((v or "").strip() for v in raw.values() if isinstance(v, str)):
            continue                                       # skip lines with only commas
        if len(rows) >= MAX_IMPORT_ROWS:
            raise ValueError(f"At most {MAX_IMPORT_ROWS} rows per import.")
        # line_num is the line in the file (blank lines included), so errors point at the right row.
        row: dict[str, Any] = {"row": reader.line_num, "ticker": (raw.get(c_ticker) or "").strip().upper()}
        try:
            row["purchase_date"] = _parse_date(raw.get(c_date) or "")
            row["shares"] = _parse_number(raw.get(c_shares) or "") if c_shares else None
            row["amount"] = _parse_number(raw.get(c_amount) or "") if c_amount else None
        except ValueError as e:
            row["error"] = str(e)
        rows.append(row)
    return rows


def _check_row(row: dict) -> dict:
    if row.get("error"):
        return {**row, "status": "error"}
    try:
        r = resolve_lot(Lot(row["ticker"], row["purchase_date"], shares=row["shares"], amount=row["amount"]))
    except Exception as e:
        return {**row, "status": "error", "error": str(e)}
    return {**row, "ticker": r.ticker, "status": "ok", "trade_date": r.trade_date, "price_paid": r.price_paid,
            "shares_now": r.shares_now, "cost_basis": r.cost_basis, "note": r.note}


async def check_rows(rows: list[dict]) -> list[dict]:
    """Validate and price every row (in parallel threads; prices are cached per ticker)."""
    return clean(list(await asyncio.gather(*(asyncio.to_thread(_check_row, r) for r in rows))))